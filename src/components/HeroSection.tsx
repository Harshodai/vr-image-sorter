import { Scan, Sparkles } from 'lucide-react';

export function HeroSection() {
  return (
    <section className="text-center py-12 animate-fade-in">
      <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-accent text-accent-foreground text-sm font-medium mb-6">
        <Sparkles className="w-4 h-4" />
        Barcode & OCR Scanning
      </div>
      
      <h1 className="text-4xl md:text-5xl font-bold text-foreground mb-4 tracking-tight">
        Saree Image Organizer
      </h1>
      
      <p className="text-lg text-muted-foreground max-w-2xl mx-auto mb-8">
        Automatically rename your saree images using barcode and OCR technology. 
        Upload images, let our scanner detect VR codes, and download organized files.
      </p>

      <div className="flex flex-wrap justify-center gap-8 text-sm text-muted-foreground">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
            <span className="text-primary font-semibold">1</span>
          </div>
          <span>Upload Images</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
            <span className="text-primary font-semibold">2</span>
          </div>
          <span>Process & Scan</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
            <span className="text-primary font-semibold">3</span>
          </div>
          <span>Download Results</span>
        </div>
      </div>
    </section>
  );
}
