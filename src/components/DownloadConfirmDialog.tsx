import { AlertTriangle, Search } from 'lucide-react';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';

interface DownloadConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  processedCount: number;
  reviewCount: number;
  failedCount: number;
}

/**
 * Shown before any ZIP leaves the app. Renaming is irreversible once these
 * files are filed into inventory, so the last cheap moment to catch a bad read
 * is here — hence the explicit nudge to magnify a few before downloading.
 */
export function DownloadConfirmDialog({
  open, onOpenChange, onConfirm, processedCount, reviewCount, failedCount,
}: DownloadConfirmDialogProps) {
  const outstanding = reviewCount + failedCount;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Search className="w-5 h-5 text-primary" />
            Check before you download
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-3 text-sm">
              <p>
                You are about to download <strong>{processedCount}</strong> renamed image
                {processedCount === 1 ? '' : 's'}. Click any image and use the magnifier to
                read its label — once these are filed into inventory, a wrong name is hard
                to trace back.
              </p>

              {outstanding > 0 && (
                <div className="flex gap-2 rounded-md border border-warning/40 bg-warning/10 p-2.5 text-foreground">
                  <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />
                  <span>
                    {reviewCount > 0 && (
                      <>
                        <strong>{reviewCount}</strong> image{reviewCount === 1 ? '' : 's'} still
                        need{reviewCount === 1 ? 's' : ''} your confirmation
                        {failedCount > 0 && ', and '}
                      </>
                    )}
                    {failedCount > 0 && (
                      <>
                        <strong>{failedCount}</strong> could not be read at all
                      </>
                    )}
                    . They are <em>not</em> in this ZIP.
                  </span>
                </div>
              )}
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Go back and check</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>Download anyway</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
