import { vi } from "vitest";

type Handler = (init: RequestInit) => Response;
/** A route may also answer later, to hold a request in flight. */
type Route = (init: RequestInit) => Response | Promise<Response>;

export const ADA = {
  id: 1,
  phone_number: "5552234567",
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

/** A route that answers only when `respond` is called, to hold a request in flight. */
export function held() {
  let respond: (handler: Handler) => void = () => {};
  const route: Route = (init) =>
    new Promise<Response>((resolve) => (respond = (handler) => resolve(handler(init))));
  return { route, respond: (handler: Handler) => respond(handler) };
}

// A signed-in user with no inventories, invites, connections, requests, items, loans or
// items to discover.
const DEFAULTS: Record<string, Handler> = {
  "GET /api/auth/csrf/": empty(204),
  "GET /api/inventories/": json(200, []),
  "GET /api/invites/": json(200, []),
  "GET /api/connections/": json(200, []),
  "GET /api/connections/requests/": json(200, { received: [], sent: [] }),
  "GET /api/items/": json(200, []),
  "GET /api/borrowing/": json(200, []),
  "GET /api/discover/": json(200, []),
  "GET /api/lending/": json(200, []),
};

/**
 * Stubs `fetch` with handlers keyed by `"METHOD /path/"`. A request with no handler
 * rejects, so the test fails on whatever the page shows for an unreachable backend.
 */
export function fakeBackend(routes: Record<string, Route>) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${url}`;
    const handler = routes[key] ?? DEFAULTS[key];
    if (!handler) throw new TypeError(`No fake response for ${key}`);
    return handler(init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    /** Every request's key, in the order sent. */
    keys: () => fetchMock.mock.calls.map(([url, init]) => `${init?.method ?? "GET"} ${url}`),
    requests: (key: string) =>
      fetchMock.mock.calls
        .filter(([url, init]) => `${init?.method ?? "GET"} ${url}` === key)
        .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : undefined)),
  };
}
