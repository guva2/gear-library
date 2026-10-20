import { useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "./api";
import { useAuth } from "./auth";
import { FormErrors, unreachable } from "./forms";
import HealthStatus from "./HealthStatus";

/** The logged-out pages (login, register, not found): one centered panel, no sidebar. */
export function PublicLayout() {
  return (
    <main className="public">
      <div className="panel">
        <h1 className="brand">Gear Library</h1>
        <Outlet />
      </div>
    </main>
  );
}

interface Page {
  to: string;
  label: string;
  /** The paths, with everything under them, where the sidebar marks this page. */
  paths: string[];
}

const PAGES: Page[] = [
  { to: "/", label: "Discover", paths: ["/"] },
  { to: "/manage", label: "Manage", paths: ["/manage", "/inventories"] },
  { to: "/loans", label: "Loans", paths: ["/loans"] },
  { to: "/connections", label: "Connections", paths: ["/connections"] },
];

function isUnder(pathname: string, path: string): boolean {
  if (path === "/") return pathname === "/";
  return pathname === path || pathname.startsWith(`${path}/`);
}

/** Every signed-in page: the sidebar, then the page. */
export function AppLayout() {
  const { pathname } = useLocation();
  return (
    <div className="app">
      <aside className="sidebar">
        <h1 className="brand">Gear Library</h1>
        <nav aria-label="Main">
          <ul>
            {PAGES.map((page) => (
              <li key={page.to}>
                <Link
                  to={page.to}
                  aria-current={
                    page.paths.some((path) => isUnder(pathname, path)) ? "page" : undefined
                  }
                >
                  {page.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <SidebarFooter />
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}

function SidebarFooter() {
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

  return (
    <footer className="sidebar-footer">
      {user && <p>Signed in as {`${user.first_name} ${user.last_name}`}</p>}
      <FormErrors errors={errors} />
      <button type="button" onClick={logOut}>
        Log out
      </button>
      <HealthStatus />
    </footer>
  );
}
