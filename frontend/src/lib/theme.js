import { useState } from 'react';

/** Dark-mode toggle. The initial class is set by an inline script in index.html (no flash). */
export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'));
  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle('dark', next);
    try { localStorage.setItem('ft-theme', next ? 'dark' : 'light'); } catch { /* private mode */ }
    setDark(next);
  };
  return [dark, toggle];
}
