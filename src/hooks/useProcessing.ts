import { useState, useCallback, useRef } from 'react';
import { UploadedImage, ProcessingResult, ProcessedFile, AppState } from '@/types';

// Configure your backend URL here
const API_BASE_URL = import.meta.env.VITE_API_URL || 'https://vr-image-sorter-production.up.railway.app';

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

// Helper to get authenticated blob URL for downloads
export async function getAuthenticatedDownload(url: string): Promise<void> {
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
    link.download = 'saree_organized.zip';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    // Cleanup blob URL
    URL.revokeObjectURL(blobUrl);
  } catch (error) {
    throw error;
  }
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

      const failedFiles: ProcessedFile[] = data.failed.map((item: any) => ({
        originalName: item.original_name,
        newName: '',
        success: false,
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
        downloadUrl: data.download_url ? `${API_BASE_URL}${data.download_url}` : '',
        failedDownloadUrl: data.failed_download_url ? `${API_BASE_URL}${data.failed_download_url}` : undefined,
      });

      setState('results');
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setState('upload');
        return;
      }
      setError(err instanceof Error ? err.message : 'An error occurred');
      const failedFiles: ProcessedFile[] = images.map(img => ({
        originalName: img.name,
        newName: '',
        success: false
      }));

      setResult({
        stats: {
          totalFiles: images.length,
          processedFiles: 0,
          failedFiles: images.length,
          successRate: 0,
        },
        processedFiles: [],
        failedFiles,
      });

      setState('results');
    }
  }, []);

  const simulateProcessing = useCallback(async (images: UploadedImage[]) => {
    // Simulated processing for demo when backend is not connected
    const processedFiles: ProcessedFile[] = [];
    const failedFiles: ProcessedFile[] = [];

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
          newName: '',
          success: false,
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
    cancelProcessing,
    reset,
  };
}
