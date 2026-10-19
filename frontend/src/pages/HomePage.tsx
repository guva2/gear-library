import { useState } from "react";
import { useNavigate } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { useAuth } from "../auth";
import { FormErrors, unreachable } from "../forms";
import HealthStatus from "../HealthStatus";
import { formatPhoneNumber } from "../phone";

export default function HomePage() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const [errors, setErrors] = useState<FieldErrors>({});

  async function logOut() {
    try {
      const response = await apiFetch("/api/auth/logout/", { method: "POST" });
      if (!response.ok) {
        const errors = await readErrors(response, []);
        // A 403 that is not a CSRF failure means the session is already gone.
        const csrfFailed = errors.form?.some((message) => message.startsWith("CSRF"));
        if (response.status !== 403 || csrfFailed) {
          setErrors(errors);
          return;
        }
      }
      setUser(null);
      navigate("/login", { replace: true });
    } catch {
      setErrors(unreachable());
    }
  }

  if (!user) return null;
  return (
    <>
      <p>Signed in as {`${user.first_name} ${user.last_name}`}</p>
      <p>{formatPhoneNumber(user.phone_number)}</p>
      <FormErrors errors={errors} />
      <button type="button" onClick={logOut}>
        Log out
      </button>
      <HealthStatus />
    </>
  );
}
