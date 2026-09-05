import { useState, useEffect, useRef } from 'react';
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
 *
 * The fetch is gated behind IntersectionObserver rather than firing on mount.
 * A review queue (unlike the processed/failed lists, which cap at 8 previews)
 * renders every item, since a human has to go through all of them — with no
 * gate, a re-upload landing dozens or hundreds of images in review fired that
 * many concurrent authenticated fetches at once. The browser then queues most
 * of them behind its per-host connection limit, and every thumbnail sits on
 * its loading skeleton until its turn comes — the app doing real, bounded
 * work, but presenting as "stuck loading" for however long the queue takes to
 * drain. Loading only what has actually scrolled near the viewport keeps the
 * number of simultaneous requests bounded by screen space, not list size.
 */
export function AuthenticatedImage({ src, alt, className, onClick }: AuthenticatedImageProps) {
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [inView, setInView] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === 'undefined') {
      // Defensive fallback for an environment without it: load eagerly
      // rather than never loading at all.
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some(e => e.isIntersecting)) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin: '200px' } // start just before it's actually visible
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!inView) return;
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
  }, [inView, src]);

  // `contents` makes this wrapper invisible to layout — callers size the
  // placeholder/img child directly (e.g. "w-full h-full object-cover" inside
  // a sized parent) — while still giving IntersectionObserver a stable node
  // to watch across the loading -> loaded/error transition.
  return (
    <div ref={containerRef} className="contents">
      {!inView || loading ? (
        <div className={`${className} bg-muted animate-pulse`} />
      ) : error || !imageSrc ? (
        <div className={`${className} bg-muted flex items-center justify-center text-muted-foreground text-xs`}>
          Failed to load
        </div>
      ) : (
        <img src={imageSrc} alt={alt} className={className} onClick={onClick} />
      )}
    </div>
  );
}
