// The clock of the top bar shows the time of the server (GET /api/health). Each write moves that time on
// (doc/api.md section 1.3). A chart, chain or audit read is also a write: it adds an audit record (section 3.6).

import type { QueryClient } from '@tanstack/react-query';
import { queryKeys } from '../api/endpoints';

/** The reads that write an audit record on the server, by the first part of the query key. */
export const AUDITED_READS: readonly string[] = [queryKeys.charts[0], queryKeys.chains[0], 'audit'];

/** Read GET /api/health again, so that the clock of the top bar shows the time of the latest write. */
export function refreshClock(client: QueryClient): void {
  void client.invalidateQueries({ queryKey: queryKeys.health });
}
