/** @type {import('tailwindcss').Config} */

// Theme colours resolve to CSS variables that ThemeProvider writes from src/theme/tokens.ts,
// so every class follows the active light/dark theme and still supports opacity (bg-accent/15).
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        canvas: token('canvas'),
        surface: { DEFAULT: token('surface'), 2: token('surface-2') },
        line: { DEFAULT: token('line'), muted: token('line-muted') },
        fg: { DEFAULT: token('fg'), muted: token('fg-muted'), subtle: token('fg-subtle') },
        accent: { DEFAULT: token('accent'), emphasis: token('accent-emphasis') },
        success: token('success'),
        warning: token('warning'),
        danger: token('danger'),
        purple: token('purple'),
        cyan: token('cyan'),
      },
      screens: {
        xs: '400px',
      },
    },
  },
  plugins: [],
  corePlugins: {
    preflight: false, // Prevents Ant Design conflicts; the border reset lives in index.css
  }
}
