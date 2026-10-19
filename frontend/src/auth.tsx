import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { apiFetch } from "./api";

export interface User {
  id: number;
  phone_number: string;
  first_name: string;
  last_name: string;
}

interface AuthState {
  /** `undefined` until the session has been checked, `null` when logged out. */
  user: User | null | undefined;
  setUser: (user: User | null) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  return <AuthContext.Provider value={{ user, setUser }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const auth = useContext(AuthContext);
  if (auth === null) throw new Error("useAuth needs an AuthProvider");
  return auth;
}

/** The location a guarded page sends to `/login`, so login can return there. */
export interface FromState {
  from?: { pathname: string; search: string; hash: string };
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, setUser } = useAuth();
  const location = useLocation();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (user !== undefined) return;
    const controller = new AbortController();
    apiFetch("/api/auth/me/", { signal: controller.signal })
      .then(async (response) => {
        if (response.status === 200) return (await response.json()) as User;
        if (response.status === 403) return null;
        throw new Error(`Session check failed: ${response.status}`);
      })
      .then(
        (result) => {
          if (!controller.signal.aborted) setUser(result);
        },
        () => {
          if (!controller.signal.aborted) setFailed(true);
        },
      );
    return () => controller.abort();
  }, [user, setUser]);

  if (failed) return <p role="alert">Could not reach the backend.</p>;
  if (user === undefined) return <p>Loading…</p>;
  if (user === null) {
    const state: FromState = { from: location };
    return <Navigate to="/login" replace state={state} />;
  }
  return children;
}
