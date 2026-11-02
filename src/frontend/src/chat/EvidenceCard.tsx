// The evidence card of the 3MT slide: the current assertion, then the assertions that it supersedes,
// with a line through them ("Front desk, 2019: penicillin allergy").

import type { Card } from '../api/types';
import { Badge, IntentBadge, SourceBadge, VerificationBadge } from '../components/Badges';
import { formatDate } from '../lib/dates';
import { CATEGORY_LABELS } from '../lib/labels';
import { detailSummary, supersededLine } from '../patient/assertionText';

export function EvidenceCard({ card, recorded }: { card: Card; recorded: boolean }) {
  const { assertion } = card;
  const summary = detailSummary(assertion);
  return (
    <article className="evidence-card" aria-label={`Evidence ${card.rank}: ${assertion.display}`}>
      <div className="evidence-label">Assertion</div>
      <p className="evidence-main">
        <strong>{assertion.author.label}</strong>, {formatDate(assertion.assertedAt)}: {assertion.statement}
      </p>
      <div className="evidence-meta">
        <span className="muted">
          {CATEGORY_LABELS[assertion.category]}: {assertion.display}
          {summary ? ` (${summary})` : ''} · {assertion.author.name}
        </span>
      </div>
      <div className="badges">
        {recorded && <Badge tone="recorded">Recorded, unconfirmed</Badge>}
        <IntentBadge intent={assertion.intent} />
        <VerificationBadge verification={assertion.verification} />
        <SourceBadge source={assertion.source} />
      </div>
      {card.supersedes.length > 0 && (
        <>
          <div className="evidence-label evidence-label-supersedes">Supersedes</div>
          <ul className="evidence-supersedes">
            {card.supersedes.map((old) => (
              <li key={old.id}>
                <s>{supersededLine(old)}</s>
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}
