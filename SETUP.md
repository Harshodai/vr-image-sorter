# Setup & Operations Guide

End-to-end install, then how to tune for correctness and for speed.

Everything below was verified on macOS from a clean clone. The Windows commands
are the same tool driven the same way, but **have not been run on Windows** —
`npm run doctor` is the gate. Run it first; if it prints all five rows without
`NOT FOUND`, continue.

---

## 1. Install prerequisites

### Windows (PowerShell, one time)

```powershell
winget install OpenJS.NodeJS.LTS
winget install Python.Python.3.12
winget install Git.Git
winget install astral-sh.uv
```

`npx` ships with Node — the first line is what installs it. `uv` is optional but
cuts the Python install from minutes to seconds.

**Close and reopen the terminal**, then verify:

```powershell
node -v; npx -v; python --version; git --version
```

### macOS

```bash
brew install node python@3.12 git uv
```

### Linux

```bash
sudo apt-get install -y nodejs npm python3 python3-venv git libgl1 libglib2.0-0
```

`libgl1` and `libglib2.0-0` are required by OpenCV and are easy to miss — without
them the backend imports fail with an obscure `libGL.so.1` error.

---

## 2. Install the app

```bash
git clone https://github.com/Harshodai/vr-image-sorter.git
cd vr-image-sorter
npm run doctor
npm run setup
```

`doctor` before `setup` on purpose: it tells you what is missing in one line
instead of failing halfway through a five-minute install.

**Install with the clone, not with `npx`.** `npx github:Harshodai/vr-image-sorter doctor`
works fine as a pre-check, but npx unpacks into a cache npm can clear at any
time — that is no place for a virtualenv and downloaded OCR models, and `git pull`
cannot work there because npm strips `.git`.

---

## 3. Run

### Web UI — for small batches and for reviewing

```bash
npm start
```

Opens `http://localhost:8080`. If a port is taken it says so and names the
override:

```bash
PORT=8010 UI_PORT=8090 npm start          # macOS / Linux
```
```powershell
$env:PORT=8010; $env:UI_PORT=8090; npm start   # Windows
```

### Folder mode — for the real backlog

The browser cannot hold 100,000 images: every one costs a file handle plus a
preview, and a crash loses the run. The UI caps at 2,000 for that reason. Use
folder mode instead — it reads from disk and records progress after every image.

```bash
npm run sort -- --input C:\photos --output C:\sorted --copy
```

| flag | effect |
|---|---|
| `--copy` | leave the input folder untouched (recommended for the first run) |
| `--resume` | skip images already recorded; use after any interruption |
| `--recursive` | descend into subfolders |
| `--workers N` | images in flight (default: auto from core count) |

Resume after a crash, reboot or Ctrl-C:

```bash
npm run sort -- --input C:\photos --output C:\sorted --copy --resume
```

Ongoing intake instead of a backlog:

```bash
npm run watch -- --input C:\dropbox --output C:\sorted
```

### Output layout

| folder | meaning |
|---|---|
| `renamed/` | trusted — renamed to `VR<digits>.<ext>` |
| `review/` | a code was read but not trusted — **keeps its original filename** |
| `failed/` | nothing readable — keeps its original filename |
| `manifest.jsonl` | every image with code, confidence, method, reason — audit trail and resume index |
| `review.csv` | the review queue as a spreadsheet |

Confirm the review queue in the UI (magnify the label first), or in bulk:

```bash
# open sorted/review.csv, fill in the `corrected_code` column, then:
npm run apply -- --csv C:\sorted\review.csv --output C:\sorted
```

---

## 4. Accuracy

### What "100%" can and cannot mean

Two different things get called 100%, and only one is achievable:

- **Zero wrong renames** — nothing is ever filed under the wrong code. This is
  achievable, and the system is built around it.
- **Zero human effort** — every image identified automatically, nobody checks
  anything. This is not achievable with OCR on hand-held photographs, and any
  tool promising it is guessing on the images it cannot read.

The design chooses the first. An image is renamed automatically only when the
read is trustworthy; otherwise it keeps its original filename and waits for a
person. Three things disqualify an automatic rename:

1. **Confidence below `OCR_MIN_CONFIDENCE`** (default `0.90`).
2. **Character substitution** — the code matched only after `O`→`0` / `I`→`1`
   fixes. That can rescue a real read or invent a plausible wrong one, and
   nothing in the text distinguishes the two cases.
