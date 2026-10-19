import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { useAuth, type FromState, type User } from "../auth";
import { Field, FormErrors, UNREACHABLE, useFocusFirstInvalid } from "../forms";

const FIELDS = ["phone_number", "password"];

export default function LoginPage() {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [errors, setErrors] = useState<FieldErrors>({});
  const formRef = useFocusFirstInvalid(errors);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const response = await apiFetch("/api/auth/login/", {
        method: "POST",
        body: Object.fromEntries(FIELDS.map((field) => [field, form.get(field)])),
      });
      if (!response.ok) {
        setErrors(await readErrors(response, FIELDS));
        return;
      }
      setUser((await response.json()) as User);
      navigate((location.state as FromState | null)?.from ?? "/", { replace: true });
    } catch {
      setErrors(UNREACHABLE);
    }
  }

  return (
    <>
      <h2>Log in</h2>
      <form ref={formRef} onSubmit={submit} noValidate>
        <FormErrors errors={errors} />
        <Field
          name="phone_number"
          label="Phone number"
          type="tel"
          autoComplete="tel"
          errors={errors}
        />
        <Field
          name="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          errors={errors}
        />
        <button type="submit">Log in</button>
      </form>
      <p>
        New here?{" "}
        <Link to="/register" state={location.state}>
          Create an account
        </Link>
      </p>
    </>
  );
}
