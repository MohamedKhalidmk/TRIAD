// The pager under a paged list: "1–25 of 1,148", with the Previous and Next buttons.
// The range text is a live region, so a screen reader reads the new range after a page change.

import { useEffect, type RefObject } from 'react';
import type { Page } from '../api/types';
import { lastOffset, type PageState } from '../lib/usePage';

const NUMBER = new Intl.NumberFormat('en-US');

/** A number with a comma between the thousands, for example "1,148". */
export function formatCount(value: number): string {
  return NUMBER.format(value);
}

interface PagerProps {
  /** The page that the list shows now. While the next page loads, it is the previous page. */
  page: Page<unknown> | undefined;
  state: PageState;
  /** The name of the list for the label of the nav, for example "the staff list". */
  label: string;
  /** True while the next page loads (isPlaceholderData). */
  busy?: boolean;
  /** The top of the list. After a page change, the app scrolls to it if it is above the screen. */
  scrollTo?: RefObject<HTMLElement | null>;
}

export function Pager({ page, state, label, busy = false, scrollTo }: PagerProps) {
  const { limit, offset, setOffset } = state;

  // A write can make the list shorter. Then the offset can be after the end: go to the last page.
  useEffect(() => {
    if (!page || busy || page.items.length > 0 || page.offset === 0) return;
    setOffset(lastOffset(page.total, limit));
  }, [page, busy, limit, setOffset]);

  if (!page || page.items.length === 0) return null;

  const total = page.total;
  const first = page.offset + 1;
  const last = page.offset + page.items.length;
  const onePage = offset === 0 && total <= limit;

  const go = (next: number) => {
    setOffset(next);
    const top = scrollTo?.current;
    if (top && top.getBoundingClientRect().top < 0) top.scrollIntoView({ block: 'start' });
  };

  return (
    <nav className="pager" aria-label={`Pages of ${label}`} aria-busy={busy || undefined}>
      <span className="pager-range" aria-live="polite">
        {formatCount(first)}–{formatCount(last)} of {formatCount(total)}
      </span>
      {!onePage && (
        <span className="pager-buttons">
          <button type="button" className="button button-small" disabled={offset === 0} onClick={() => go(Math.max(0, offset - limit))}>
            Previous
          </button>
          <button type="button" className="button button-small" disabled={offset + limit >= total} onClick={() => go(offset + limit)}>
            Next
          </button>
        </span>
      )}
    </nav>
  );
}
