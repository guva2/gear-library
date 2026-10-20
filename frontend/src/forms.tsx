import { useEffect, useRef, type ReactNode } from "react";
import type { FieldErrors } from "./api";

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
