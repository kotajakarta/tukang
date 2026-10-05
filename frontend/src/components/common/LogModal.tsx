import React, { useEffect, useRef } from 'react';
import { Button, Modal, Spin } from 'antd';
import { useIsMobile } from '../../hooks/useIsMobile';

interface LogModalProps {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  lines: string[];
  loading: boolean;
  emptyText: string;
  /** Controls on the left of the footer (line count, refresh) */
  toolbar?: React.ReactNode;
  desktopWidth?: number;
}

/** Log viewer: a dialog on desktop, full screen on phones; always scrolled to the newest line */
export const LogModal: React.FC<LogModalProps> = ({ open, onClose, title, lines, loading, emptyText, toolbar, desktopWidth = 900 }) => {
  const isMobile = useIsMobile();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [lines, loading]);

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      width={isMobile ? '100%' : desktopWidth}
      style={isMobile ? { top: 0, maxWidth: '100vw', margin: 0, paddingBottom: 0 } : undefined}
      styles={isMobile ? { content: { borderRadius: 0, minHeight: '100dvh', display: 'flex', flexDirection: 'column' } } : undefined}
      footer={
        <div className="flex flex-wrap justify-between items-center gap-2 w-full">
          <div className="flex items-center gap-2">{toolbar}</div>
          <Button onClick={onClose}>Close</Button>
        </div>
      }
    >
      <div
        ref={scrollRef}
        className={`bg-canvas p-3 rounded-lg font-mono text-xs text-fg overflow-y-auto whitespace-pre-wrap break-words leading-relaxed border border-line ${
          isMobile ? 'h-[calc(100dvh-150px)]' : 'h-[480px]'
        }`}
      >
        {loading ? (
          <div className="flex justify-center items-center h-full">
            <Spin />
          </div>
        ) : lines.length === 0 ? (
          <div className="text-fg-subtle italic">{emptyText}</div>
        ) : (
          lines.map((line, idx) => (
            <div key={idx} className="hover:bg-surface px-1 py-0.5 rounded">
              {line}
            </div>
          ))
        )}
      </div>
    </Modal>
  );
};
