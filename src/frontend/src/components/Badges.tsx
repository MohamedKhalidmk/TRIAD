// Small labels for the intent, the verification, the source and other values.

import type { Intent, Source, Verification } from '../api/types';
import { VERIFICATION_LABELS } from '../lib/labels';
import type { ReactNode } from 'react';

export function Badge({ tone = 'neutral', children, title }: { tone?: string; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

const INTENT_TONES: Record<Intent, string> = {
  Decision: 'decision',
  Recommendation: 'recommendation',
  Report: 'report',
};

export function IntentBadge({ intent }: { intent: Intent }) {
  return (
    <Badge tone={INTENT_TONES[intent]} title="Intent">
      {intent}
    </Badge>
  );
}

const VERIFICATION_TONES: Record<Verification, string> = {
  Confirmed: 'ok',
  Refuted: 'danger',
  EnteredInError: 'danger',
  Unconfirmed: 'muted',
  Provisional: 'warn',
  Differential: 'warn',
};

export function VerificationBadge({ verification }: { verification: Verification }) {
  return (
    <Badge tone={VERIFICATION_TONES[verification]} title="Verification">
      {VERIFICATION_LABELS[verification]}
    </Badge>
  );
}

export function SourceBadge({ source }: { source: Source }) {
  if (source !== 'Agent') return null;
  return (
    <Badge tone="agent" title="The Care Assistant recorded this item">
      Agent
    </Badge>
  );
}
