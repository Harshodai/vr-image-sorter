import { useState, useCallback, useRef } from 'react';
import { UploadedImage, ProcessingResult, ProcessedFile, FailedFile, AppState } from '@/types';
import { toast } from 'sonner';

// Configure your backend URL here
// Added your specific Railway backend as a hardcoded fallback
const API_URL_RAW = import.meta.env.VITE_API_URL || 'https://vr-image-sorter-production.up.railway.app';
// Ensure the URL does not end with a trailing slash to avoid double slashes in paths
const API_BASE_URL = API_URL_RAW.endsWith('/') ? API_URL_RAW.slice(0, -1) : API_URL_RAW;

// Store session token securely in memory (not localStorage for security)
let sessionToken: string | null = null;

// Export getter for session token (for authenticated requests)
export function getSessionToken(): string | null {
  return sessionToken;
}


// Helper for authenticated fetch
export async function authenticatedFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  if (sessionToken) {
    headers.set('Authorization', `Bearer ${sessionToken}`);
  }
  return fetch(url, { ...options, headers });
}

// Helper to get authenticated blob URL for downloads with custom filename
export async function getAuthenticatedDownload(url: string, filename?: string): Promise<void> {
  try {
    const response = await authenticatedFetch(url);
    if (!response.ok) {
      throw new Error('Download failed');
    }
    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);

    // Create a temporary link and click it
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename || 'download.zip';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // Cleanup blob URL
    URL.revokeObjectURL(blobUrl);
  } catch (error) {
    throw error;
  }
}

// Helper for single file download (processed or failed)
export async function getAuthenticatedSingleDownload(
  sessionId: string,
  filename: string,
  type: 'processed' | 'failed'
): Promise<void> {
  const endpoint = type === 'processed'
    ? `/api/download-single/${sessionId}/${filename}`
    : `/api/download-single-failed/${sessionId}/${filename}`;

  await getAuthenticatedDownload(`${API_BASE_URL}${endpoint}`, filename);
}

// Helper to get authenticated image blob URL for previews
export async function getAuthenticatedImageUrl(url: string): Promise<string> {
  const response = await authenticatedFetch(url);
  if (!response.ok) {
    throw new Error('Failed to load image');
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

export function useProcessing() {
  const [state, setState] = useState<AppState>('upload');
  const [currentIndex, setCurrentIndex] = useState(0);
  const [result, setResult] = useState<ProcessingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const processImages = useCallback(async (images: UploadedImage[]) => {
    setState('processing');
    setCurrentIndex(0);
    setError(null);

    abortControllerRef.current = new AbortController();

    try {
      const formData = new FormData();
      images.forEach((img, index) => {
        formData.append('files', img.file);
        // Simulate progress
        setCurrentIndex(index + 1);
      });

      const response = await fetch(`${API_BASE_URL}/api/process`, {
        method: 'POST',
        body: formData,
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error('Processing failed. Please check if the backend is running.');
      }

      const data = await response.json();

      // Store the session token for authenticated requests
      sessionToken = data.session_token || null;

      // Create authenticated preview URLs (token will be added when fetching)
      const processedFiles: ProcessedFile[] = data.processed.map((item: any) => ({
        originalName: item.original_name,
        newName: item.new_name,
        success: true,
        preview: item.preview_url ? `${API_BASE_URL}${item.preview_url}` : undefined,
      }));

      const failedFiles: FailedFile[] = data.failed.map((item: any) => ({
        originalName: item.original_name,
        preview: item.preview_url ? `${API_BASE_URL}${item.preview_url}` : undefined,
      }));

      setResult({
        stats: {
          totalFiles: images.length,
          processedFiles: processedFiles.length,
          failedFiles: failedFiles.length,
          successRate: Math.round((processedFiles.length / images.length) * 100),
        },
        processedFiles,
        failedFiles,
        downloadUrl: data.download_url ? `${API_BASE_URL}${data.download_url}` : undefined,
        failedDownloadUrl: data.failed_download_url ? `${API_BASE_URL}${data.failed_download_url}` : undefined,
        hasProcessed: data.has_processed || false,
        hasFailed: data.has_failed || false,
        sessionId: data.session_id, // Add session ID to result for retry/single download
      });

      setState('results');
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setState('upload');
        return;
      }

      const errorMessage = err instanceof Error ? err.message : 'An error occurred';
      setError(errorMessage);
      toast.error(`Connection Error: ${errorMessage}. Please check if VITE_API_URL is set correctly.`);

      // Don't move to results state if there was a connection error
      setState('upload');
    }
  }, []);

  
  const retryImages = useCallback(async (filenames: string[], sessionId: string) => {
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/api/retry/${sessionId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ filenames }),
      });

      if (!response.ok) {
        throw new Error('Retry failed');
      }

      const data = await response.json();

      if (data.success && result) {
        // Merge new results
        const newProcessed: ProcessedFile[] = data.retried_processed.map((item: any) => ({
          originalName: item.original_name,
          newName: item.new_name,
          success: true,
          preview: item.preview_url ? `${API_BASE_URL}${item.preview_url}` : undefined,
        }));

        // Filter out retried files from failed list
        const remainingFailed = result.failedFiles.filter(
          f => !newProcessed.some(p => p.originalName === f.originalName)
        );

        const allProcessed = [...result.processedFiles, ...newProcessed];

        setResult({
          ...result,
          stats: {
            ...result.stats,
            processedFiles: allProcessed.length,
            failedFiles: remainingFailed.length,
            successRate: Math.round((allProcessed.length / result.stats.totalFiles) * 100)
          },
          processedFiles: allProcessed,
          failedFiles: remainingFailed,
          downloadUrl: data.download_url ? `${API_BASE_URL}${data.download_url}` : result.downloadUrl,
          failedDownloadUrl: data.failed_download_url ? `${API_BASE_URL}${data.failed_download_url}` : undefined,
          hasProcessed: allProcessed.length > 0,
          hasFailed: remainingFailed.length > 0
        });
      }

      return true;
    } catch (err) {
      console.error(err);
      return false;
    }
  }, [result]);

  const simulateProcessing = useCallback(async (images: UploadedImage[]) => {
    const processedFiles: ProcessedFile[] = [];
    const failedFiles: FailedFile[] = [];

    for (let i = 0; i < images.length; i++) {
      setCurrentIndex(i + 1);
      await new Promise(resolve => setTimeout(resolve, 500));

      // Simulate 85% success rate
      if (Math.random() > 0.15) {
        processedFiles.push({
          originalName: images[i].name,
          newName: `VR${Math.floor(10000 + Math.random() * 90000)}.jpg`,
          success: true,
          preview: images[i].preview,
        });
      } else {
        failedFiles.push({
          originalName: images[i].name,
        });
      }
    }

    setResult({
      stats: {
        totalFiles: images.length,
        processedFiles: processedFiles.length,
        failedFiles: failedFiles.length,
        successRate: Math.round((processedFiles.length / images.length) * 100),
      },
      processedFiles,
      failedFiles,
    });

    setState('results');
    setError(null);
  }, []);

  const cancelProcessing = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setState('upload');
  }, []);

  const reset = useCallback(() => {
    setState('upload');
    setCurrentIndex(0);
    setResult(null);
    setError(null);
    // Clear session token on reset
    sessionToken = null;
  }, []);

  return {
    state,
    currentIndex,
    result,
    error,
    processImages,
    retryImages,
    cancelProcessing,
    reset,
  };
}
