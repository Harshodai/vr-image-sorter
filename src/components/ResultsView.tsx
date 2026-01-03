import { Upload, CheckCircle, XCircle, BarChart3, Download, RotateCcw, Maximize2 } from 'lucide-react';
import { ProcessingResult, ProcessedFile, FailedFile } from '@/types';
import { Button } from '@/components/ui/button';
import { StatsCard } from './StatsCard';
import { useState, useEffect } from 'react';
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
  const [lightboxImage, setLightboxImage] = useState<{ src: string; name: string } | null>(null);
  const [downloadingSuccess, setDownloadingSuccess] = useState(false);
  const [downloadingFailed, setDownloadingFailed] = useState(false);
  const [downloadingAll, setDownloadingAll] = useState(false);

  const hasProcessed = result.processedFiles.length > 0;
  const hasFailed = result.failedFiles.length > 0;
  const hasBoth = hasProcessed && hasFailed;

  const handleDownloadSuccess = async () => {
    if (result.downloadUrl) {
      setDownloadingSuccess(true);
      try {
        await getAuthenticatedDownload(result.downloadUrl, 'saree_organized.zip');
        toast.success('Successfully processed images downloaded');
      } catch (error) {
        toast.error('Download failed. Please try again.');
      } finally {
        setDownloadingSuccess(false);
      }
    } else {
      toast.info('Demo mode: Connect to backend for actual ZIP download.');
    }
  };

  const handleDownloadFailed = async () => {
    if (result.failedDownloadUrl) {
      setDownloadingFailed(true);
      try {
        await getAuthenticatedDownload(result.failedDownloadUrl, 'failed_images.zip');
        toast.success('Failed images downloaded');
      } catch (error) {
        toast.error('Download failed. Please try again.');
      } finally {
        setDownloadingFailed(false);
      }
    } else {
      toast.info('Demo mode: Connect to backend for actual ZIP download.');
    }
  };

  const handleDownloadAll = async () => {
    setDownloadingAll(true);
    try {
      // Download success ZIP first
      if (result.downloadUrl) {
        await getAuthenticatedDownload(result.downloadUrl, 'saree_organized.zip');
      }
      // Small delay between downloads
      await new Promise(resolve => setTimeout(resolve, 500));
      // Download failed ZIP
      if (result.failedDownloadUrl) {
        await getAuthenticatedDownload(result.failedDownloadUrl, 'failed_images.zip');
      }
      toast.success('Both downloads started');
    } catch (error) {
      toast.error('Download failed. Please try again.');
    } finally {
      setDownloadingAll(false);
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

      {/* Download All Button - only show when both sections exist */}
      {hasBoth && (
        <div className="mb-8 flex justify-center">
          <Button
            size="lg"
            onClick={handleDownloadAll}
            disabled={downloadingAll || downloadingSuccess || downloadingFailed}
            className="gap-2 bg-gradient-to-r from-primary to-primary/80"
          >
            <Download className="w-5 h-5" />
            {downloadingAll ? 'Downloading Both...' : 'Download All (2 ZIP files)'}
          </Button>
        </div>
      )}

      {/* Two Section Layout */}
      <div className={`grid gap-6 mb-8 ${hasBoth ? 'md:grid-cols-2' : 'grid-cols-1'}`}>
        {/* Successfully Processed Section */}
        {hasProcessed && (
          <div className="border border-success/20 rounded-lg p-4 bg-success/5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-full bg-success/20 flex items-center justify-center">
                  <CheckCircle className="w-4 h-4 text-success" />
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Successfully Processed</h3>
                  <p className="text-sm text-muted-foreground">{result.processedFiles.length} images</p>
                </div>
              </div>
            </div>
            
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 mb-4">
              {result.processedFiles.slice(0, 8).map((file, index) => (
                <div
                  key={index}
                  className="relative aspect-square rounded-lg overflow-hidden bg-muted border border-border group cursor-pointer"
                  onClick={() => file.preview && setLightboxImage({ src: file.preview, name: file.newName })}
                >
                  {file.preview && (
                    <AuthenticatedImage
                      src={file.preview}
                      alt={file.newName}
                      className="w-full h-full object-cover"
                    />
                  )}
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors" />
                  <div className="absolute top-1 left-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Maximize2 className="w-3 h-3 text-white drop-shadow-lg" />
                  </div>
                  <div className="absolute bottom-0 left-0 right-0 p-1 bg-gradient-to-t from-black/80 to-transparent">
                    <p className="text-[10px] text-white font-medium truncate">
                      {file.newName}
                    </p>
                  </div>
                </div>
              ))}
            </div>
            {result.processedFiles.length > 8 && (
              <p className="text-xs text-muted-foreground mb-4">
                +{result.processedFiles.length - 8} more files
              </p>
            )}
            
            <Button
              onClick={handleDownloadSuccess}
              disabled={downloadingSuccess || downloadingAll}
              className="w-full gap-2 bg-success hover:bg-success/90 text-success-foreground"
            >
              <Download className="w-4 h-4" />
              {downloadingSuccess ? 'Downloading...' : 'Download Processed (ZIP)'}
            </Button>
          </div>
        )}

        {/* Failed Section */}
        {hasFailed && (
          <div className="border border-destructive/20 rounded-lg p-4 bg-destructive/5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-full bg-destructive/20 flex items-center justify-center">
                  <XCircle className="w-4 h-4 text-destructive" />
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Failed After Retry</h3>
                  <p className="text-sm text-muted-foreground">{result.failedFiles.length} images</p>
                </div>
              </div>
            </div>
            
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 mb-4">
              {result.failedFiles.slice(0, 8).map((file, index) => (
                <div
                  key={index}
                  className="relative aspect-square rounded-lg overflow-hidden bg-muted border border-destructive/30 group cursor-pointer"
                  onClick={() => file.preview && setLightboxImage({ src: file.preview, name: file.originalName })}
                >
                  {file.preview ? (
                    <AuthenticatedImage
                      src={file.preview}
                      alt={file.originalName}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center bg-destructive/10">
                      <XCircle className="w-6 h-6 text-destructive/50" />
                    </div>
                  )}
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors" />
                  <div className="absolute top-1 left-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Maximize2 className="w-3 h-3 text-white drop-shadow-lg" />
                  </div>
                  <div className="absolute bottom-0 left-0 right-0 p-1 bg-gradient-to-t from-black/80 to-transparent">
                    <p className="text-[10px] text-white font-medium truncate">
                      {file.originalName}
                    </p>
                  </div>
                </div>
              ))}
            </div>
            {result.failedFiles.length > 8 && (
              <p className="text-xs text-muted-foreground mb-4">
                +{result.failedFiles.length - 8} more files
              </p>
            )}
            
            <Button
              variant="destructive"
              onClick={handleDownloadFailed}
              disabled={downloadingFailed || downloadingAll}
              className="w-full gap-2"
            >
              <Download className="w-4 h-4" />
              {downloadingFailed ? 'Downloading...' : 'Download Failed (ZIP)'}
            </Button>
          </div>
        )}
      </div>

      {/* Process More Button */}
      <div className="flex justify-center">
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

      {lightboxImage && (
        <ImageLightbox
          isOpen={!!lightboxImage}
          onClose={() => setLightboxImage(null)}
          imageSrc={lightboxImage.src}
          imageName={lightboxImage.name}
        />
      )}
    </div>
  );
}