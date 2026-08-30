import { useCallback, useState, useRef, useEffect } from 'react';
import { Upload, Image as ImageIcon, Folder } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { MAX_BROWSER_IMAGES } from '@/hooks/useImageUpload';

interface UploadZoneProps {
  onFilesSelected: (files: FileList | File[]) => void;
  disabled?: boolean;
}

/**
 * Recursively extracts all files from dropped DataTransferItems, traversing any folders.
 * Handles Chromium's 100-entry limit per readEntries() call by reading in a loop until empty.
 */
async function extractFilesFromDataTransfer(
  items: DataTransferItemList,
  fallbackFiles: FileList
): Promise<File[]> {
  const entries: FileSystemEntry[] = [];

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (typeof item.webkitGetAsEntry === 'function') {
      const entry = item.webkitGetAsEntry();
      if (entry) {
        entries.push(entry);
      }
    }
  }

  if (entries.length === 0) {
    return Array.from(fallbackFiles);
  }

  const allFiles: File[] = [];

  const readDir = (dirReader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> => {
    return new Promise((resolve) => {
      const dirEntries: FileSystemEntry[] = [];
      const readBatch = () => {
        dirReader.readEntries(
          (batch) => {
            if (batch.length === 0) {
              resolve(dirEntries);
            } else {
              dirEntries.push(...batch);
              readBatch();
            }
          },
          (err) => {
            console.warn('Error reading directory batch:', err);
            resolve(dirEntries);
          }
        );
      };
      readBatch();
    });
  };

  const traverse = async (entry: FileSystemEntry) => {
    if (entry.isFile) {
      const fileEntry = entry as FileSystemFileEntry;
      await new Promise<void>((resolve) => {
        fileEntry.file(
          (file) => {
            allFiles.push(file);
            resolve();
          },
          (err) => {
            console.warn('Error reading file entry:', err);
            resolve();
          }
        );
      });
    } else if (entry.isDirectory) {
      const dirEntry = entry as FileSystemDirectoryEntry;
      const dirReader = dirEntry.createReader();
      const childEntries = await readDir(dirReader);
      for (const child of childEntries) {
        await traverse(child);
      }
    }
  };

  for (const entry of entries) {
    await traverse(entry);
  }

  return allFiles;
}

export function UploadZone({ onFilesSelected, disabled }: UploadZoneProps) {
  const [isDragActive, setIsDragActive] = useState(false);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Programmatically ensure directory attributes on the input element for all browsers
  useEffect(() => {
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute('webkitdirectory', '');
      folderInputRef.current.setAttribute('mozdirectory', '');
      folderInputRef.current.setAttribute('directory', '');
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setIsDragActive(true);
  }, [disabled]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
    
    if (disabled) return;

    const items = e.dataTransfer.items;
    if (items && items.length > 0) {
      try {
        const files = await extractFilesFromDataTransfer(items, e.dataTransfer.files);
        if (files.length > 0) {
          onFilesSelected(files);
          return;
        }
      } catch (err) {
        console.error('Error reading dropped items:', err);
      }
    }
    
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      onFilesSelected(files);
    }
  }, [disabled, onFilesSelected]);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      onFilesSelected(files);
    }
    e.target.value = '';
  }, [onFilesSelected]);

  return (
    <div
      className={`upload-zone cursor-pointer text-center ${isDragActive ? 'drag-active border-primary bg-accent/50' : ''} ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => !disabled && fileInputRef.current?.click()}
    >
      <input
        ref={fileInputRef}
        id="file-input"
        type="file"
        multiple
        accept="image/jpeg,image/jpg,image/png,image/webp"
        className="hidden"
        onChange={handleFileInput}
        disabled={disabled}
      />
      {/* webkitdirectory selects a whole folder. Non-standard but supported in
          every current browser, and it is how operators actually work. */}
      <input
        ref={folderInputRef}
        id="folder-input"
        type="file"
        // @ts-expect-error -- webkitdirectory and directory are non-standard attributes
        webkitdirectory=""
        mozdirectory=""
        directory=""
        multiple
        className="hidden"
        onChange={handleFileInput}
        disabled={disabled}
      />
      
      <div className="flex flex-col items-center gap-4">
        <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center">
          <Upload className="w-8 h-8 text-primary" />
        </div>
        
        <div>
          <p className="text-lg font-medium text-foreground mb-1">
            Drag & drop your saree images here
          </p>
          <p className="text-sm text-muted-foreground">
            or click to browse files
          </p>
        </div>
        
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          disabled={disabled}
          onClick={(e) => {
            e.stopPropagation();
            folderInputRef.current?.click();
          }}
        >
          <Folder className="w-4 h-4" />
          Select a whole folder
        </Button>

        <div className="flex flex-col items-center gap-1 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <ImageIcon className="w-4 h-4" />
            <span>Supports JPG, JPEG, PNG, WebP</span>
          </div>
          <span>
            Up to {MAX_BROWSER_IMAGES.toLocaleString()} images here — for a bigger backlog
            use folder mode from the terminal
          </span>
        </div>
      </div>
    </div>
  );
}