3. **Conflict** — two different codes both read confidently. One is wrong and
   there is no basis for choosing.

Barcodes (Code128/QR) carry their own checksums, so a successful barcode decode
is self-verifying and never goes to review. Barcode reads are also the fast path,
around 0.4–0.6 s versus 2–4 s when OCR has to work for it.

### Calibrate against your own images

The shipped `0.90` came from 22 images. That is enough to show the pipeline
works and nowhere near enough to promise a rate on 100,000. Replace it with a
measurement as soon as you have labelled images.

Two ways to supply labels — a folder whose filenames already contain the correct
code, or a CSV:

```bash
cd backend
python calibrate.py --input ../labelled_images
python calibrate.py --csv ../labelled.csv      # columns: file,code
```

It scans each image once, then replays the decision across thresholds:

```
 threshold   WRONG    AUTO  REVIEW  FAILED    auto %
------------------------------------------------------------
     0.900       0       7       0       0    100.0%
     0.950       0       6       1       0     85.7%
     0.995       0       2       5       0     28.6%
```

`WRONG` must be zero. Raising the threshold moves images from `AUTO` to
`REVIEW` — it buys safety with your operators' time. Take the lowest threshold
with zero wrong, then **add margin**: a 100k backlog contains worse photographs
than any sample.

It also lists every image read as something other than its label. Check those by
eye — at this stage a wrong *label* and a wrong *read* look identical.

Then apply it:

```bash
OCR_MIN_CONFIDENCE=0.95 npm run sort -- --input ./photos --output ./sorted
```
```powershell
$env:OCR_MIN_CONFIDENCE=0.95; npm run sort -- --input .\photos --output .\sorted
```

### Recovering images that failed

Retrying re-scans at a higher resolution (`RETRY_SCAN_DIMENSION`, default 2000px
vs the normal 1200px), so it is a genuinely different attempt rather than a
repeat of deterministic work. In the UI that is the retry button. For a folder
run, re-sort the `failed/` directory at a higher resolution:

```bash
npm run sort -- --input ./sorted/failed --output ./sorted-pass2 --max-dim 2400
```

Higher `--max-dim` reads small label text better and costs roughly quadratic
time, so use it on the leftovers, not the whole backlog.

---

## 5. Speed

### Measured

On a 10-core host, 66 images, after the accuracy work:

| | |
|---|---|
| throughput | **2.03 img/s** at `OCR_POOL_SIZE=6` |
| 100,000 images | **~13.7 hours** |
| barcode hit | 0.4–0.6 s/image |
| OCR fallback | 2–4 s/image |
| memory | ~45 MB per idle engine, ~2.4 GB peak during a batch |

### Worker count — the setting that matters most

Throughput peaks around **0.6 × core count** and gets *worse* above roughly 8,
as engines start contending for cores and memory bandwidth. The pool is sized
automatically; override only if you have measured otherwise:

```bash
OCR_POOL_SIZE=6 npm run sort -- --input ./photos --output ./sorted
```

Rough expectations by machine:

| cores | auto pool | expected | 100k |
|---|---|---|---|
| 4 | 2 | ~0.9 img/s | ~30 h |
| 8 | 5 | ~1.7 img/s | ~16 h |
| 10+ | 6–8 | ~2.0 img/s | ~14 h |

Two things that look like tuning opportunities and are not:

- **Do not raise `WEB_WORKERS` above 1.** Upload sessions live in process
  memory; extra worker processes silently lose chunks of large uploads. Parallelism
  comes from the engine pool, which benchmarked faster than multiple processes anyway.
- **Do not raise `OCR_THREADS_PER_ENGINE`.** ONNX Runtime defaults to grabbing
  every core per engine, which is why one process used to saturate the CPU and
  extra workers made no difference at all.

### Trading accuracy for speed, deliberately

`OCR_EARLY_EXIT_CONFIDENCE` (default `0.98`) is the stopping rule: a clean read
at or above it ends the remaining rotation passes. Lower is faster with less
cross-checking; raise it toward `1.0` to always sweep every orientation.

```bash
OCR_EARLY_EXIT_CONFIDENCE=0.995 npm run sort -- --input ./photos --output ./sorted
```

---

## 6. The 100k playbook

