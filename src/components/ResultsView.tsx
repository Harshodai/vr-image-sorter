import { Upload, CheckCircle, XCircle, BarChart3, Download, RotateCcw, Maximize2 } from 'lucide-react';
import { ProcessingResult, ProcessedFile } from '@/types';
import { Button } from '@/components/ui/button';
import { StatsCard } from './StatsCard';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { useState, useEffect } from 'react';
import { ChevronDown } from 'lucide-react';
import { ImageLightbox } from './ImageLightbox';
import { getAuthenticatedDownload, getAuthenticatedImageUrl } from '@/hooks/useProcessing';
import { toast } from 'sonner';

interface ResultsViewProps {
  result: ProcessingResult;
  onReset: () => void;
}

// Component for authenticated image loading
function AuthenticatedImage({ src, alt, className, onClick }: { 
  src: string; 
  alt: string; 
  className?: string;
  onClick?: () => void;
}) {
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let mounted = true;
    let blobUrl: string | null = null;

    async function loadImage() {
      try {
        setLoading(true);
        setError(false);
        blobUrl = await getAuthenticatedImageUrl(src);
        if (mounted) {
          setImageSrc(blobUrl);
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
  }, [src]);

  if (loading) {
    return <div className={`${className} bg-muted animate-pulse`} />;
  }

  if (error || !imageSrc) {
    return <div className={`${className} bg-muted flex items-center justify-center text-muted-foreground text-xs`}>Failed to load</div>;
  }

  return <img src={imageSrc} alt={alt} className={className} onClick={onClick} />;
}

export function ResultsView({ result, onReset }: ResultsViewProps) {
  const [showFailed, setShowFailed] = useState(false);
  const [lightboxImage, setLightboxImage] = useState<ProcessedFile | null>(null);
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    if (result.downloadUrl) {
      setDownloading(true);
      try {
        await getAuthenticatedDownload(result.downloadUrl);
        toast.success('Download started');
      } catch (error) {
        toast.error('Download failed. Please try again.');
      } finally {
        setDownloading(false);
      }
    } else {
      alert('In demo mode: Connect to backend for actual ZIP download.\n\nWhen backend is running, this will download a ZIP file with all processed images.');
    }
  };

  const handleDownloadFailed = async () => {
    if (result.failedDownloadUrl) {
      setDownloading(true);
      try {
        await getAuthenticatedDownload(result.failedDownloadUrl);
        toast.success('Download started');
      } catch (error) {
        toast.error('Download failed. Please try again.');
      } finally {
        setDownloading(false);
      }
    } else {
      alert('In demo mode: Connect to backend for actual ZIP download.\n\nWhen backend is running, this will download a ZIP file with all failed images.');
    }
  };

  return (
    <div className="py-8 animate-fade-in">
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-success/10 mb-4">
          <CheckCircle className="w-8 h-8 text-success" />
        </div>
        <h2 className="text-2xl font-bold text-foreground mb-2">
          Processing Complete!
        </h2>
        <p className="text-muted-foreground">
          Your images have been scanned and organized.
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatsCard
          icon={Upload}
          label="Files Uploaded"
          value={result.stats.totalFiles}
          variant="default"
        />
        <StatsCard
          icon={CheckCircle}
          label="Successfully Processed"
          value={result.stats.processedFiles}
          variant="success"
        />
        <StatsCard
          icon={XCircle}
          label="Failed After Retry"
          value={result.stats.failedFiles}
          variant="destructive"
        />
        <StatsCard
          icon={BarChart3}
          label="Success Rate"
          value={`${result.stats.successRate}%`}
          variant={result.stats.successRate >= 80 ? 'success' : 'warning'}
        />
      </div>

      {/* Processed Files Preview */}
      {result.processedFiles.length > 0 && (
        <div className="mb-6">
          <h3 className="text-lg font-semibold text-foreground mb-4">
            Processed Images
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {result.processedFiles.slice(0, 12).map((file, index) => (
              <div
                key={index}
                className="relative aspect-square rounded-lg overflow-hidden bg-muted border border-border group cursor-pointer"
                onClick={() => file.preview && setLightboxImage(file)}
              >
                {file.preview && (
                  <AuthenticatedImage
                    src={file.preview}
                    alt={file.newName}
                    className="w-full h-full object-cover"
                  />
                )}
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors" />
                <div className="absolute top-2 left-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Maximize2 className="w-4 h-4 text-white drop-shadow-lg" />
                </div>
                <div className="absolute bottom-0 left-0 right-0 p-2 bg-gradient-to-t from-black/80 to-transparent">
                  <p className="text-xs text-white font-medium truncate">
                    {file.newName}
                  </p>
                </div>
              </div>
            ))}
          </div>
          {result.processedFiles.length > 12 && (
            <p className="text-sm text-muted-foreground mt-2">
              +{result.processedFiles.length - 12} more files
            </p>
          )}
        </div>
      )}

      {/* Failed Files Section */}
      {result.failedFiles.length > 0 && (
        <Collapsible open={showFailed} onOpenChange={setShowFailed} className="mb-8">
          <CollapsibleTrigger asChild>
            <Button variant="ghost" className="w-full justify-between text-destructive hover:text-destructive">
              <span>Failed Images ({result.failedFiles.length})</span>
              <ChevronDown className={`w-4 h-4 transition-transform ${showFailed ? 'rotate-180' : ''}`} />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2">
            <div className="bg-destructive/5 rounded-lg p-4 border border-destructive/20">
              <ul className="space-y-1 mb-4">
                {result.failedFiles.map((file, index) => (
                  <li key={index} className="text-sm text-muted-foreground flex items-center gap-2">
                    <XCircle className="w-4 h-4 text-destructive flex-shrink-0" />
                    {file.originalName}
                  </li>
                ))}
              </ul>
              <Button
                variant="destructive"
                size="sm"
                onClick={handleDownloadFailed}
                disabled={downloading}
                className="gap-2"
              >
                <Download className="w-4 h-4" />
                {downloading ? 'Downloading...' : 'Download Failed Images'}
              </Button>
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Action Buttons */}
      <div className="flex flex-col sm:flex-row gap-4 justify-center">
        <Button
          size="lg"
          onClick={handleDownload}
          disabled={downloading}
          className="gap-2"
        >
          <Download className="w-5 h-5" />
          {downloading ? 'Downloading...' : 'Download All as ZIP'}
        </Button>
        <Button
          size="lg"
          variant="outline"
          onClick={onReset}
          className="gap-2"
        >
          <RotateCcw className="w-5 h-5" />
          Process More Images
        </Button>
      </div>

      {lightboxImage && lightboxImage.preview && (
        <ImageLightbox
          isOpen={!!lightboxImage}
          onClose={() => setLightboxImage(null)}
          imageSrc={lightboxImage.preview}
          imageName={lightboxImage.newName}
        />
      )}
    </div>
  );
}
