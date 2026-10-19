const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const GENERIC_ERROR = "Something went wrong. Try again.";

export type FieldErrors = Record<string, string[]>;

let csrfCookie: Promise<void> | null = null;

/** Requests the `csrftoken` cookie. Later calls share the first request until it fails. */
export function ensureCsrfCookie(): Promise<void> {
  csrfCookie ??= fetch("/api/auth/csrf/", { credentials: "same-origin" }).then(
    (response) => {
      if (!response.ok) throw new Error(`CSRF cookie request failed: ${response.status}`);
    },
  );
  csrfCookie.catch(() => {
    csrfCookie = null;
  });
  return csrfCookie;
}

function readCookie(name: string): string | null {
  for (const part of document.cookie.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return decodeURIComponent(value.join("="));
  }
  return null;
}

interface ApiOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch(path: string, options: ApiOptions = {}): Promise<Response> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (UNSAFE_METHODS.has(method)) {
    await ensureCsrfCookie();
    // Read at call time: Django replaces the token at login.
    const token = readCookie("csrftoken");
    if (token) headers.set("X-CSRFToken", token);
  }
  return fetch(path, {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    credentials: "same-origin",
    signal: options.signal,
  });
}

/**
 * Reads a DRF error body. Field errors keep their field name; `non_field_errors` and
 * `detail` go under `form`.
 */
export async function readErrors(response: Response): Promise<FieldErrors> {
  const body: unknown = await response.json().catch(() => null);
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { form: [GENERIC_ERROR] };
  }
  const errors: FieldErrors = {};
  for (const [key, value] of Object.entries(body)) {
    const messages = (Array.isArray(value) ? value : [value]).filter(
      (message): message is string => typeof message === "string",
    );
    if (messages.length === 0) continue;
    const field = key === "non_field_errors" || key === "detail" ? "form" : key;
    errors[field] = [...(errors[field] ?? []), ...messages];
  }
  return Object.keys(errors).length > 0 ? errors : { form: [GENERIC_ERROR] };
}
