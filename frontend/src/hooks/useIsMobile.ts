import { useEffect, useState } from 'react';

// Matches Tailwind's `md` breakpoint: below it the app uses the bottom bar and mobile layouts
const QUERY = '(max-width: 767.98px)';

const matches = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(QUERY).matches;

export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(matches);

  useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia(QUERY);
    const onChange = (e: MediaQueryListEvent) => setMobile(e.matches);
    setMobile(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  return mobile;
}
