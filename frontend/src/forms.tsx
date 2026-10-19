import { useEffect, useRef } from "react";
import type { FieldErrors } from "./api";

interface FieldProps {
  name: string;
  label: string;
  errors: FieldErrors;
  type?: string;
  autoComplete?: string;
}

export function Field({ name, label, errors, type = "text", autoComplete }: FieldProps) {
  const messages = errors[name];
  const errorId = `${name}-error`;
  return (
    <p>
      <label htmlFor={name}>{label}</label>{" "}
      <input
        id={name}
        name={name}
        type={type}
        autoComplete={autoComplete}
        required
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

export function FormErrors({ errors }: { errors: FieldErrors }) {
  return errors.form ? <p role="alert">{errors.form.join(" ")}</p> : null;
}

export const UNREACHABLE: FieldErrors = { form: ["Could not reach the backend."] };
