import React, { useEffect, useRef, useState } from 'react';
import { Card, Button, Space, Tag } from 'antd';
import { ReloadOutlined, CodeOutlined, FullscreenOutlined } from '@ant-design/icons';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from 'lucide-react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { useServer } from '../../context/ServerContext';
import { notifyUnauthorized, WS_UNAUTHORIZED } from '../../services/api';

// The shell stays dark in both themes: ANSI colours from programs on the server assume a dark background.
const TERMINAL_BG = '#0d1117';

/** Keys a phone keyboard lacks, as the bytes a terminal sends for them */
const MOBILE_KEYS: { label: React.ReactNode; seq?: string; aria: string }[] = [
  { label: 'Esc', seq: '\x1b', aria: 'Escape' },
  { label: 'Tab', seq: '\t', aria: 'Tab' },
  { label: 'Ctrl', aria: 'Control (applies to the next key)' },
  { label: <ArrowUp size={16} />, seq: '\x1b[A', aria: 'Arrow up' },
  { label: <ArrowDown size={16} />, seq: '\x1b[B', aria: 'Arrow down' },
  { label: <ArrowLeft size={16} />, seq: '\x1b[D', aria: 'Arrow left' },
  { label: <ArrowRight size={16} />, seq: '\x1b[C', aria: 'Arrow right' },
  { label: '|', seq: '|', aria: 'Pipe' },
  { label: '/', seq: '/', aria: 'Slash' },
  { label: '-', seq: '-', aria: 'Dash' },
  { label: '~', seq: '~', aria: 'Tilde' },
];

interface WebTerminalProps {
  /** Directory the shell starts in (e.g. opened from Files); the server's default when omitted */
  cwd?: string;
}

