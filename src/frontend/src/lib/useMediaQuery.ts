import { useCallback, useSyncExternalStore } from 'react';

/**
 * Gives true while the CSS media query matches, for example "(max-width: 1100px)".
 * The value is correct on the first render, and it changes when the window size changes.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}
