// The chain of an assertion: the current item first, then the items that it superseded,
// with a line through them (GET /api/assertions/{id}/chain).

import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '../api/endpoints';
import type { AssertionView } from '../api/types';
import { IntentBadge, SourceBadge, VerificationBadge } from '../components/Badges';
import { Dialog } from '../components/Dialog';
import { ErrorPanel, Loading } from '../components/ErrorView';
import { formatDateTime } from '../lib/dates';
import { CATEGORY_LABELS } from '../lib/labels';
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

/** A chain, newest first. With strikeAll, the current item also gets a line (a new item will supersede it). */
export function ChainList({ items, strikeAll = false }: { items: AssertionView[]; strikeAll?: boolean }) {
  return (
    <ol className="chain-list">
      {items.map((item, index) => (
        <li key={item.id}>
          {index > 0 && (
            <span className="chain-arrow" aria-hidden="true">
              ↑ superseded by the item above
            </span>
          )}
          <ChainItem item={item} struck={strikeAll || !item.isCurrent || index > 0} />
        </li>
      ))}
    </ol>
  );
}

export function useChain(assertionId: number | null) {
  return useQuery({
    queryKey: queryKeys.chain(assertionId ?? 0),
    queryFn: ({ signal }) => api.chain(assertionId as number, signal),
    enabled: assertionId !== null,
  });
}

export function ChainDialog({ assertionId, onClose }: { assertionId: number | null; onClose: () => void }) {
  const chain = useChain(assertionId);
  return (
    <Dialog
      open={assertionId !== null}
      title="Assertion chain"
      subtitle="Newest first. The first item is the current one. The items with a line through them are superseded."
      onClose={onClose}
      size="large"
    >
      {chain.isPending ? (
        <Loading label="Wait. The app gets the chain." />
      ) : chain.isError ? (
        <ErrorPanel error={chain.error} onRetry={() => chain.refetch()} />
      ) : (
        <ChainList items={chain.data.items} />
      )}
    </Dialog>
  );
}
