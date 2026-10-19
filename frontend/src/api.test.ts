import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Api = typeof import("./api");

function setCookie(value: string) {
  document.cookie = `csrftoken=${value}; path=/`;
}

function clearCookie() {
  document.cookie = "csrftoken=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

type FetchMock = { mock: { calls: unknown[][] } };

function stubFetch() {
  const fetchMock = vi.fn(
    async (_url: string, _init?: RequestInit) => new Response(null, { status: 204 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function callsTo(fetchMock: FetchMock, path: string) {
  return fetchMock.mock.calls.filter(([url]) => url === path) as [string, RequestInit][];
}

function headersOf(init: RequestInit) {
  return new Headers(init.headers);
}

describe("apiFetch", () => {
  let api: Api;

  // A fresh module per test, so each starts without a CSRF cookie request in flight.
  beforeEach(async () => {
    vi.resetModules();
    api = await import("./api");
    setCookie("token-one");
  });

  afterEach(clearCookie);

  it.each(["POST", "PATCH", "DELETE"])("sends the CSRF token on %s", async (method) => {
    const fetchMock = stubFetch();

    await api.apiFetch("/api/thing/", { method });

    const [[, init]] = callsTo(fetchMock, "/api/thing/");
    expect(init.method).toBe(method);
    expect(headersOf(init).get("X-CSRFToken")).toBe("token-one");
  });

  it("does not send the CSRF token on GET", async () => {
    const fetchMock = stubFetch();

    await api.apiFetch("/api/thing/");

    const [[, init]] = callsTo(fetchMock, "/api/thing/");
    expect(headersOf(init).has("X-CSRFToken")).toBe(false);
  });

  it("reads the cookie again on every call", async () => {
    const fetchMock = stubFetch();

    await api.apiFetch("/api/auth/login/", { method: "POST" });
    setCookie("token-two");
    await api.apiFetch("/api/auth/logout/", { method: "POST" });

    expect(headersOf(callsTo(fetchMock, "/api/auth/login/")[0][1]).get("X-CSRFToken")).toBe(
      "token-one",
    );
    expect(headersOf(callsTo(fetchMock, "/api/auth/logout/")[0][1]).get("X-CSRFToken")).toBe(
      "token-two",
    );
  });

  it("requests the CSRF cookie once, before the first unsafe request", async () => {
    const fetchMock = stubFetch();

    await api.ensureCsrfCookie();
    await api.apiFetch("/api/thing/", { method: "POST" });
    await api.apiFetch("/api/thing/", { method: "DELETE" });

    expect(callsTo(fetchMock, "/api/auth/csrf/")).toHaveLength(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/csrf/");
  });

  it("waits for the CSRF cookie before an unsafe request", async () => {
    let finishCsrf!: () => void;
    const fetchMock = vi.fn((url: string) =>
      url === "/api/auth/csrf/"
        ? new Promise<Response>((resolve) => {
            finishCsrf = () => resolve(new Response(null, { status: 204 }));
          })
        : Promise.resolve(new Response(null, { status: 204 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    const request = api.apiFetch("/api/thing/", { method: "POST" });
    await new Promise((r) => setTimeout(r, 0));
    expect(callsTo(fetchMock, "/api/thing/")).toHaveLength(0);
    finishCsrf();
    await request;

    expect(callsTo(fetchMock, "/api/thing/")).toHaveLength(1);
  });

  it("asks for the CSRF cookie again after a failed attempt", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockImplementation(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.apiFetch("/api/thing/", { method: "POST" })).rejects.toThrow();
    await api.apiFetch("/api/thing/", { method: "POST" });

    expect(callsTo(fetchMock, "/api/auth/csrf/")).toHaveLength(2);
    expect(callsTo(fetchMock, "/api/thing/")).toHaveLength(1);
  });

  it("sends a body as JSON", async () => {
    const fetchMock = stubFetch();

    await api.apiFetch("/api/thing/", { method: "POST", body: { a: 1 } });

    const [[, init]] = callsTo(fetchMock, "/api/thing/");
    expect(init.body).toBe('{"a":1}');
    expect(headersOf(init).get("Content-Type")).toBe("application/json");
  });
});

describe("readErrors", () => {
  it("keeps field errors and gathers form-wide ones under `form`", async () => {
    const { readErrors } = await import("./api");
    const response = new Response(
      JSON.stringify({ phone_number: ["Bad number."], non_field_errors: ["Wrong."] }),
      { status: 400 },
    );

    expect(await readErrors(response)).toEqual({
      phone_number: ["Bad number."],
      form: ["Wrong."],
    });
  });

  it("uses `detail` as a form error", async () => {
    const { readErrors } = await import("./api");
    const response = new Response(JSON.stringify({ detail: "You are already logged in." }), {
      status: 403,
    });

    expect(await readErrors(response)).toEqual({ form: ["You are already logged in."] });
  });

  it("falls back to a generic message for a body that is not an error report", async () => {
    const { readErrors } = await import("./api");

    expect(await readErrors(new Response("<html></html>", { status: 502 }))).toEqual({
      form: ["Something went wrong. Try again."],
    });
  });
});
