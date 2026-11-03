// Form fields with a label and a place for the error message.

import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { FieldMessage } from './ErrorView';

interface FieldFrameProps {
  label: ReactNode;
  error?: string;
  hint?: ReactNode;
  className?: string;
  children: (id: string, describedBy: string | undefined) => ReactNode;
}

function FieldFrame({ label, error, hint, className, children }: FieldFrameProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  return (
    <div className={`field ${error ? 'field-invalid' : ''} ${className ?? ''}`}>
      <label htmlFor={id}>{label}</label>
      {children(id, describedBy)}
      {hint && (
        <span className="field-hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId}>
          <FieldMessage message={error} />
        </span>
      )}
    </div>
  );
}

type TextFieldProps = InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; error?: string; hint?: ReactNode };

export function TextField({ label, error, hint, className, ...input }: TextFieldProps) {
  return (
    <FieldFrame label={label} error={error} hint={hint} className={className}>
      {(id, describedBy) => <input id={id} aria-describedby={describedBy} aria-invalid={error ? true : undefined} {...input} />}
    </FieldFrame>
  );
}

type TextAreaFieldProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { label: ReactNode; error?: string; hint?: ReactNode };

export function TextAreaField({ label, error, hint, className, ...input }: TextAreaFieldProps) {
  return (
    <FieldFrame label={label} error={error} hint={hint} className={className}>
      {(id, describedBy) => (
        <textarea id={id} aria-describedby={describedBy} aria-invalid={error ? true : undefined} {...input} />
      )}
    </FieldFrame>
  );
}

type SelectFieldProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label: ReactNode;
  error?: string;
  hint?: ReactNode;
  children: ReactNode;
};

export function SelectField({ label, error, hint, className, children, ...select }: SelectFieldProps) {
  return (
    <FieldFrame label={label} error={error} hint={hint} className={className}>
      {(id, describedBy) => (
        <select id={id} aria-describedby={describedBy} aria-invalid={error ? true : undefined} {...select}>
          {children}
        </select>
      )}
    </FieldFrame>
  );
}

/** Reads a text value of a form. An empty value gives null. */
export function formText(data: FormData, name: string): string | null {
  const value = data.get(name);
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}
