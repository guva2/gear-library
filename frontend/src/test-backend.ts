import { vi } from "vitest";

type Handler = (init: RequestInit) => Response;

export const ADA = {
  id: 1,
  phone_number: "5551234567",
  first_name: "Ada",
  last_name: "Lovelace",
};

export function json(status: number, body: unknown): Handler {
  return () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
}

export function empty(status: number): Handler {
  return () => new Response(null, { status });
}

// A signed-in user with no inventories, invites, connections, requests or items.
const DEFAULTS: Record<string, Handler> = {
  "GET /api/auth/csrf/": empty(204),
  "GET /api/health/": json(200, { status: "ok", database: "ok" }),
  "GET /api/inventories/": json(200, []),
  "GET /api/invites/": json(200, []),
  "GET /api/connections/": json(200, []),
  "GET /api/connections/requests/": json(200, { received: [], sent: [] }),
  "GET /api/items/": json(200, []),
};

/**
 * Stubs `fetch` with handlers keyed by `"METHOD /path/"`. A request with no handler
 * rejects, so the test fails on whatever the page shows for an unreachable backend.
 */
export function fakeBackend(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${url}`;
    const handler = routes[key] ?? DEFAULTS[key];
    if (!handler) throw new TypeError(`No fake response for ${key}`);
    return handler(init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    requests: (key: string) =>
      fetchMock.mock.calls
        .filter(([url, init]) => `${init?.method ?? "GET"} ${url}` === key)
        .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : undefined)),
  };
}
