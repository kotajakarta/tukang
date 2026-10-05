import React, { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { ConfigProvider, theme as antdTheme } from 'antd';
import { PALETTES, Palette, TOKEN_NAMES, ThemeName, toRgbChannels } from '../theme/tokens';

export type ThemeMode = 'system' | 'light' | 'dark';

interface ThemeContextValue {
  /** What the user picked */
  mode: ThemeMode;
  /** What is actually shown (system resolved against the device setting) */
  resolved: ThemeName;
  palette: Palette;
  setMode: (mode: ThemeMode) => void;
  /** system -> light -> dark -> system */
  cycleMode: () => void;
}

const STORAGE_KEY = 'theme.mode'; // also read by the pre-paint script public/theme-init.js
const MODES: ThemeMode[] = ['system', 'light', 'dark'];

const readMode = (): ThemeMode => {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
  } catch {
    return 'system';
  }
};

const darkQuery = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null);

const applyToDocument = (name: ThemeName, palette: Palette) => {
  const root = document.documentElement;
  for (const token of TOKEN_NAMES) root.style.setProperty(`--c-${token}`, toRgbChannels(palette[token]));
  root.dataset.theme = name;
  root.style.colorScheme = name;
  root.style.backgroundColor = palette.canvas;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', palette.surface);
};

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [mode, setModeState] = useState<ThemeMode>(readMode);
  const [systemDark, setSystemDark] = useState(() => darkQuery()?.matches ?? true);

  useEffect(() => {
    const mq = darkQuery();
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const resolved: ThemeName = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode;
  const palette = PALETTES[resolved];

  // Before paint, so a theme change never shows a frame of mixed colours
  useLayoutEffect(() => applyToDocument(resolved, palette), [resolved, palette]);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* per-browser preference only; fine to lose */
    }
  }, []);

  const cycleMode = useCallback(() => setMode(MODES[(MODES.indexOf(mode) + 1) % MODES.length]), [mode, setMode]);

  const antdConfig = useMemo(
    () => ({
      algorithm: resolved === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
      token: {
        colorPrimary: palette['accent-emphasis'],
        colorInfo: palette['accent-emphasis'],
        colorLink: palette.accent,
        colorSuccess: palette.success,
        colorWarning: palette.warning,
        colorError: palette.danger,
        colorBgBase: palette.canvas,
        colorBgLayout: palette.canvas,
        colorBgContainer: palette.surface,
        colorBgElevated: resolved === 'dark' ? palette['surface-2'] : palette.surface,
        colorBorder: palette.line,
        colorBorderSecondary: palette['line-muted'],
        colorText: palette.fg,
        colorTextSecondary: palette['fg-muted'],
        colorTextTertiary: palette['fg-subtle'],
        borderRadius: 6,
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif",
      },
      components: {
        Layout: { headerBg: palette.surface, siderBg: palette.surface, bodyBg: palette.canvas, headerHeight: 56, headerPadding: 0 },
        Table: { headerBg: palette['surface-2'], headerColor: palette['fg-muted'], rowHoverBg: palette['surface-2'], borderColor: palette['line-muted'] },
      },
    }),
    [resolved, palette],
  );

  // Static antd APIs (message.*, Modal.confirm) render outside this tree; give them the same theme
  useLayoutEffect(() => {
    ConfigProvider.config({ holderRender: (children) => <ConfigProvider theme={antdConfig}>{children}</ConfigProvider> });
  }, [antdConfig]);

  const value = useMemo(() => ({ mode, resolved, palette, setMode, cycleMode }), [mode, resolved, palette, setMode, cycleMode]);

  return (
    <ThemeContext.Provider value={value}>
      <ConfigProvider theme={antdConfig}>{children}</ConfigProvider>
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
};
