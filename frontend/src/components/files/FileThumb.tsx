import React, { useEffect, useRef, useState } from 'react';
import { Play } from 'lucide-react';
import { api, FileEntry } from '../../services/api';
import { thumbKind } from './fileUtils';

// ---------------------------------------------------------------- video frames
// Nodes rarely have ffmpeg, so the browser seeks a muted <video> into the clip and paints one frame
// to a canvas. Few at a time: each one holds a connection, and the browser allows ~6 per host.

const MAX_CAPTURES = 2;
const MAX_FRAMES = 400;
const FRAME_SHORT_SIDE = 400; // enough for the 3:4 box after the crop

const frames = new Map<string, string | null>(); // url -> JPEG data URL, or null when it failed
type Job = { url: string; listeners: Set<(frame: string | null) => void>; started: boolean };
const jobs = new Map<string, Job>();
const pending: Job[] = [];
let running = 0;

const captureFrame = (url: string) =>
  new Promise<string | null>((resolve) => {
    const video = document.createElement('video');
    let done = false;
    const finish = (frame: string | null) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      video.removeAttribute('src');
      video.load(); // drops the connection
      resolve(frame);
    };
    const timer = setTimeout(() => finish(null), 20000);
    const paint = () => {
      if (!video.videoWidth) return finish(null); // audio-only container
      const scale = Math.min(1, FRAME_SHORT_SIDE / Math.min(video.videoWidth, video.videoHeight));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      try {
        canvas.getContext('2d')!.drawImage(video, 0, 0, canvas.width, canvas.height);
        finish(canvas.toDataURL('image/jpeg', 0.75));
      } catch {
        finish(null);
      }
    };
    video.muted = true;
    video.playsInline = true;
    video.preload = 'metadata';
    video.onerror = () => finish(null);
    video.onloadedmetadata = () => {
      // The very first frame is often black: skip a little into the clip
      const d = video.duration;
      const at = Number.isFinite(d) && d > 0 ? Math.min(1.5, d * 0.25) : 0;
      if (at > 0) {
        video.onseeked = paint;
        video.currentTime = at;
      } else {
        video.onloadeddata = paint;
      }
    };
    video.src = url;
  });

const pump = () => {
  while (running < MAX_CAPTURES && pending.length) {
    const job = pending.shift()!;
    job.started = true;
    running++;
    captureFrame(job.url).then((frame) => {
      if (frames.size >= MAX_FRAMES) frames.delete(frames.keys().next().value!);
      frames.set(job.url, frame);
      jobs.delete(job.url);
      job.listeners.forEach((cb) => cb(frame));
      running--;
      pump();
    });
  }
};

/** Calls `cb` with the clip's frame once captured; the returned function cancels a queued capture. */
const subscribeFrame = (url: string, cb: (frame: string | null) => void) => {
  if (frames.has(url)) {
    cb(frames.get(url)!);
    return () => {};
  }
  let job = jobs.get(url);
  if (!job) {
    job = { url, listeners: new Set(), started: false };
    jobs.set(url, job);
    pending.push(job);
  }
  job.listeners.add(cb);
  pump();
  const queued = job;
  return () => {
    queued.listeners.delete(cb);
    if (!queued.started && !queued.listeners.size) {
      jobs.delete(url);
      pending.splice(pending.indexOf(queued), 1);
    }
  };
};

/** Data URL of a frame once the element has been on screen long enough to capture it. */
const useVideoFrame = (url: string | null, ref: React.RefObject<HTMLElement>) => {
  const [frame, setFrame] = useState<string | null | undefined>(() => (url ? frames.get(url) : undefined));
  useEffect(() => {
    const el = ref.current;
    if (!url || !el || frames.has(url)) return;
    let unsubscribe: (() => void) | null = null;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !unsubscribe) unsubscribe = subscribeFrame(url, setFrame);
        else if (!entry.isIntersecting && unsubscribe) {
          unsubscribe(); // scrolled past before its turn: let visible clips go first
          unsubscribe = null;
        }
      },
      { rootMargin: '200px' }
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      unsubscribe?.();
    };
  }, [url, ref]);
  return frame;
};

// ---------------------------------------------------------------- component

/**
 * An image/video's thumbnail in a fixed box, showing `icon` until it loads (and for every other file
 * type, or when the thumbnail can't be made).
 */
export const FileThumb: React.FC<{
  serverId: string;
  entry: FileEntry;
  icon: React.ReactNode;
  className?: string;
  fit?: 'cover' | 'contain';
  /** Mark videos with a play badge (skip it where the box is icon-sized) */
  badge?: boolean;
}> = ({ serverId, entry, icon, className = '', fit = 'cover', badge = false }) => {
  const kind = thumbKind(entry);
  const url = kind ? api.filesThumbUrl(serverId, entry.path, `3x4-${entry.mtime}-${entry.size}`) : null;
  // Cropping a logo/icon to fill the box would cut it off
  if (/\.svg$/i.test(entry.name)) fit = 'contain';
  return (
    <span className={`relative flex items-center justify-center flex-shrink-0 overflow-hidden ${className}`}>
      {url ? <ThumbImage key={url} url={url} video={kind === 'video'} icon={icon} fit={fit} badge={badge} /> : icon}
    </span>
  );
};

const ThumbImage: React.FC<{ url: string; video: boolean; icon: React.ReactNode; fit: 'cover' | 'contain'; badge: boolean }> = ({
  url,
  video,
  icon,
  fit,
  badge,
}) => {
  const ref = useRef<HTMLSpanElement>(null);
  const frame = useVideoFrame(video ? url : null, ref);
  const src = video ? frame : url;
  const [state, setState] = useState<'loading' | 'ok' | 'failed'>('loading');
  const shown = state === 'ok' && !!src;

  return (
    <span ref={ref} className="absolute inset-0 flex items-center justify-center">
      {!shown && icon}
      {src && state !== 'failed' && (
        <img
          src={src}
          alt=""
          draggable={false}
          loading="lazy"
          decoding="async"
          onLoad={() => setState('ok')}
          onError={() => setState('failed')}
          className={`absolute inset-0 w-full h-full transition-opacity ${
            fit === 'cover' ? 'object-cover' : 'object-contain'
          } ${shown ? 'opacity-100' : 'opacity-0'}`}
        />
      )}
      {shown && video && badge && (
        <span className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="flex items-center justify-center w-7 h-7 rounded-full bg-black/55 text-white">
            <Play size={14} fill="currentColor" strokeWidth={0} className="ml-0.5" />
          </span>
        </span>
      )}
    </span>
  );
};
