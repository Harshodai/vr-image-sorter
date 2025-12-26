import { Scan } from 'lucide-react';

export function Footer() {
  return (
    <footer className="py-8 border-t border-border mt-12">
      <div className="flex flex-col items-center gap-4 text-center">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
            <Scan className="w-4 h-4 text-primary" />
          </div>
          <span className="font-semibold text-foreground">Saree Organizer</span>
        </div>
        
        <p className="text-sm text-muted-foreground max-w-md">
          Streamline your saree inventory management with automatic barcode and OCR scanning technology.
        </p>
        
        <p className="text-xs text-muted-foreground">
          © {new Date().getFullYear()} Saree Organizer. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
