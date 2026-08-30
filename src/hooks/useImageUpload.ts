import { useState, useCallback } from 'react';
import { UploadedImage } from '@/types';
import { toast } from 'sonner';

/**
 * Browsers cannot hold an unbounded selection. Every image costs a File handle
 * plus an object URL for its preview, so a folder of 100k photos will exhaust
 * the tab long before the backend sees any of them. The cap is a hard stop with
 * a pointer at the folder-based CLI, which is the right tool at that size.
 */
export const MAX_BROWSER_IMAGES = 25000;

/** Beyond this we stop generating preview URLs; the grid shows a count instead. */
export const PREVIEW_LIMIT = 200;

const ACCEPTED_MIME_TYPES = new Set([
  'image/jpeg',
  'image/jpg',
  'image/png',
  'image/webp',
  'image/pjpeg',
  'image/x-png',
  'image/jfif',
]);

const ACCEPTED_EXTENSIONS = new Set([
  '.jpg',
  '.jpeg',
  '.png',
  '.webp',
  '.jfif',
]);

const SYSTEM_FILE_PATTERNS = [
  /^\./, // hidden files (.DS_Store, .gitignore, ._*)
  /^__MACOSX/i,
  /Thumbs\.db$/i,
  /desktop\.ini$/i,
];

function isSystemFile(fileName: string): boolean {
  const baseName = fileName.split(/[/\\]/).pop() || fileName;
  return SYSTEM_FILE_PATTERNS.some(p => p.test(baseName));
}

function isValidImageFile(file: File): boolean {
  if (isSystemFile(file.name)) return false;

  // 1. Check MIME type if populated by the browser
  if (file.type) {
    return ACCEPTED_MIME_TYPES.has(file.type.toLowerCase());
  }

  // 2. Check file extension (crucial for folder selection and Drag & Drop where file.type is often "")
  const lastDot = file.name.lastIndexOf('.');
  if (lastDot !== -1) {
    const ext = file.name.slice(lastDot).toLowerCase();
    if (ACCEPTED_EXTENSIONS.has(ext)) {
      return true;
    }
  }

  return false;
}

export function useImageUpload() {
  const [images, setImages] = useState<UploadedImage[]>([]);

  const addImages = useCallback((files: FileList | File[]) => {
    const fileArray = Array.from(files);
    // Ignore OS system/hidden files like .DS_Store, ._photo.jpg quietly
    const nonSystemFiles = fileArray.filter(file => !isSystemFile(file.name));
    const validFiles = nonSystemFiles.filter(isValidImageFile);
    const rejected = nonSystemFiles.length - validFiles.length;

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
        toast.warning(`Skipped ${rejected} non-image file(s).`);
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
