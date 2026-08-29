import { useState, useEffect } from 'react';
import { getAuthenticatedImageUrl } from '@/hooks/useProcessing';

interface AuthenticatedImageProps {
  src: string;
  alt: string;
  className?: string;
  onClick?: () => void;
}

/**
 * Previews sit behind a session token, so they cannot be loaded by pointing an
 * <img> at the URL — the bytes are fetched with the auth header and handed to
 * the tag as a blob URL, which is revoked when the component goes away.
 */
export function AuthenticatedImage({ src, alt, className, onClick }: AuthenticatedImageProps) {
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
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [src]);

  if (loading) return <div className={`${className} bg-muted animate-pulse`} />;
  if (error || !imageSrc) {
    return (
      <div className={`${className} bg-muted flex items-center justify-center text-muted-foreground text-xs`}>
        Failed to load
      </div>
    );
  }
  return <img src={imageSrc} alt={alt} className={className} onClick={onClick} />;
}
