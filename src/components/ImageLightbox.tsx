import { X, ZoomIn, ZoomOut, Maximize, Move } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { VisuallyHidden } from '@radix-ui/react-visually-hidden';
import { useState, useEffect, useRef, useCallback } from 'react';
import { getAuthenticatedImageUrl } from '@/hooks/useProcessing';

interface ImageLightboxProps {
  isOpen: boolean;
  onClose: () => void;
  imageSrc: string;
  imageName: string;
  /** Shown above the image — used to state what the reader should verify. */
  caption?: string;
}

const MIN_ZOOM = 1;
const MAX_ZOOM = 8;
const ZOOM_STEP = 0.4;

/**
 * Full-screen viewer with a real magnifier. Label text is small and often the
 * only way to confirm a code by eye, so scrolling to zoom, dragging to pan and
 * double-clicking to jump to 3x all matter more than they would for a gallery.
 */
export function ImageLightbox({ isOpen, onClose, imageSrc, imageName, caption }: ImageLightboxProps) {
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragStart = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  const reset = useCallback(() => {
    setZoom(1);
    setOffset({ x: 0, y: 0 });
  }, []);

  useEffect(() => {
    if (!isOpen || !imageSrc) {
      setLoadedSrc(null);
      setLoading(true);
      setError(false);
      reset();
      return;
    }

    let mounted = true;
    let blobUrl: string | null = null;

    async function loadImage() {
      try {
        setLoading(true);
        setError(false);
        blobUrl = await getAuthenticatedImageUrl(imageSrc);
        if (mounted) {
          setLoadedSrc(blobUrl);
          setLoading(false);
        }
      } catch (err) {
        if (mounted) {
          setError(true);
          setLoading(false);
        }
      }
    }

    loadImage();
    return () => {
      mounted = false;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [isOpen, imageSrc, reset]);

  // Zooming back out to fit should not leave the image parked off-screen.
  const applyZoom = useCallback((next: number) => {
    const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next));
    setZoom(clamped);
    if (clamped === MIN_ZOOM) setOffset({ x: 0, y: 0 });
  }, []);

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    applyZoom(zoom + (e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP));
  }, [zoom, applyZoom]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (zoom === MIN_ZOOM) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    dragStart.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
    setDragging(true);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragStart.current) return;
    setOffset({
      x: dragStart.current.ox + (e.clientX - dragStart.current.x),
      y: dragStart.current.oy + (e.clientY - dragStart.current.y),
    });
  };

  const endDrag = () => {
    dragStart.current = null;
    setDragging(false);
  };

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '+' || e.key === '=') applyZoom(zoom + ZOOM_STEP);
      if (e.key === '-') applyZoom(zoom - ZOOM_STEP);
      if (e.key === '0') reset();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, zoom, applyZoom, reset]);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-6xl w-[96vw] h-[92vh] p-0 bg-background/95 backdrop-blur-sm border-border overflow-hidden">
        <VisuallyHidden>
          <DialogTitle>{imageName}</DialogTitle>
        </VisuallyHidden>

        <div className="absolute top-2 right-2 z-20 flex items-center gap-1 bg-background/85 rounded-lg p-1 shadow">
          <Button variant="ghost" size="icon" title="Zoom out (-)" onClick={() => applyZoom(zoom - ZOOM_STEP)} disabled={zoom <= MIN_ZOOM}>
            <ZoomOut className="w-4 h-4" />
          </Button>
          <span className="text-xs tabular-nums w-12 text-center text-muted-foreground">
            {Math.round(zoom * 100)}%
          </span>
          <Button variant="ghost" size="icon" title="Zoom in (+)" onClick={() => applyZoom(zoom + ZOOM_STEP)} disabled={zoom >= MAX_ZOOM}>
            <ZoomIn className="w-4 h-4" />
          </Button>
          <Button variant="ghost" size="icon" title="Reset (0)" onClick={reset} disabled={zoom === MIN_ZOOM}>
            <Maximize className="w-4 h-4" />
          </Button>
          <Button variant="ghost" size="icon" title="Close" onClick={onClose}>
            <X className="w-5 h-5" />
          </Button>
        </div>

        {caption && (
          <div className="absolute top-2 left-2 z-20 max-w-[60%] rounded-lg bg-background/85 px-3 py-1.5 text-xs text-foreground shadow">
            {caption}
          </div>
        )}

        <div
          className="w-full h-full flex flex-col items-center justify-center p-4 overflow-hidden select-none"
          onWheel={onWheel}
        >
          {loading && <div className="w-32 h-32 bg-muted animate-pulse rounded-lg" />}
          {error && <div className="text-muted-foreground">Failed to load image</div>}
          {!loading && !error && loadedSrc && (
            <img
              src={loadedSrc}
              alt={imageName}
              draggable={false}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onDoubleClick={() => (zoom > MIN_ZOOM ? reset() : applyZoom(3))}
              style={{
                transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
                cursor: zoom > MIN_ZOOM ? (dragging ? 'grabbing' : 'grab') : 'zoom-in',
                transition: dragging ? 'none' : 'transform 120ms ease-out',
              }}
              className="max-w-full max-h-[calc(92vh-90px)] object-contain rounded-lg will-change-transform"
            />
          )}
          <p className="mt-3 text-sm text-muted-foreground font-medium truncate max-w-full flex items-center gap-2">
            {zoom > MIN_ZOOM && <Move className="w-3.5 h-3.5" />}
            {imageName}
            <span className="text-xs opacity-70">
              — scroll to zoom, double-click to magnify
            </span>
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
