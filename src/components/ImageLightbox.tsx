import { X } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { VisuallyHidden } from '@radix-ui/react-visually-hidden';
import { useState, useEffect } from 'react';
import { getAuthenticatedImageUrl } from '@/hooks/useProcessing';

interface ImageLightboxProps {
  isOpen: boolean;
  onClose: () => void;
  imageSrc: string;
  imageName: string;
}

export function ImageLightbox({ isOpen, onClose, imageSrc, imageName }: ImageLightboxProps) {
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!isOpen || !imageSrc) {
      setLoadedSrc(null);
      setLoading(true);
      setError(false);
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
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
      }
    };
  }, [isOpen, imageSrc]);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl w-[95vw] h-[90vh] p-0 bg-background/95 backdrop-blur-sm border-border">
        <VisuallyHidden>
          <DialogTitle>{imageName}</DialogTitle>
        </VisuallyHidden>
        
        <Button
          variant="ghost"
          size="icon"
          className="absolute top-2 right-2 z-10 bg-background/80 hover:bg-background"
          onClick={onClose}
        >
          <X className="w-5 h-5" />
        </Button>
        
        <div className="w-full h-full flex flex-col items-center justify-center p-4">
          {loading && (
            <div className="w-32 h-32 bg-muted animate-pulse rounded-lg" />
          )}
          {error && (
            <div className="text-muted-foreground">Failed to load image</div>
          )}
          {!loading && !error && loadedSrc && (
            <img
              src={loadedSrc}
              alt={imageName}
              className="max-w-full max-h-[calc(90vh-80px)] object-contain rounded-lg"
            />
          )}
          <p className="mt-4 text-sm text-muted-foreground font-medium truncate max-w-full">
            {imageName}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
