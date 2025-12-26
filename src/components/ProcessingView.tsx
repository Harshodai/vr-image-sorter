import { Loader2, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';

interface ProcessingViewProps {
  currentIndex: number;
  totalFiles: number;
  onCancel: () => void;
}

export function ProcessingView({ currentIndex, totalFiles, onCancel }: ProcessingViewProps) {
  const progress = (currentIndex / totalFiles) * 100;

  return (
    <div className="flex flex-col items-center justify-center py-20 animate-fade-in">
      <div className="relative mb-8">
        <div className="w-24 h-24 rounded-full border-4 border-primary/20 flex items-center justify-center">
          <Loader2 className="w-12 h-12 text-primary animate-spin" />
        </div>
        <div className="absolute inset-0 rounded-full border-4 border-transparent border-t-primary animate-spin-slow" 
             style={{ animationDuration: '1.5s' }} />
      </div>

      <h2 className="text-2xl font-bold text-foreground mb-2">
        Processing Images
      </h2>
      
      <p className="text-muted-foreground mb-6">
        Scanning barcodes and extracting VR codes...
      </p>

      <div className="w-full max-w-md mb-4">
        <Progress value={progress} className="h-2" />
      </div>

      <p className="text-sm text-muted-foreground mb-8">
        Processing image <span className="font-semibold text-foreground">{currentIndex}</span> of{' '}
        <span className="font-semibold text-foreground">{totalFiles}</span>
      </p>

      <Button
        variant="destructive"
        onClick={onCancel}
        className="gap-2"
      >
        <XCircle className="w-4 h-4" />
        Cancel Processing
      </Button>
    </div>
  );
}
