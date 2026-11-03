// The Care Assistant pane (3MT slide style): past chats, the messages and the input box.
// Each assistant answer shows one evidence card for each citation, by rank.
// A send uses a new clientTurnId. "Try again" sends the same clientTurnId, so the server does not add the turn twice.

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { isAbortError, newClientTurnId } from '../api/client';
import { api, queryKeys } from '../api/endpoints';
import type { ChatSession, ChatTurn, Patient, UserView } from '../api/types';
import { Badge } from '../components/Badges';
import { ErrorBanner, Loading } from '../components/ErrorView';
import { formatCount } from '../components/Pager';
import { formatDateTime, formatTime } from '../lib/dates';
import { nextOffset, PAGE_SIZE } from '../lib/usePage';
import { EvidenceCard } from './EvidenceCard';

interface PendingTurn {
  clientTurnId: string;
  text: string;
  error: unknown;
}

function mergeTurns(turns: ChatTurn[], added: ChatTurn[]): ChatTurn[] {
  const byId = new Map<number, ChatTurn>();
  for (const turn of [...turns, ...added]) byId.set(turn.id, turn);
  return [...byId.values()].sort((a, b) => a.seq - b.seq);
}

function suggestions(user: UserView, patient: Patient): string[] {
  if (user.role === 'Patient') return ['What medications am I taking?', 'What is my plan?', 'Do I have any allergies?'];
  const pronoun = patient.sex === 'female' ? 'she' : patient.sex === 'male' ? 'he' : 'the patient';
  const list = [`Is ${pronoun} allergic to penicillin?`, 'Any allergies?', 'What did the nurse recommend?', 'What is the plan?'];
  if (user.role === 'Nurse') list.splice(2, 1, 'What medications is the patient taking?');
  return list;
}

