import { X } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { VisuallyHidden } from '@radix-ui/react-visually-hidden';

interface ImageLightboxProps {
  isOpen: boolean;
  onClose: () => void;
  imageSrc: string;
  imageName: string;
}

export function ImageLightbox({ isOpen, onClose, imageSrc, imageName }: ImageLightboxProps) {
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
          <img
            src={imageSrc}
            alt={imageName}
            className="max-w-full max-h-[calc(90vh-80px)] object-contain rounded-lg"
          />
          <p className="mt-4 text-sm text-muted-foreground font-medium truncate max-w-full">
            {imageName}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
