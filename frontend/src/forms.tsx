import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { apiFetch, readErrors, type FieldErrors } from "./api";

interface FieldProps {
  name: string;
  label: string;
  errors: FieldErrors;
  /** Defaults to `name`. Set it when two forms on one page have a field with this name. */
  id?: string;
  type?: string;
  autoComplete?: string;
  required?: boolean;
  defaultValue?: string;
}

export function Field({
  name,
  label,
  errors,
  id = name,
  type = "text",
  autoComplete,
  required = true,
  defaultValue,
}: FieldProps) {
  const messages = errors[name];
  const errorId = `${id}-error`;
  return (
    <p>
      <label htmlFor={id}>{label}</label>{" "}
      <input
        id={id}
        name={name}
        type={type}
        autoComplete={autoComplete}
        defaultValue={defaultValue}
        required={required}
        aria-invalid={messages ? true : undefined}
        aria-describedby={messages ? errorId : undefined}
      />
      {messages && <span id={errorId}> {messages.join(" ")}</span>}
    </p>
  );
}

/** Returns a ref for the form; each new `errors` value moves focus to its first invalid field. */
export function useFocusFirstInvalid(errors: FieldErrors) {
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [errors]);
  return form;
}

const submitIds = new WeakMap<FieldErrors, number>();
let lastSubmitId = 0;

/** Each new `errors` object remounts the alert, so a repeated message is announced again. */
export function FormErrors({ errors }: { errors: FieldErrors }) {
  if (!errors.form) return null;
  if (!submitIds.has(errors)) submitIds.set(errors, ++lastSubmitId);
  return (
    <p key={submitIds.get(errors)} role="alert" tabIndex={-1}>
      {errors.form.join(" ")}
    </p>
  );
}

export const unreachable = (): FieldErrors => ({ form: ["Could not reach the backend."] });

interface ConfirmationProps {
  message: ReactNode;
  confirm: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Takes focus when it appears, so a screen reader reads the question. */
export function Confirmation({ message, confirm, onConfirm, onCancel }: ConfirmationProps) {
  const ref = useRef<HTMLParagraphElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <p ref={ref} tabIndex={-1}>
      {message}{" "}
      <button type="button" onClick={onConfirm}>
        {confirm}
      </button>{" "}
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
    </p>
  );
}

/**
 * Orders the changes sent from one page. Each call marks a new change as the latest and
 * returns a check that stays true until the next call, so a reply to an older change can
 * leave out its messages instead of showing them over the newer one's.
 */
export function useLatestChange(): () => () => boolean {
  const latest = useRef(0);
  return useCallback(() => {
    const id = ++latest.current;
    return () => latest.current === id;
  }, []);
}

/**
 * Holds a page's errors and `change`, which sends a change and reloads either way: a refusal
 * may come from a change someone else made, so the page shows the current state with it.
 * `reload` is told whether the reply is to the page's latest change. `begin` clears the
 * errors and starts a change for a form that sends its own request; it returns whether that
 * change is still the page's latest. A reply to an older change sets no errors, but still
 * reloads, since the change may have gone through. `sent` counts the changes started, by
 * `change` or `begin`, and goes up by one at each start.
 */
export function useChange(reload: (latest: boolean) => void) {
  const [errors, setErrors] = useState<FieldErrors>({});
  const [sent, setSent] = useState(0);
  const start = useLatestChange();

  function begin() {
    setErrors({});
    setSent((count) => count + 1);
    return start();
  }

  async function change(path: string, method: "POST" | "DELETE", body?: unknown) {
    const isLatest = begin();
    try {
      const response = await apiFetch(path, { method, body });
      if (!response.ok) {
        const errors = await readErrors(response, []);
        if (isLatest()) setErrors(errors);
      }
      reload(isLatest());
    } catch {
      if (isLatest()) setErrors(unreachable());
    }
  }

  return { errors, setErrors, change, begin, sent };
}
