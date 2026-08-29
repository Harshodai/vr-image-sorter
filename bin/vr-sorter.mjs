#!/usr/bin/env node
/**
 * Single-command launcher, so a Windows operator never has to remember the
 * Python/venv/uvicorn/vite incantations.
 *
 *   npx github:Harshodai/vr-image-sorter setup
 *   npx github:Harshodai/vr-image-sorter start
 *   npx github:Harshodai/vr-image-sorter update
 *   npx github:Harshodai/vr-image-sorter sort --input C:\photos --output C:\sorted
 *
 * Node is the only thing that has to be installed up front; everything else is
 * checked for and reported with the exact command to fix it.
 */
import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import process from 'node:process';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const IS_WIN = process.platform === 'win32';
const VENV = join(ROOT, 'backend', '.venv');
const VENV_BIN = join(VENV, IS_WIN ? 'Scripts' : 'bin');
const VENV_PY = join(VENV_BIN, IS_WIN ? 'python.exe' : 'python');

const c = {
  dim: s => `\x1b[2m${s}\x1b[0m`,
  red: s => `\x1b[31m${s}\x1b[0m`,
  green: s => `\x1b[32m${s}\x1b[0m`,
  yellow: s => `\x1b[33m${s}\x1b[0m`,
  bold: s => `\x1b[1m${s}\x1b[0m`,
};

function which(cmd) {
  const probe = spawnSync(IS_WIN ? 'where' : 'which', [cmd], { encoding: 'utf8', shell: IS_WIN });
  return probe.status === 0 ? probe.stdout.split(/\r?\n/)[0].trim() : null;
}

function run(cmd, args, opts = {}) {
  const res = spawnSync(cmd, args, { stdio: 'inherit', cwd: ROOT, shell: IS_WIN, ...opts });
  if (res.error) throw res.error;
  return res.status ?? 1;
}

/** Find a Python that is new enough; version matters because of typing syntax used in the backend. */
function findPython() {
  for (const cmd of IS_WIN ? ['python', 'py', 'python3'] : ['python3', 'python']) {
    if (!which(cmd)) continue;
    const out = spawnSync(cmd, ['--version'], { encoding: 'utf8', shell: IS_WIN });
    const m = /Python 3\.(\d+)/.exec(`${out.stdout}${out.stderr}`);
    if (m && Number(m[1]) >= 9) return cmd;
  }
  return null;
}

function requirePython() {
  const py = findPython();
  if (!py) {
    console.error(c.red('Python 3.9+ not found.'));
    console.error(IS_WIN
      ? '  Install it with:  winget install Python.Python.3.12\n  Then open a NEW terminal and try again.'
      : '  Install it with:  brew install python@3.12');
    process.exit(1);
  }
  return py;
}

function cmdDoctor() {
  const py = findPython();
  const rows = [
    ['node', process.version],
    ['python', py ? spawnSync(py, ['--version'], { encoding: 'utf8', shell: IS_WIN }).stdout.trim() : c.red('NOT FOUND (3.9+ required)')],
    ['uv', which('uv') ? 'found (fast installs)' : c.yellow('not found — pip fallback, slower')],
    ['git', which('git') ? 'found' : c.yellow('not found — `update` will not work')],
    ['venv', existsSync(VENV_PY) ? 'installed' : c.yellow('missing — run `setup`')],
    ['node_modules', existsSync(join(ROOT, 'node_modules')) ? 'installed' : c.yellow('missing — run `setup`')],
  ];
  for (const [k, v] of rows) console.log(`  ${k.padEnd(14)}${v}`);
  return 0;
}

function cmdSetup() {
  const py = requirePython();
  console.log(c.bold('\n1/3  Python environment'));
  if (which('uv')) {
    if (run('uv', ['venv', VENV, '--python', py])) return 1;
    if (run('uv', ['pip', 'install', '-r', join(ROOT, 'backend', 'requirements.txt')],
            { env: { ...process.env, VIRTUAL_ENV: VENV } })) return 1;
  } else {
    console.log(c.yellow('  uv not found — using pip. Install uv for much faster setup:'));
    console.log(c.dim(IS_WIN ? '    winget install astral-sh.uv' : '    brew install uv'));
    if (run(py, ['-m', 'venv', VENV])) return 1;
    if (run(VENV_PY, ['-m', 'pip', 'install', '--upgrade', 'pip'])) return 1;
    if (run(VENV_PY, ['-m', 'pip', 'install', '-r', join(ROOT, 'backend', 'requirements.txt')])) return 1;
  }

  console.log(c.bold('\n2/3  OCR models'));
  if (run(VENV_PY, ['preload_models.py'], { cwd: join(ROOT, 'backend') })) return 1;

  console.log(c.bold('\n3/3  Frontend'));
  if (run('npm', ['ci', '--prefer-offline', '--no-audit', '--fund=false'])) {
    if (run('npm', ['install', '--no-audit', '--fund=false'])) return 1;
  }

  console.log(c.green('\nSetup complete. Start it with:  npx github:Harshodai/vr-image-sorter start'));
  return 0;
}

