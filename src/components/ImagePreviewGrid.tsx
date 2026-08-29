import { X, Maximize2 } from 'lucide-react';
import { useState } from 'react';
import { UploadedImage } from '@/types';
import { PREVIEW_LIMIT } from '@/hooks/useImageUpload';
import { Button } from '@/components/ui/button';
import { ImageLightbox } from './ImageLightbox';

interface ImagePreviewGridProps {
  images: UploadedImage[];
  onRemove: (id: string) => void;
}

export function ImagePreviewGrid({ images, onRemove }: ImagePreviewGridProps) {
  const [lightboxImage, setLightboxImage] = useState<UploadedImage | null>(null);

  if (images.length === 0) return null;

  return (
    <>
      <div className="mt-6 animate-fade-in">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-foreground">
            Uploaded Images
          </h3>
          <span className="text-sm text-muted-foreground bg-secondary px-3 py-1 rounded-full">
            {images.length} {images.length === 1 ? 'image' : 'images'} ready
          </span>
        </div>
        
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {images.slice(0, PREVIEW_LIMIT).map((image) => (
            <div
              key={image.id}
              className="relative group aspect-square rounded-lg overflow-hidden bg-muted border border-border animate-scale-in cursor-pointer"
              onClick={() => image.preview && setLightboxImage(image)}
            >
              {image.preview ? (
                <img
                  src={image.preview}
                  alt={image.name}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-xs text-muted-foreground">
                  no preview
                </div>
              )}
              
              <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors" />
              
              <div className="absolute top-2 left-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <Maximize2 className="w-5 h-5 text-white drop-shadow-lg" />
              </div>
              
              <Button
                variant="destructive"
                size="icon"
                className="absolute top-2 right-2 w-7 h-7 opacity-0 group-hover:opacity-100 transition-opacity"
                onClick={(e) => {
                  e.stopPropagation();
                  onRemove(image.id);
                }}
              >
                <X className="w-4 h-4" />
              </Button>
              
              <div className="absolute bottom-0 left-0 right-0 p-2 bg-gradient-to-t from-black/80 to-transparent">
                <p className="text-xs text-white truncate">
                  {image.name}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {images.length > PREVIEW_LIMIT && (
          <p className="mt-4 text-sm text-muted-foreground">
            Showing the first {PREVIEW_LIMIT} of {images.length.toLocaleString()}. All of them
            will be processed — previews are capped to keep the page responsive.
          </p>
        )}

      {lightboxImage && (
        <ImageLightbox
          isOpen={!!lightboxImage}
          onClose={() => setLightboxImage(null)}
          imageSrc={lightboxImage.preview}
          imageName={lightboxImage.name}
        />
      )}
    </>
  );
}
