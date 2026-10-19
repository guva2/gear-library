import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { useAuth, type FromState, type User } from "../auth";
import { Field, FormErrors, unreachable, useFocusFirstInvalid } from "../forms";

const FIELDS = ["phone_number", "first_name", "last_name", "password"];

export default function RegisterPage() {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [errors, setErrors] = useState<FieldErrors>({});
  const formRef = useFocusFirstInvalid(errors);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const response = await apiFetch("/api/auth/register/", {
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
      setErrors(unreachable());
    }
  }

  return (
    <>
      <h2>Create an account</h2>
      <form ref={formRef} onSubmit={submit} noValidate>
        <FormErrors errors={errors} />
        <Field
          name="phone_number"
          label="Phone number"
          type="tel"
          autoComplete="tel"
          errors={errors}
        />
        <Field name="first_name" label="First name" autoComplete="given-name" errors={errors} />
        <Field name="last_name" label="Last name" autoComplete="family-name" errors={errors} />
        <Field
          name="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          errors={errors}
        />
        <button type="submit">Create account</button>
      </form>
      <p>
        Already have an account?{" "}
        <Link to="/login" state={location.state}>
          Log in
        </Link>
      </p>
    </>
  );
}