function requireSetup() {
  if (existsSync(VENV_PY)) return;
  console.error(c.red('Not set up yet. Run `setup` first.'));
  process.exit(1);
}

function cmdUpdate() {
  if (!which('git')) {
    console.error(c.red('git not found, cannot update.'));
    return 1;
  }
  console.log(c.bold('Pulling latest...'));
  if (run('git', ['pull', '--ff-only'])) {
    console.error(c.red('Pull failed. You may have local changes — commit or stash them first.'));
    return 1;
  }
  // Dependencies and OCR models can change with the code, so re-run setup.
  return cmdSetup();
}

function cmdStart() {
  requireSetup();
  const port = process.env.PORT || '8000';
  const uiPort = process.env.UI_PORT || '8080';

  const backend = spawn(join(VENV_BIN, IS_WIN ? 'uvicorn.exe' : 'uvicorn'),
    ['main:app', '--host', '0.0.0.0', '--port', port],
    { cwd: join(ROOT, 'backend'), stdio: 'inherit', shell: IS_WIN,
      env: { ...process.env, OMP_NUM_THREADS: '1', MKL_NUM_THREADS: '1' } });

  const frontend = spawn('npm', ['run', 'dev', '--', '--port', uiPort],
    { cwd: ROOT, stdio: 'inherit', shell: IS_WIN,
      env: { ...process.env, VITE_API_URL: `http://localhost:${port}` } });

  console.log(c.green(`\n  UI      http://localhost:${uiPort}`));
  console.log(c.green(`  API     http://localhost:${port}/docs\n`));

  const shutdown = () => { backend.kill(); frontend.kill(); process.exit(0); };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
  // If either half dies the other is useless, so take both down.
  backend.on('exit', shutdown);
  frontend.on('exit', shutdown);
  return null; // long-running
}

function cmdSort(argv) {
  requireSetup();
  return run(VENV_PY, ['cli.py', 'sort', ...argv], {
    cwd: join(ROOT, 'backend'),
    env: { ...process.env, OMP_NUM_THREADS: '1', MKL_NUM_THREADS: '1' },
  });
}

function cmdWatch(argv) {
  requireSetup();
  return run(VENV_PY, ['cli.py', 'watch', ...argv], {
    cwd: join(ROOT, 'backend'),
    env: { ...process.env, OMP_NUM_THREADS: '1', MKL_NUM_THREADS: '1' },
  });
}

function cmdApply(argv) {
  requireSetup();
  return run(VENV_PY, ['cli.py', 'apply', ...argv], { cwd: join(ROOT, 'backend') });
}

function usage() {
  console.log(`
${c.bold('vr-sorter')} — saree image sorter

  ${c.bold('doctor')}   check what is installed
  ${c.bold('setup')}    install Python deps, OCR models and frontend deps
  ${c.bold('update')}   pull the latest code, then re-run setup
  ${c.bold('start')}    run the web UI (http://localhost:8080)
  ${c.bold('sort')}     process a folder    --input <dir> --output <dir> [--resume] [--copy]
  ${c.bold('watch')}    process new files as they land in a folder
  ${c.bold('apply')}    apply corrected codes  --csv <review.csv> --output <dir>

Sorting 100k images is a folder job, not a browser job:
  npx github:Harshodai/vr-image-sorter sort --input ./photos --output ./sorted --resume
`);
  return 0;
}

const [command, ...rest] = process.argv.slice(2);
const table = {
  doctor: cmdDoctor, setup: cmdSetup, update: cmdUpdate, start: cmdStart,
  sort: () => cmdSort(rest), watch: () => cmdWatch(rest), apply: () => cmdApply(rest),
  help: usage, '--help': usage, '-h': usage, undefined: usage,
};
const handler = table[command];
if (!handler) {
  console.error(c.red(`Unknown command: ${command}`));
  process.exit(usage() || 1);
}
const code = handler();
if (code !== null) process.exit(code);
