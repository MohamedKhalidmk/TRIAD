// Tabs that keep the selected tab in the link parameter "tab".
// The arrow keys, Home and End move between the tabs.
// All tabs control the one TabPanel, but a tab can give the id of a different panel (panelId).
// On a narrow screen the tab list scrolls sideways (styles.css). The selected tab then moves into view,
// and a fade at an edge shows that more tabs are on that side.

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react';
import { useSearchParams } from 'react-router-dom';

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
  /** The id of the panel of this tab, if it is not the TabPanel ("<idPrefix>-panel"). */
  panelId?: string;
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

/**
 * Gives the classes "scroll-fade-left" and "scroll-fade-right" while a box that scrolls sideways has more content
 * on that side (styles.css adds the fade). "contentKey" changes when the content changes.
 */
export function useScrollFade(ref: RefObject<HTMLElement | null>, contentKey: unknown): string {
  const [edges, setEdges] = useState({ left: false, right: false });
  useEffect(() => {
    const box = ref.current;
    if (!box) return;
    const update = () => {
      const left = box.scrollLeft > 1;
      const right = box.scrollLeft + box.clientWidth < box.scrollWidth - 1;
      setEdges((old) => (old.left === left && old.right === right ? old : { left, right }));
    };
    update();
    box.addEventListener('scroll', update, { passive: true });
    const observer = new ResizeObserver(update);
    observer.observe(box);
    return () => {
      box.removeEventListener('scroll', update);
      observer.disconnect();
    };
  }, [ref, contentKey]);
  return `${edges.left ? ' scroll-fade-left' : ''}${edges.right ? ' scroll-fade-right' : ''}`;
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
  const listRef = useRef<HTMLDivElement>(null);
  const selectedIndex = tabs.findIndex((tab) => tab.id === selected);
  const fade = useScrollFade(listRef, tabs.length);

  // Scroll the tab list sideways (not the page) until the selected tab is fully visible.
  useEffect(() => {
    const list = listRef.current;
    const button = refs.current[selectedIndex];
    if (!list || !button || list.scrollWidth <= list.clientWidth) return;
    const listBox = list.getBoundingClientRect();
    const box = button.getBoundingClientRect();
    if (box.left < listBox.left) list.scrollLeft -= listBox.left - box.left;
    else if (box.right > listBox.right) list.scrollLeft += box.right - listBox.right;
  }, [selectedIndex, tabs.length]);

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
    <div className={`tabs${fade}`} role="tablist" aria-label={label} ref={listRef}>
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          ref={(element) => {
            refs.current[index] = element;
          }}
          type="button"
          role="tab"
          id={`${idPrefix}-tab-${tab.id}`}
          aria-controls={tab.panelId ?? `${idPrefix}-panel`}
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

interface TabPanelProps {
  idPrefix: string;
  selected: string;
  children: ReactNode;
  /** True when the selected tab has its own panel (panelId). */
  hidden?: boolean;
}

export function TabPanel({ idPrefix, selected, children, hidden }: TabPanelProps) {
  return (
    <div className="tab-panel" role="tabpanel" id={`${idPrefix}-panel`} aria-labelledby={`${idPrefix}-tab-${selected}`} hidden={hidden}>
      {children}
    </div>
  );
}
