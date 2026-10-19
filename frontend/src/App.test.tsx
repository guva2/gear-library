import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

// React 18+ does not warn about a state update after unmount, so record the setters.
const stateSetters = vi.hoisted(() => [] as ReturnType<typeof vi.fn>[]);

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useState: (initial: unknown) => {
      const [value, set] = actual.useState(initial);
      // One wrapper per hook instance, so the setter keeps React's stable identity.
      const setter = actual.useRef<ReturnType<typeof vi.fn> | null>(null);
      if (setter.current === null) {
        setter.current = vi.fn(set);
        stateSetters.push(setter.current);
      }
      return [value, setter.current];
    },
  };
});

function respondWith(status: number, body: string) {
  const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("health page", () => {
  it("shows ok once the backend and database answer", async () => {
    const fetchMock = respondWith(200, JSON.stringify({ status: "ok", database: "ok" }));

    render(<App />);

    expect(screen.getByRole("status")).toHaveTextContent("Checking");
    expect(await screen.findByText("Backend and database are ok.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/health/", expect.anything());
  });

  it("shows the database as unavailable on a 503 from the backend", async () => {
    respondWith(503, JSON.stringify({ status: "error", database: "unavailable" }));

    render(<App />);

    expect(
      await screen.findByText("The backend is up, but the database is unavailable."),
    ).toBeInTheDocument();
  });

  it("shows an error when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<App />);

    expect(await screen.findByText("Could not reach the backend.")).toBeInTheDocument();
  });

  // The Vite proxy answers with a non-JSON error when the backend is down.
  it("shows an error for a response that is not a health report", async () => {
    respondWith(502, "");

    render(<App />);

    expect(await screen.findByText("Could not reach the backend.")).toBeInTheDocument();
  });

  // Vite's SPA fallback answers an unproxied path with 200 and HTML.
  it("shows an error for a 200 that is not a health report", async () => {
    respondWith(200, "<!doctype html><html></html>");

    render(<App />);

    expect(await screen.findByText("Could not reach the backend.")).toBeInTheDocument();
  });

  it("does not set state after unmounting before the response", async () => {
    let resolve!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((r) => (resolve = r))));
    stateSetters.length = 0;

    const { unmount } = render(<App />);
    unmount();
    resolve(new Response(JSON.stringify({ status: "ok", database: "ok" }), { status: 200 }));
    await new Promise((r) => setTimeout(r, 20));

    expect(stateSetters.length).toBeGreaterThan(0);
    for (const setter of stateSetters) expect(setter).not.toHaveBeenCalled();
  });
});
