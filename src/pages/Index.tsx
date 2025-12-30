import { Scan, Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { HeroSection } from '@/components/HeroSection';
import { UploadZone } from '@/components/UploadZone';
import { ImagePreviewGrid } from '@/components/ImagePreviewGrid';
import { ProcessingView } from '@/components/ProcessingView';
import { ResultsView } from '@/components/ResultsView';
import { RequirementsSection } from '@/components/RequirementsSection';
import { Footer } from '@/components/Footer';
import { ThemeToggle } from '@/components/ThemeToggle';
import { useImageUpload } from '@/hooks/useImageUpload';
import { useProcessing } from '@/hooks/useProcessing';

const Index = () => {
  const { images, addImages, removeImage, clearImages, hasImages } = useImageUpload();
  const { state, currentIndex, result, error, processImages, cancelProcessing, reset } = useProcessing();

  const handleStartProcessing = () => {
    if (hasImages) {
      processImages(images);
    }
  };

  const handleReset = () => {
    reset();
    clearImages();
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border sticky top-0 bg-background/95 backdrop-blur-sm z-50">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
                <Scan className="w-5 h-5 text-primary-foreground" />
              </div>
              <div>
                <h1 className="font-bold text-foreground">Saree Organizer</h1>
                <p className="text-xs text-muted-foreground">Barcode & OCR Scanner</p>
              </div>
            </div>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        {state === 'upload' && (
          <>
            <HeroSection />
            
            {/* Upload Section */}
            <section className="max-w-3xl mx-auto">
              <UploadZone onFilesSelected={addImages} />
              
              <ImagePreviewGrid images={images} onRemove={removeImage} />
              
              {hasImages && (
                <div className="mt-8 flex flex-col sm:flex-row gap-4 justify-center animate-fade-in">
                  <Button
                    size="lg"
                    onClick={handleStartProcessing}
                    className="gap-2 text-lg px-8"
                  >
                    <Play className="w-5 h-5" />
                    Start Processing
                  </Button>
                  <Button
                    size="lg"
                    variant="outline"
                    onClick={clearImages}
                  >
                    Clear All
                  </Button>
                </div>
              )}
            </section>

            <RequirementsSection />
          </>
        )}

        {state === 'processing' && (
          <ProcessingView
            currentIndex={currentIndex}
            totalFiles={images.length}
            onCancel={cancelProcessing}
          />
        )}

        {state === 'results' && result && (
          <ResultsView result={result} onReset={handleReset} />
        )}
      </main>

      <Footer />
    </div>
  );
};

export default Index;
