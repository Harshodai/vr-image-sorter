export interface UploadedImage {
  id: string;
  file: File;
  preview: string;
  name: string;
}

export interface ProcessingStats {
  totalFiles: number;
  processedFiles: number;
  failedFiles: number;
  successRate: number;
}

export interface ProcessedFile {
  originalName: string;
  newName: string;
  success: boolean;
  preview?: string;
  downloadUrl?: string;
}

export interface FailedFile {
  originalName: string;
  preview?: string;
  downloadUrl?: string;
}

export interface ProcessingResult {
  stats: ProcessingStats;
  processedFiles: ProcessedFile[];
  failedFiles: FailedFile[];
  downloadUrl?: string;
  failedDownloadUrl?: string;
  hasProcessed?: boolean;
  hasFailed?: boolean;
  sessionId?: string;
}

export type AppState = 'upload' | 'processing' | 'results';
