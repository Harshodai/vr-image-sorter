import { useCallback, useState } from 'react';
import { Upload, Image as ImageIcon, Folder } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { MAX_BROWSER_IMAGES } from '@/hooks/useImageUpload';

interface UploadZoneProps {
  onFilesSelected: (files: FileList | File[]) => void;
  disabled?: boolean;
}

export function UploadZone({ onFilesSelected, disabled }: UploadZoneProps) {
  const [isDragActive, setIsDragActive] = useState(false);

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

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
    
    if (disabled) return;
    
    const files = e.dataTransfer.files;
    if (files.length > 0) {
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
      onClick={() => !disabled && document.getElementById('file-input')?.click()}
    >
      <input
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
        id="folder-input"
        type="file"
        // @ts-expect-error -- webkitdirectory is not in React's typings
        webkitdirectory=""
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
            document.getElementById('folder-input')?.click();
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
