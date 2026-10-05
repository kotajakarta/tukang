/**
 * Colour tokens: the single source of truth for both themes.
 *
 * ThemeProvider writes each token to <html> as a CSS variable (`--c-<name>`, as "R G B" so Tailwind
 * can apply opacity), Tailwind maps its colour names onto those variables (tailwind.config.js), and
 * antd gets the same values through its theme tokens. Components never hardcode a colour.
 */
export type ThemeName = 'light' | 'dark';

export const TOKEN_NAMES = [
  'canvas', // page background
  'surface', // cards, header, sidebar
  'surface-2', // hover, raised or inset areas
  'line', // borders
  'line-muted', // dividers inside a surface (table rows)
  'fg', // primary text
  'fg-muted', // secondary text
  'fg-subtle', // tertiary text, placeholders, section titles
  'accent', // links, active navigation, focus
  'accent-emphasis', // filled primary controls (white text on top)
  'success',
  'warning',
  'danger',
  'purple',
  'cyan',
] as const;

export type TokenName = (typeof TOKEN_NAMES)[number];
export type Palette = Record<TokenName, string>;

export const PALETTES: Record<ThemeName, Palette> = {
  dark: {
    canvas: '#0d1117',
    surface: '#161b22',
    'surface-2': '#1f242c',
    line: '#30363d',
    'line-muted': '#21262d',
    fg: '#e6edf3',
    'fg-muted': '#9198a1',
    'fg-subtle': '#848d97',
    accent: '#4493f8',
    'accent-emphasis': '#1f6feb',
    success: '#3fb950',
    warning: '#d29922',
    danger: '#f85149',
    purple: '#ab7df8',
    cyan: '#39c5cf',
  },
  light: {
    canvas: '#f6f8fa',
    surface: '#ffffff',
    'surface-2': '#eff2f5',
    line: '#d1d9e0',
    'line-muted': '#e6eaef',
    fg: '#1f2328',
    'fg-muted': '#59636e',
    'fg-subtle': '#636c76',
    accent: '#0969da',
    'accent-emphasis': '#0969da',
    success: '#1a7f37',
    warning: '#875e00',
    danger: '#d1242f',
    purple: '#8250df',
    cyan: '#1b7c83',
  },
};

/** "#rrggbb" -> "r g b" (the form Tailwind's `<alpha-value>` needs) */
export const toRgbChannels = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
};

/** Same colour with an alpha channel, for libraries that take plain CSS colours (charts) */
export const withAlpha = (hex: string, alpha: number) => `rgb(${toRgbChannels(hex)} / ${alpha})`;
