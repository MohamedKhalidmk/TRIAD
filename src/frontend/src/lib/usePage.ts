// The page of a list view (doc/api.md section 1.5): the offset and the page size.
// When a filter changes, the list goes back to the first page.

import { useCallback, useState } from 'react';
import type { QueryKey } from '@tanstack/react-query';

/** The default number of rows on a page. */
export const PAGE_SIZE = 25;

export interface PageState {
  limit: number;
  /** The offset of the page that the user selected. */
  offset: number;
  /** The limit and the offset, for the request and the query key. */
  params: { limit: number; offset: number };
  setOffset: (offset: number) => void;
}

/**
 * Keeps the offset of a paged list.
 * `filters` holds the values that select the rows, for example [role, q]. When one of them changes,
 * the offset goes back to 0 in the same render. So the app does not ask for the old offset with the new filters.
 */
export function usePage(filters: readonly unknown[], limit = PAGE_SIZE): PageState {
  const filterKey = JSON.stringify(filters);
  const [state, setState] = useState({ filterKey, offset: 0 });
  let offset = state.offset;
  if (state.filterKey !== filterKey) {
    // React renders again at once with the new state (the pattern "store information from previous renders").
    setState({ filterKey, offset: 0 });
    offset = 0;
  }
  const setOffset = useCallback((next: number) => setState({ filterKey, offset: Math.max(0, next) }), [filterKey]);
  return { limit, offset, params: { limit, offset }, setOffset };
}

/** The offset of the last page. */
export function lastOffset(total: number, limit: number): number {
  return total > 0 ? Math.floor((total - 1) / limit) * limit : 0;
}

/** The offset of the next page, or undefined after the last page (for useInfiniteQuery). */
export function nextOffset(page: { items: unknown[]; total: number; offset: number }): number | undefined {
  const next = page.offset + page.items.length;
  return page.items.length > 0 && next < page.total ? next : undefined;
}

/**
 * The placeholderData of a paged query that belongs to one patient or one chain.
 * It keeps the previous page while the next page loads (as keepPreviousData does), but only if the previous query
 * has the same key prefix. So the rows of a different patient never show, not even for a short time.
 */
export function keepPageOf(prefix: QueryKey) {
  return <T>(previous: T | undefined, previousQuery?: { queryKey: QueryKey }): T | undefined =>
    previousQuery && prefix.every((part, index) => Object.is(previousQuery.queryKey[index], part)) ? previous : undefined;
}
