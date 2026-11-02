// A modal dialog on the native <dialog> element. Escape and the close button close it.
// The variant "drawer" shows the dialog on the right side of the screen.

import { useEffect, useId, useRef, type ReactNode } from 'react';

interface DialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  variant?: 'modal' | 'drawer';
  size?: 'small' | 'medium' | 'large';
  /** Text under the title. */
  subtitle?: ReactNode;
}

export function Dialog({ open, title, onClose, children, variant = 'modal', size = 'medium', subtitle }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`dialog dialog-${variant} dialog-${size}`}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {open && (
        <div className="dialog-frame">
          <header className="dialog-header">
            <div>
              <h2 id={titleId}>{title}</h2>
              {subtitle && <div className="dialog-subtitle">{subtitle}</div>}
            </div>
            <button type="button" className="icon-button" aria-label="Close" onClick={onClose}>
              ×
            </button>
          </header>
          <div className="dialog-body">{children}</div>
        </div>
      )}
    </dialog>
  );
}

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  error?: ReactNode;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmDialog({ open, title, message, confirmLabel, danger, busy, error, onConfirm, onClose }: ConfirmDialogProps) {
  return (
    <Dialog open={open} title={title} onClose={onClose} size="small">
      <div className="stack">
        <div>{message}</div>
        {error}
        <div className="form-actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={danger ? 'button button-danger' : 'button button-primary'}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Wait…' : confirmLabel}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
