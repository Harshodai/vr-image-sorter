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
  reviewFiles: number;
  successRate: number;
}

export interface ProcessedFile {
  originalName: string;
  newName: string;
  success: boolean;
  preview?: string;
  downloadUrl?: string;
  confidence?: number;
  method?: string;
}

export interface CodeCandidate {
  code: string;
  confidence: number;
}

/**
 * An image the scanner could read but not trust. It keeps its ORIGINAL
 * filename until a human confirms the code — nothing is renamed on a guess.
 */
export interface ReviewFile {
  originalName: string;
  storedName: string;
  suggestedCode: string;
  suggestedName: string;
  confidence: number;
  method: string;
  reason: string;
  alternatives: CodeCandidate[];
  preview?: string;
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
  reviewFiles: ReviewFile[];
  downloadUrl?: string;
  failedDownloadUrl?: string;
  hasProcessed?: boolean;
  hasFailed?: boolean;
  hasReview?: boolean;
  sessionId?: string;
}

export type AppState = 'upload' | 'processing' | 'results';
