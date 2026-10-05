// Apply the saved/system theme before first paint (ThemeProvider takes over once React runs).
// A separate file, not inline, so the CSP can stay `script-src 'self'`. Loaded blocking from index.html.
// Keep in sync with STORAGE_KEY in src/context/ThemeContext.tsx and canvas in src/theme/tokens.ts.
(function () {
  var mode = 'system';
  try { mode = localStorage.getItem('theme.mode') || 'system'; } catch (e) {}
  var dark = mode === 'dark' || (mode !== 'light' && (!window.matchMedia || window.matchMedia('(prefers-color-scheme: dark)').matches));
  var root = document.documentElement;
  root.dataset.theme = dark ? 'dark' : 'light';
  root.style.colorScheme = dark ? 'dark' : 'light';
  root.style.backgroundColor = dark ? '#0d1117' : '#f6f8fa';
})();
