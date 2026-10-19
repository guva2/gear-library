import { useState } from "react";
import { useNavigate } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { useAuth } from "../auth";
import { FormErrors, UNREACHABLE } from "../forms";
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
        setErrors(await readErrors(response));
        return;
      }
      setUser(null);
      navigate("/login", { replace: true });
    } catch {
      setErrors(UNREACHABLE);
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
