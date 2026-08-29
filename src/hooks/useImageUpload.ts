import { useState, useCallback } from 'react';
import { UploadedImage } from '@/types';
import { toast } from 'sonner';

/**
 * Browsers cannot hold an unbounded selection. Every image costs a File handle
 * plus an object URL for its preview, so a folder of 100k photos will exhaust
 * the tab long before the backend sees any of them. The cap is a hard stop with
 * a pointer at the folder-based CLI, which is the right tool at that size.
 */
export const MAX_BROWSER_IMAGES = 2000;

/** Beyond this we stop generating preview URLs; the grid shows a count instead. */
export const PREVIEW_LIMIT = 200;

const ACCEPTED = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];

export function useImageUpload() {
  const [images, setImages] = useState<UploadedImage[]>([]);

  const addImages = useCallback((files: FileList | File[]) => {
    const fileArray = Array.from(files);
    const validFiles = fileArray.filter(file => ACCEPTED.includes(file.type));
    const rejected = fileArray.length - validFiles.length;

    setImages(prev => {
      const room = MAX_BROWSER_IMAGES - prev.length;
      if (room <= 0) {
        toast.error(
          `Limit is ${MAX_BROWSER_IMAGES.toLocaleString()} images in the browser. ` +
          `For a larger batch use the folder mode — see the README.`
        );
        return prev;
      }

      const accepted = validFiles.slice(0, room);
      const dropped = validFiles.length - accepted.length;

      const newImages: UploadedImage[] = accepted.map((file, i) => ({
        id: `${Date.now()}-${i}-${Math.random().toString(36).slice(2, 11)}`,
        file,
        // Only the images that will actually be rendered get an object URL.
        // Creating 2000 of them costs memory for previews nobody will look at.
        preview: prev.length + i < PREVIEW_LIMIT ? URL.createObjectURL(file) : '',
        name: file.name,
      }));

      if (rejected > 0) {
        toast.warning(`Skipped ${rejected} file(s) that are not JPG, PNG or WebP.`);
      }
      if (dropped > 0) {
        toast.error(
          `Added ${accepted.length}, dropped ${dropped.toLocaleString()} over the ` +
          `${MAX_BROWSER_IMAGES.toLocaleString()} limit. Use folder mode for a batch this size.`
        );
      }

      return [...prev, ...newImages];
    });
  }, []);

  const removeImage = useCallback((id: string) => {
    setImages(prev => {
      const image = prev.find(img => img.id === id);
      if (image?.preview) URL.revokeObjectURL(image.preview);
      return prev.filter(img => img.id !== id);
    });
  }, []);

  const clearImages = useCallback(() => {
    setImages(prev => {
      prev.forEach(img => img.preview && URL.revokeObjectURL(img.preview));
      return [];
    });
  }, []);

  return {
    images,
    addImages,
    removeImage,
    clearImages,
    hasImages: images.length > 0,
  };
}
