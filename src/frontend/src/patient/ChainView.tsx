// The chain of an assertion: the current item first, then the items that it superseded,
// with a line through them (GET /api/assertions/{id}/chain?limit=&offset=). A long chain has pages.

import { useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, queryKeys, type PageParams } from '../api/endpoints';
import type { AssertionView } from '../api/types';
import { IntentBadge, SourceBadge, VerificationBadge } from '../components/Badges';
import { Dialog } from '../components/Dialog';
import { ErrorBanner, ErrorPanel, Loading } from '../components/ErrorView';
import { Pager } from '../components/Pager';
import { formatDateTime } from '../lib/dates';
import { CATEGORY_LABELS } from '../lib/labels';
import { keepPageOf, usePage } from '../lib/usePage';
import { detailSummary } from './assertionText';

export function ChainItem({ item, struck }: { item: AssertionView; struck: boolean }) {
  const summary = detailSummary(item);
  return (
    <div className={struck ? 'chain-item chain-item-struck' : 'chain-item'}>
      <div className="chain-item-head">
        <strong>{item.author.label}</strong>
        <span className="muted"> · {item.author.name}</span>
        <span className="muted"> · {formatDateTime(item.assertedAt)}</span>
      </div>
      <div className="chain-item-body">
        {struck ? (
          <s>
            {CATEGORY_LABELS[item.category]}: {item.display}
            {summary ? ` (${summary})` : ''} — {item.statement}
          </s>
        ) : (
          <>
            {CATEGORY_LABELS[item.category]}: <strong>{item.display}</strong>
            {summary ? ` (${summary})` : ''} — {item.statement}
          </>
        )}
      </div>
      <div className="badges">
        <IntentBadge intent={item.intent} />
        <VerificationBadge verification={item.verification} />
        <SourceBadge source={item.source} />
        {struck && <span className="badge badge-muted">Superseded</span>}
        {!struck && item.isCurrent && <span className="badge badge-ok">Current</span>}
      </div>
    </div>
  );
}

/**
 * One page of a chain, newest first. offset is the offset of the page: only the first item of the chain is current.
 * With strikeAll, the current item also gets a line (a new item will supersede it).
 */
export function ChainList({ items, offset = 0, strikeAll = false }: { items: AssertionView[]; offset?: number; strikeAll?: boolean }) {
  return (
    <ol className="chain-list" start={offset + 1}>
      {items.map((item, index) => (
        <li key={item.id}>
          {index > 0 && (
            <span className="chain-arrow" aria-hidden="true">
              ↑ superseded by the item above
            </span>
          )}
          <ChainItem item={item} struck={strikeAll || !item.isCurrent || offset + index > 0} />
        </li>
      ))}
    </ol>
  );
}

/** One page of the chain of an assertion. Each page read writes an audit record. */
export function useChain(assertionId: number | null, page: PageParams) {
  return useQuery({
    queryKey: queryKeys.chain(assertionId ?? 0, page),
    queryFn: ({ signal }) => api.chain(assertionId as number, page, signal),
    enabled: assertionId !== null,
    placeholderData: keepPageOf(queryKeys.chainPages(assertionId ?? 0)),
  });
}

/** The chain of an assertion, with a pager. inline: a small error banner (in a form), not the full error panel. */
export function ChainPages({ assertionId, strikeAll = false, inline = false }: { assertionId: number; strikeAll?: boolean; inline?: boolean }) {
  const page = usePage([assertionId]);
  const chain = useChain(assertionId, page.params);
  const listRef = useRef<HTMLDivElement>(null);
  if (chain.isPending) return <Loading label="Wait. The app gets the chain." />;
  if (chain.isError) return inline ? <ErrorBanner error={chain.error} /> : <ErrorPanel error={chain.error} onRetry={() => chain.refetch()} />;
  return (
    <div ref={listRef} className={chain.isPlaceholderData ? 'paged-busy' : undefined}>
      <ChainList items={chain.data.items} offset={chain.data.offset} strikeAll={strikeAll} />
      <Pager page={chain.data} state={page} label="the chain" busy={chain.isPlaceholderData} scrollTo={listRef} />
    </div>
  );
}

export function ChainDialog({ assertionId, onClose }: { assertionId: number | null; onClose: () => void }) {
  return (
    <Dialog
      open={assertionId !== null}
      title="Assertion chain"
      subtitle="Newest first. The first item is the current one. The items with a line through them are superseded."
      onClose={onClose}
      size="large"
    >
      {assertionId !== null && <ChainPages assertionId={assertionId} />}
    </Dialog>
  );
}
