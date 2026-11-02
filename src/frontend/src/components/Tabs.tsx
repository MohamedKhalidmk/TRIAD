// Tabs that keep the selected tab in the link parameter "tab".
// The arrow keys, Home and End move between the tabs.

import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
}

/** Gives the selected tab from the link, or the first tab if the link has no correct tab. */
export function useTabParam<T extends string>(tabs: TabItem<T>[], fallback?: T): [T, (id: T) => void] {
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab');
  const known = tabs.find((tab) => tab.id === requested);
  const current = known ? known.id : fallback && tabs.some((tab) => tab.id === fallback) ? fallback : tabs[0]?.id;
  const select = (id: T) => {
    const next = new URLSearchParams(params);
    next.set('tab', id);
    setParams(next, { replace: true });
  };
  return [current as T, select];
}

interface TabListProps<T extends string> {
  tabs: TabItem<T>[];
  selected: T;
  onSelect: (id: T) => void;
  label: string;
  idPrefix: string;
}

export function TabList<T extends string>({ tabs, selected, onSelect, label, idPrefix }: TabListProps<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = -1;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next < 0) return;
    event.preventDefault();
    onSelect(tabs[next].id);
    refs.current[next]?.focus();
  };

  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          ref={(element) => {
            refs.current[index] = element;
          }}
          type="button"
          role="tab"
          id={`${idPrefix}-tab-${tab.id}`}
          aria-controls={`${idPrefix}-panel`}
          aria-selected={tab.id === selected}
          tabIndex={tab.id === selected ? 0 : -1}
          className={tab.id === selected ? 'tab tab-selected' : 'tab'}
          onClick={() => onSelect(tab.id)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ idPrefix, selected, children }: { idPrefix: string; selected: string; children: ReactNode }) {
  return (
    <div className="tab-panel" role="tabpanel" id={`${idPrefix}-panel`} aria-labelledby={`${idPrefix}-tab-${selected}`}>
      {children}
    </div>
  );
}
