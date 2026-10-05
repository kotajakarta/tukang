import React, { useEffect, useState } from 'react';
import { Button, Modal, Spin, Tooltip } from 'antd';
import { ChevronLeft, ChevronRight, Download, ExternalLink, Maximize2, Minimize2, X } from 'lucide-react';
import { api, FileEntry } from '../../services/api';
import { fileIcon, formatSize, previewKind } from './fileUtils';

/**
 * Media viewer/player for images, video, audio and PDF. `items` are the previewable files of the
 * current directory so the user can step through them (← / →) without closing the modal.
 */
export const FileViewer: React.FC<{
  serverId: string;
  items: FileEntry[];
  index: number | null;
  onIndexChange: (index: number) => void;
  onDownload: (item: FileEntry) => void;
  onClose: () => void;
}> = ({ serverId, items, index, onIndexChange, onDownload, onClose }) => {
  const item = index !== null ? items[index] : undefined;
  const kind = item ? previewKind(item) : null;
  const src = item ? api.filesViewUrl(serverId, item.path) : '';
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [actualSize, setActualSize] = useState(false);

  useEffect(() => {
    // The browser's PDF viewer doesn't reliably fire iframe load events: only images get a spinner
    setLoading(kind === 'image');
    setFailed(false);
    setActualSize(false);
  }, [src, kind]);

  const hasPrev = index !== null && index > 0;
  const hasNext = index !== null && index < items.length - 1;

  useEffect(() => {
    if (index === null) return;
    const onKey = (e: KeyboardEvent) => {
      // Let focused players/inputs keep their own arrow-key seeking
      if ((e.target as HTMLElement)?.closest?.('video, audio, input, textarea')) return;
      if (e.key === 'ArrowLeft' && hasPrev) onIndexChange(index - 1);
      else if (e.key === 'ArrowRight' && hasNext) onIndexChange(index + 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [index, hasPrev, hasNext, onIndexChange]);

  const fallback = item && (
    <div className="flex flex-col items-center gap-3 text-center text-white/80 px-6">
      {React.createElement(fileIcon(item).Icon, { size: 56, color: fileIcon(item).color, strokeWidth: 1.25 })}
      <div>This file can’t be previewed in the browser.</div>
      <Button icon={<Download size={15} />} onClick={() => onDownload(item)}>
        Download ({formatSize(item.size)})
      </Button>
    </div>
  );

  let body: React.ReactNode = null;
  if (item && failed) body = fallback;
  else if (item && kind === 'image')
    body = (
      <div className={`w-full h-full ${actualSize ? 'overflow-auto' : 'flex items-center justify-center'}`}>
        <img
          key={src}
          src={src}
          alt={item.name}
          onLoad={() => setLoading(false)}
          onError={() => {
            setLoading(false);
            setFailed(true);
          }}
          onClick={() => setActualSize((v) => !v)}
          className={actualSize ? 'max-w-none cursor-zoom-out' : 'max-w-full max-h-full object-contain cursor-zoom-in'}
          style={{ imageRendering: actualSize ? 'pixelated' : undefined, background: 'repeating-conic-gradient(#ffffff10 0 25%, transparent 0 50%) 0 0 / 16px 16px' }}
        />
      </div>
    );
  else if (item && kind === 'video')
    body = (
      <video key={src} src={src} controls autoPlay playsInline className="max-w-full max-h-full bg-black outline-none" onError={() => setFailed(true)} />
    );
  else if (item && kind === 'audio')
    body = (
      <div className="flex flex-col items-center gap-5 w-full max-w-lg px-6">
        {React.createElement(fileIcon(item).Icon, { size: 72, color: fileIcon(item).color, strokeWidth: 1.1 })}
        <div className="text-white/90 font-medium break-all text-center">{item.name}</div>
        <audio key={src} src={src} controls autoPlay className="w-full" onError={() => setFailed(true)} />
      </div>
    );
  else if (item && kind === 'pdf') body = <iframe key={src} src={src} title={item.name} className="w-full h-full border-0 bg-white" />;

  const navButton = (dir: -1 | 1) => {
    const enabled = dir < 0 ? hasPrev : hasNext;
    // Over a PDF the arrows would cover its own toolbar/scrollbar; the header has prev/next too
    if (!enabled || kind === 'pdf') return null;
    return (
      <button
        type="button"
        aria-label={dir < 0 ? 'Previous file' : 'Next file'}
        onClick={() => onIndexChange(index! + dir)}
        className={`absolute top-1/2 -translate-y-1/2 ${dir < 0 ? 'left-3' : 'right-3'} z-10 flex items-center justify-center w-10 h-10 rounded-full bg-black/50 text-white border-0 cursor-pointer hover:bg-black/75 transition-colors`}
      >
        {dir < 0 ? <ChevronLeft size={22} /> : <ChevronRight size={22} />}
      </button>
    );
  };

  return (
    <Modal
      open={index !== null && !!item}
      onCancel={onClose}
      footer={null}
      closable={false}
      centered
      destroyOnClose
      width="min(1200px, 96vw)"
      styles={{ content: { padding: 0, overflow: 'hidden', background: '#0d1117' }, body: { padding: 0 } }}
    >
      {item && (
        <div className="flex flex-col" style={{ height: 'min(86vh, 900px)' }}>
          <div className="flex items-center gap-2 px-3 py-2 border-b border-white/10 text-white">
            {React.createElement(fileIcon(item).Icon, { size: 18, color: fileIcon(item).color, strokeWidth: 1.75, className: 'flex-shrink-0' })}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium" title={item.path}>
                {item.name}
              </div>
              <div className="text-xs text-white/50">
                {formatSize(item.size)}
                {items.length > 1 && ` · ${index! + 1} of ${items.length}`}
              </div>
            </div>
            {items.length > 1 && (
              <>
                <Tooltip title="Previous (←)">
                  <Button type="text" className="!text-white/80 hover:!text-white disabled:!text-white/25" disabled={!hasPrev} icon={<ChevronLeft size={18} />} onClick={() => onIndexChange(index! - 1)} aria-label="Previous file" />
                </Tooltip>
                <Tooltip title="Next (→)">
                  <Button type="text" className="!text-white/80 hover:!text-white disabled:!text-white/25" disabled={!hasNext} icon={<ChevronRight size={18} />} onClick={() => onIndexChange(index! + 1)} aria-label="Next file" />
                </Tooltip>
              </>
            )}
            {kind === 'image' && !failed && (
              <Tooltip title={actualSize ? 'Fit to window' : 'Actual size'}>
                <Button type="text" className="!text-white/80 hover:!text-white" icon={actualSize ? <Minimize2 size={16} /> : <Maximize2 size={16} />} onClick={() => setActualSize((v) => !v)} aria-label="Toggle zoom" />
              </Tooltip>
            )}
            <Tooltip title="Open in new tab">
              <Button type="text" className="!text-white/80 hover:!text-white" icon={<ExternalLink size={16} />} href={src} target="_blank" rel="noopener noreferrer" aria-label="Open in new tab" />
            </Tooltip>
            <Tooltip title="Download">
              <Button type="text" className="!text-white/80 hover:!text-white" icon={<Download size={16} />} onClick={() => onDownload(item)} aria-label="Download" />
            </Tooltip>
            <Tooltip title="Close (Esc)">
              <Button type="text" className="!text-white/80 hover:!text-white" icon={<X size={18} />} onClick={onClose} aria-label="Close" />
            </Tooltip>
          </div>
          <div className="relative flex-1 min-h-0 flex items-center justify-center bg-black/40">
            {navButton(-1)}
            {body}
            {navButton(1)}
            {loading && !failed && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <Spin />
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
};
