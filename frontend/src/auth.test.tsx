import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it } from "vitest";
import { AuthProvider, RequireAuth } from "./auth";
import LoginPage from "./pages/LoginPage";
import { ADA, fakeBackend, json } from "./test-backend";

function Where() {
  const location = useLocation();
  return <p>At {location.pathname + location.search}</p>;
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/somewhere"
            element={
              <RequireAuth>
                <Where />
              </RequireAuth>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("RequireAuth", () => {
  it("shows the page to a logged-in user", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA) });

    renderAt("/somewhere");

    expect(await screen.findByText("At /somewhere")).toBeInTheDocument();
  });

  it("sends an anonymous user to log in, then back to the page they asked for", async () => {
    const backend = fakeBackend({
      "GET /api/auth/me/": json(403, { detail: "Not logged in." }),
      "POST /api/auth/login/": json(200, ADA),
    });

    renderAt("/somewhere?tab=2");

    fireEvent.change(await screen.findByLabelText("Phone number"), {
      target: { value: "(555) 123-4567" },
    });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByText("At /somewhere?tab=2")).toBeInTheDocument();
    expect(backend.requests("POST /api/auth/login/")).toEqual([
      { phone_number: "(555) 123-4567", password: "pw" },
    ]);
  });

  it("shows an error when the session check fails", async () => {
    fakeBackend({ "GET /api/auth/me/": json(502, {}) });

    renderAt("/somewhere");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the backend.");
    expect(screen.queryByText(/^At /)).not.toBeInTheDocument();
  });
});
