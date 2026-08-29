import { useState } from 'react';
import { AlertTriangle, Check, Maximize2, Loader2 } from 'lucide-react';
import { ReviewFile } from '@/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { AuthenticatedImage } from './AuthenticatedImage';
import { toast } from 'sonner';

interface ReviewSectionProps {
  files: ReviewFile[];
  onConfirm: (storedName: string, code: string) => Promise<boolean>;
  onMagnify: (src: string, name: string, caption: string) => void;
}

const VR_CODE = /^VR\d{4,8}$/i;

/**
 * The images the scanner read but would not trust. They keep their original
 * filenames until a human types or accepts a code, so a bad read can never
 * silently become a renamed file.
 */
export function ReviewSection({ files, onConfirm, onMagnify }: ReviewSectionProps) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Set<string>>(new Set());

  if (files.length === 0) return null;

  const codeFor = (f: ReviewFile) => edits[f.storedName] ?? f.suggestedCode;

  const confirm = async (f: ReviewFile) => {
    const code = codeFor(f).trim().toUpperCase();
    if (!VR_CODE.test(code)) {
      toast.error('Enter a code like VR12345 (VR followed by 4-8 digits).');
      return;
    }
    setBusy(prev => new Set(prev).add(f.storedName));
    try {
      const ok = await onConfirm(f.storedName, code);
      toast[ok ? 'success' : 'error'](ok ? `Saved as ${code}` : 'Could not save that code');
    } finally {
      setBusy(prev => {
        const next = new Set(prev);
        next.delete(f.storedName);
        return next;
      });
    }
  };

  return (
    <div className="border border-warning/30 rounded-lg p-4 bg-warning/5 mb-8">
      <div className="flex items-start gap-2 mb-4">
        <div className="w-8 h-8 rounded-full bg-warning/20 flex items-center justify-center shrink-0">
          <AlertTriangle className="w-4 h-4 text-warning" />
        </div>
        <div>
          <h3 className="font-semibold text-foreground">Needs your eyes ({files.length})</h3>
          <p className="text-sm text-muted-foreground">
            A code was read but not confidently enough to rename the file. These keep their
            original names until you confirm. Click an image to magnify the label first.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        {files.map(file => {
          const isBusy = busy.has(file.storedName);
          const caption = `${file.reason} — check the label before accepting`;
          return (
            <div
              key={file.storedName}
              className="flex flex-col sm:flex-row gap-3 items-start sm:items-center rounded-lg border border-border bg-background/60 p-3"
            >
              <div className="relative w-20 h-20 rounded-md overflow-hidden bg-muted shrink-0 group">
                {file.preview && (
                  <>
                    <AuthenticatedImage
                      src={file.preview}
                      alt={file.originalName}
                      className="w-full h-full object-cover cursor-zoom-in"
                      onClick={() => onMagnify(file.preview!, file.originalName, caption)}
                    />
                    <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                      <Maximize2 className="w-5 h-5 text-white" />
                    </div>
                  </>
                )}
              </div>

              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">{file.originalName}</p>
                <p className="text-xs text-muted-foreground">
                  {file.reason} · confidence {(file.confidence * 100).toFixed(1)}%
                </p>
                {file.alternatives.length > 1 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {file.alternatives.map(alt => (
                      <button
                        key={alt.code}
                        type="button"
                        onClick={() => setEdits(p => ({ ...p, [file.storedName]: alt.code }))}
                        className="text-[11px] px-1.5 py-0.5 rounded border border-border hover:bg-accent transition-colors"
                        title={`Use ${alt.code} (${(alt.confidence * 100).toFixed(1)}%)`}
                      >
                        {alt.code} · {(alt.confidence * 100).toFixed(0)}%
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 shrink-0 w-full sm:w-auto">
                <Input
                  value={codeFor(file)}
                  onChange={e => setEdits(p => ({ ...p, [file.storedName]: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && confirm(file)}
                  className="h-9 w-32 font-mono text-sm"
                  aria-label={`VR code for ${file.originalName}`}
                  disabled={isBusy}
                />
                <Button size="sm" className="h-9 gap-1" onClick={() => confirm(file)} disabled={isBusy}>
                  {isBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  Confirm
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