1. **Calibrate first.** Label 200–500 images spanning the hard cases — glare,
   sideways labels, blur, no barcode — and run `calibrate.py`. Set
   `OCR_MIN_CONFIDENCE` from the result plus margin. Do this before the big run,
   not after.
2. **Pilot on 1,000 images.** Confirm the throughput and the review rate on your
   actual hardware, and extrapolate. A 5% review rate on 100k is 5,000 images for
   someone to look at — worth knowing in advance.
3. **Run with `--copy`.** The originals stay untouched, so a bad threshold costs
   a re-run rather than your only copy.
4. **Expect to resume.** 14 hours will be interrupted. `--resume` continues from
   the manifest; it never redoes finished work.
5. **Work the review queue.** Use the UI's magnifier, or `review.csv` plus
   `npm run apply`.
6. **Spot-check `renamed/` before filing anything.** Pull 50 at random and check
   them by eye. This is the only step that catches a systematic misread, and it
   costs fifteen minutes.

---

## 7. Configuration reference

Set as environment variables.

| variable | default | what it does |
|---|---|---|
| `OCR_MIN_CONFIDENCE` | `0.90` | below this, an image goes to review instead of being renamed |
| `OCR_EARLY_EXIT_CONFIDENCE` | `0.98` | a clean read this good stops the remaining passes |
| `OCR_POOL_SIZE` | auto (`0.6 × cores`, 2–8) | OCR engines, i.e. images processed at once |
| `BATCH_CONCURRENCY` | pool + 2 | images in flight; slight oversubscription keeps the pool busy |
| `OCR_THREADS_PER_ENGINE` | `1` | leave at 1 — see above |
| `MAX_SCAN_DIMENSION` | `1200` | working resolution; higher reads small text better, costs ~quadratic time |
| `RETRY_SCAN_DIMENSION` | `2000` | resolution used on an explicit retry |
| `SCAN_TIMEOUT_SECONDS` | `120` | per-image ceiling |
| `SESSION_TTL_SECONDS` | `86400` | how long a web session's files survive |
| `ENABLE_BARCODE_SCANNER` | `True` | set `False` to force the OCR path |
| `WEB_WORKERS` | `1` | leave at 1 — see above |
| `PORT` / `UI_PORT` | `8000` / `8080` | ports |

---

## 8. Updating

```bash
cd vr-image-sorter
npm run update
```

Pulls the latest code and re-runs setup. If you have edited files locally it
will refuse rather than overwrite them — commit or stash first.

---

## 9. Troubleshooting

| symptom | cause and fix |
|---|---|
| `Backend port 8000 is already in use` | something else owns it. `netstat -ano \| findstr :8000` (Windows) or `lsof -nP -iTCP:8000 -sTCP:LISTEN`. Or set `PORT`. |
| `Python 3.9+ not found` after installing it | the terminal has a stale PATH — open a new one. |
| `Not set up yet. Run setup first.` | the venv is missing; `npm run setup`. |
| `libGL.so.1: cannot open shared object file` | Linux only: `sudo apt-get install libgl1 libglib2.0-0`. |
| `manifest.jsonl exists. Use --resume` | a previous run wrote to that output folder. Add `--resume`, or point at a fresh folder. |
| Everything lands in `review/` | `OCR_MIN_CONFIDENCE` is too high for these images. Run `calibrate.py`. |
| Slower than the table above | check `OCR_POOL_SIZE` against `0.6 × cores`, and that nothing else is using the CPU. |
| Browser tab freezes on a big selection | you exceeded what a browser can hold. Use folder mode. |

---

## 10. Checking it works

```bash
npm run doctor            # prerequisites
make test                 # accuracy against the labelled images in ./input
make bench                # timing on this machine
```

`make test` expects 7/7 with zero wrong renames. On Windows, run the underlying
scripts directly (`make` is not native there):

```powershell
backend\.venv\Scripts\python.exe test_pipeline.py
```

---

## What is not yet proven

The accuracy evidence in this repo is 22 images: 22/22 renamed correctly, zero
wrong. That demonstrates the pipeline works. It is **not** proof of an accuracy
rate at 100,000, and no honest reading of it says otherwise.

Section 4's calibration step is what converts this into a number you can defend.
Until you have run it on your own labelled images, treat the review queue as
load-bearing rather than optional, and keep the spot-check in step 6 of the
playbook.
