import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

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
});