export const WebTerminal: React.FC<WebTerminalProps> = ({ cwd }) => {
  const { activeServer } = useServer();
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermInstance = useRef<Terminal | null>(null);
  const fitAddonInstance = useRef<FitAddon | null>(null);
  // Sticky Ctrl from the mobile key bar: the next typed character is sent as its control code
  const [ctrlArmed, setCtrlArmed] = useState(false);
  const ctrlArmedRef = useRef(false);
  ctrlArmedRef.current = ctrlArmed;
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');

  const initTerminal = () => {
    if (!terminalRef.current || !activeServer) return;

    // Cleanup previous instance
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (xtermInstance.current) {
      xtermInstance.current.dispose();
      xtermInstance.current = null;
    }

    const term = new Terminal({
      cursorBlink: true,
      fontFamily: 'Consolas, "Cascadia Code", "Courier New", Menlo, Monaco, monospace',
      fontSize: 13,
      lineHeight: 1.2,
      letterSpacing: 0,
      theme: {
        background: '#0d1117',
        foreground: '#c9d1d9',
        cursor: '#58a6ff',
        selectionBackground: 'rgba(56, 139, 253, 0.35)',
        black: '#484f58',
        red: '#ff7b72',
        green: '#3fb950',
        yellow: '#d29922',
        blue: '#58a6ff',
        magenta: '#bc8cff',
        cyan: '#39c5cf',
        white: '#b1bac4',
      },
      convertEol: true,
      scrollback: 5000,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());

    term.open(terminalRef.current);

    // Initial fit after DOM paint and when fonts are confirmed ready
    requestAnimationFrame(() => {
      try {
        fitAddon.fit();
      } catch (e) {}
    });

    if (document.fonts) {
      document.fonts.ready.then(() => {
        try {
          fitAddon.fit();
        } catch (e) {}
      });
    }

    xtermInstance.current = term;
    fitAddonInstance.current = fitAddon;

    // Connect WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const cols = term.cols || 80;
    const rows = term.rows || 24;
    const cwdParam = cwd ? `&cwd=${encodeURIComponent(cwd)}` : '';
    const wsUrl = `${protocol}//${window.location.host}/ws/terminal/${activeServer.id}?cols=${cols}&rows=${rows}${cwdParam}`;

    setStatus('connecting');
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('connected');
      term.focus();
    };

    ws.onmessage = (event) => {
      term.write(event.data);
    };

    ws.onclose = (event) => {
      setStatus('disconnected');
      if (event.code === WS_UNAUTHORIZED) {
        notifyUnauthorized();
        return;
      }
      term.write('\r\n\x1b[31m[Session Disconnected]\x1b[0m\r\n');
    };

    ws.onerror = () => {
      setStatus('disconnected');
    };

    term.onData((data) => {
      if (ws.readyState !== WebSocket.OPEN) return;
      if (ctrlArmedRef.current && data.length === 1 && /[a-z@\[\\\]^_]/i.test(data)) {
        ws.send(String.fromCharCode(data.toUpperCase().charCodeAt(0) & 31));
        setCtrlArmed(false);
        return;
      }
      ws.send(data);
    });

    const handleResize = () => {
      if (fitAddon && term) {
        try {
          fitAddon.fit();
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
          }
        } catch (e) {}
      }
    };

    window.addEventListener('resize', handleResize);

    const resizeObserver = new ResizeObserver(() => {
      requestAnimationFrame(handleResize);
    });

    if (terminalRef.current) {
      resizeObserver.observe(terminalRef.current);
    }

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', handleResize);
      if (ws) ws.close();
      term.dispose();
    };
  };

  useEffect(() => {
    const cleanup = initTerminal();
    return () => {
      if (cleanup) cleanup();
    };
  }, [activeServer?.id, cwd]);

  const sendKey = (seq: string) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(seq);
    xtermInstance.current?.focus();
  };

  return (
    <Card
      title={
        <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
          <CodeOutlined className="text-accent" />
          <span className="text-xs sm:text-sm font-semibold truncate max-w-[100px] sm:max-w-none">Shell</span>
          <Tag color={status === 'connected' ? 'success' : status === 'connecting' ? 'processing' : 'error'} className="m-0 text-[10px] sm:text-xs">
            {status.toUpperCase()}
          </Tag>
          {activeServer && (
            <Tag color="blue" className="m-0 text-[10px] sm:text-xs hidden sm:inline-block truncate max-w-[120px]">
              {activeServer.name}
            </Tag>
          )}
          {cwd && (
            <Tag className="m-0 text-[10px] sm:text-xs font-mono truncate max-w-[160px] sm:max-w-[320px]" title={cwd}>
              {cwd}
            </Tag>
          )}
        </div>
      }
      extra={
        <Space size="small">
          <Button icon={<ReloadOutlined />} size="small" onClick={() => initTerminal()}>
            <span className="hidden sm:inline">Restart</span>
          </Button>
          <Button
            icon={<FullscreenOutlined />}
            size="small"
            onClick={() => fitAddonInstance.current?.fit()}
          >
            <span className="hidden sm:inline">Fit Size</span>
          </Button>
        </Space>
      }
      className="h-[calc(100dvh-148px)] md:h-[calc(100dvh-104px)] flex flex-col p-0 overflow-hidden"
      styles={{ body: { flex: 1, minHeight: 0, padding: 0, backgroundColor: TERMINAL_BG, display: 'flex', flexDirection: 'column' } }}
    >
      <div className="flex-1 min-h-0 w-full p-2 box-border overflow-hidden">
        <div ref={terminalRef} className="w-full h-full" style={{ padding: 0, margin: 0 }} />
      </div>
      <div className="md:hidden flex gap-1.5 overflow-x-auto px-2 py-2 border-t border-[#30363d] bg-[#161b22]" role="toolbar" aria-label="Terminal keys">
        {MOBILE_KEYS.map(({ label, seq, aria }) => {
          const isCtrl = !seq;
          const on = isCtrl && ctrlArmed;
          return (
            <button
              key={aria}
              type="button"
              aria-label={aria}
              aria-pressed={isCtrl ? on : undefined}
              // Keep focus (and the phone keyboard) on the terminal
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => (isCtrl ? setCtrlArmed((v) => !v) : sendKey(seq!))}
              className={`flex-shrink-0 inline-flex items-center justify-center min-w-[44px] h-9 px-2.5 rounded-md font-mono text-sm cursor-pointer border ${
                on ? 'bg-[#1f6feb] border-[#1f6feb] text-white' : 'bg-[#21262d] border-[#30363d] text-[#e6edf3] active:bg-[#30363d]'
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>
    </Card>
  );
};

