import { useId } from "react";
import type { ComponentPropsWithRef, ReactNode } from "react";

export function Button({
  busy = false,
  children,
  disabled,
  type = "button",
  ...props
}: ComponentPropsWithRef<"button"> & { busy?: boolean }) {
  return (
    <button {...props} type={type} disabled={disabled || busy} aria-busy={busy}>
      {children}
    </button>
  );
}

export function Field({
  label,
  help,
  error,
  id,
  ...props
}: ComponentPropsWithRef<"input"> & {
  label: string;
  help?: string;
  error?: string;
}) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const describedBy =
    [
      props["aria-describedby"],
      help ? `${inputId}-help` : null,
      error ? `${inputId}-error` : null,
    ]
      .filter(Boolean)
      .join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={inputId}>{label}</label>
      <input
        {...props}
        id={inputId}
        aria-describedby={describedBy}
        aria-invalid={error ? true : props["aria-invalid"]}
      />
      {help && <small id={`${inputId}-help`}>{help}</small>}
      {error && (
        <small id={`${inputId}-error`} className="error-text">
          {error}
        </small>
      )}
    </div>
  );
}

export function Feedback({ children }: { children: ReactNode }) {
  return (
    <p role="status" aria-live="polite" aria-atomic="true" className="feedback">
      {children}
    </p>
  );
}
export function Loading({ children = "Loading…" }: { children?: ReactNode }) {
  return (
    <p role="status" aria-live="polite" aria-atomic="true" className="feedback">
      {children}
    </p>
  );
}
export function ErrorFeedback({
  children,
  retry,
}: {
  children: ReactNode;
  retry?: () => void;
}) {
  return (
    <div role="alert" aria-atomic="true" className="error-text">
      <p>{children}</p>
      {retry && <Button onClick={retry}>Try again</Button>}
    </div>
  );
}