export function CareAssistant({ patient, user }: { patient: Patient; user: UserView }) {
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // The past chats, newest first: the first page, and one more page for each "Show older chats".
  const sessions = useInfiniteQuery({
    queryKey: queryKeys.chatSessions(patient.id),
    queryFn: ({ signal, pageParam }) => api.chatSessions(patient.id, { limit: PAGE_SIZE, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
  });
  const session = useQuery({
    queryKey: queryKeys.chatSession(sessionId ?? 0),
    queryFn: ({ signal }) => api.chatSession(sessionId as number, signal),
    enabled: sessionId !== null,
  });

  const createSession = useMutation({
    mutationFn: () => api.createChatSession(patient.id),
    onSuccess: (created) => {
      queryClient.setQueryData(queryKeys.chatSession(created.id), created);
      queryClient.invalidateQueries({ queryKey: queryKeys.chatSessions(patient.id) });
      setSessionId(created.id);
      setPending(null);
      inputRef.current?.focus();
    },
  });

  const turns = session.data?.turns ?? [];

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [turns.length, pending, sessionId]);

  const send = async (text: string, clientTurnId: string) => {
    setPending({ clientTurnId, text, error: null });
    let target = sessionId;
    try {
      if (target === null) {
        const created = await api.createChatSession(patient.id);
        queryClient.setQueryData(queryKeys.chatSession(created.id), created);
        setSessionId(created.id);
        target = created.id;
      }
      const result = await api.postTurn(target, { clientTurnId, text });
      queryClient.setQueryData<ChatSession>(queryKeys.chatSession(target), (old) =>
        old ? { ...old, turns: mergeTurns(old.turns, [result.userTurn, result.assistantTurn]) } : old,
      );
      setPending(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.chatSessions(patient.id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.audit(patient.id) });
      if (result.assistantTurn.kind === 'tell' || result.assistantTurn.recordedIds.length > 0) {
        queryClient.invalidateQueries({ queryKey: queryKeys.charts });
        queryClient.invalidateQueries({ queryKey: queryKeys.chains });
      }
    } catch (error) {
      if (isAbortError(error)) return;
      setPending({ clientTurnId, text, error });
    }
  };

  const busy = pending !== null && pending.error === null;

  const onSubmit = (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    void send(text, newClientTurnId());
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onSubmit();
    }
  };

  const mode = session.data?.mode;
  const pastChats = sessions.data?.pages.flatMap((page) => page.items) ?? [];
  const chatCount = sessions.data?.pages[0]?.total ?? 0;

  return (
    <section className="assistant" aria-labelledby="assistant-title">
      <header className="window-bar">
        <span className="window-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <h2 id="assistant-title">Care Assistant</h2>
        {mode && (
          <Badge tone="mode" title={session.data?.model ? `Model: ${session.data.model}` : 'The chat mode of this session'}>
            Mode: {mode}
          </Badge>
        )}
      </header>

      <div className="assistant-sessions">
        <div className="field field-inline">
          <label htmlFor="assistant-session">Chat</label>
          <select
            id="assistant-session"
            value={sessionId ?? ''}
            onChange={(event) => {
              setSessionId(event.target.value ? Number(event.target.value) : null);
              setPending(null);
            }}
          >
            <option value="">{sessionId === null ? 'New chat (not started)' : 'Close this chat'}</option>
            {pastChats.map((item) => (
              <option key={item.id} value={item.id}>
                {formatDateTime(item.startedAt)} · {item.firstQuestion ?? 'No question yet'} ({item.turnCount} turns)
              </option>
            ))}
          </select>
        </div>
        <button type="button" className="button button-small" onClick={() => createSession.mutate()} disabled={createSession.isPending}>
          New chat
        </button>
      </div>
      {sessions.hasNextPage && (
        <div className="pager-more">
          <span className="muted small" aria-live="polite">
            {formatCount(pastChats.length)} of {formatCount(chatCount)} past chats in the list.
          </span>
          <button type="button" className="link-button" onClick={() => void sessions.fetchNextPage()} disabled={sessions.isFetchingNextPage}>
            {sessions.isFetchingNextPage ? 'Wait…' : 'Show older chats'}
          </button>
        </div>
      )}
      <ErrorBanner error={createSession.error} onDismiss={() => createSession.reset()} />

      <div className="assistant-messages" ref={listRef} aria-live="polite">
        {sessionId !== null && session.isPending && <Loading label="Wait. The app gets the chat." />}
        {sessionId !== null && session.isError && <ErrorBanner error={session.error} />}
        {turns.length === 0 && pending === null && !(sessionId !== null && session.isPending) && (
          <div className="assistant-empty">
            <p>
              {user.role === 'Patient'
                ? 'Ask about your record. The answers show their sources.'
                : 'Ask about this patient. Each answer shows the current assertion and the assertions that it supersedes.'}
            </p>
            <div className="suggestions" aria-label="Example questions">
              {suggestions(user, patient).map((text) => (
                <button
                  key={text}
                  type="button"
                  className="chip"
                  onClick={() => {
                    setDraft(text);
                    inputRef.current?.focus();
                  }}
                >
                  {text}
                </button>
              ))}
            </div>
            {patient.permissions.tell && (
              <p className="muted small">
                You can also tell a fact. For example:{' '}
                {user.role === 'Patient' ? '“My mother had diabetes.”' : '“The patient\'s father died of a heart attack.”'} The
                assistant records it as unconfirmed.
              </p>
            )}
            {sessionId === null && pastChats.length > 0 && (
              <div className="past-chats">
                <span className="eyebrow">Past chats</span>
                <ul>
                  {pastChats.slice(0, 5).map((item) => (
                    <li key={item.id}>
                      <button type="button" className="link-button" onClick={() => setSessionId(item.id)}>
                        {item.firstQuestion ?? 'No question yet'}
                      </button>{' '}
                      <span className="muted small">
                        {formatDateTime(item.startedAt)} · {item.turnCount} turns · {item.mode}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} />
        ))}
        {pending && (
          <>
            <div className="bubble-row bubble-row-user">
              <div className="bubble bubble-user">{pending.text}</div>
            </div>
            {pending.error ? (
              <div className="pending-error">
                <ErrorBanner error={pending.error} />
                <div className="row">
                  <button type="button" className="button button-small" onClick={() => void send(pending.text, pending.clientTurnId)}>
                    Try again
                  </button>
                  <button
                    type="button"
                    className="button button-small"
                    onClick={() => {
                      setDraft(pending.text);
                      setPending(null);
                    }}
                  >
                    Edit the question
                  </button>
                </div>
              </div>
            ) : (
              <div className="bubble-row">
                <div className="bubble bubble-assistant bubble-typing" role="status">
                  The assistant reads the record…
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <form className="assistant-input" onSubmit={onSubmit}>
        <label htmlFor="assistant-input" className="visually-hidden">
          Message to the Care Assistant
        </label>
        <textarea
          id="assistant-input"
          ref={inputRef}
          rows={2}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={patient.permissions.tell ? 'Ask a question or tell a fact' : 'Ask a question'}
        />
        <button type="submit" className="button button-primary" disabled={!draft.trim() || busy}>
          Send
        </button>
      </form>
    </section>
  );
}

function TurnView({ turn }: { turn: ChatTurn }) {
  if (turn.speaker === 'User') {
    return (
      <div className="bubble-row bubble-row-user">
        <div className="bubble bubble-user">{turn.text}</div>
        <span className="bubble-time">{formatTime(turn.createdAt)}</span>
      </div>
    );
  }
  const recorded = new Set(turn.recordedIds);
  const cards = [...turn.cards].sort((a, b) => a.rank - b.rank);
  return (
    <div className="assistant-turn">
      <div className="bubble-row">
        <div className="bubble bubble-assistant">{turn.text}</div>
      </div>
      <div className="bubble-time">
        {formatTime(turn.createdAt)}
        {turn.kind === 'tell' && (turn.recordedIds.length > 0 ? ' · Recorded from your message' : ' · Nothing recorded')}
        {cards.length === 0 && turn.kind === 'ask' && ' · No item cited'}
      </div>
      {cards.map((card) => (
        <EvidenceCard key={`${card.rank}-${card.assertion.id}`} card={card} recorded={recorded.has(card.assertion.id)} />
      ))}
    </div>
  );
}
