import { useEffect, useState } from "react";

type Health = "loading" | "ok" | "database-unavailable" | "unreachable";

const MESSAGES: Record<Health, string> = {
  loading: "Checking the backend…",
  ok: "Backend and database are ok.",
  "database-unavailable": "The backend is up, but the database is unavailable.",
  unreachable: "Could not reach the backend.",
};

async function checkHealth(signal: AbortSignal): Promise<Health> {
  const response = await fetch("/api/health/", { signal });
  const body = await response.json().catch(() => null);
  if (response.status === 200 && body?.database === "ok") {
    return "ok";
  }
  if (response.status === 503 && body?.database === "unavailable") {
    return "database-unavailable";
  }
  return "unreachable";
}

export default function App() {
  const [health, setHealth] = useState<Health>("loading");

  useEffect(() => {
    const controller = new AbortController();
    checkHealth(controller.signal)
      .catch(() => "unreachable" as const)
      .then((result) => {
        if (!controller.signal.aborted) {
          setHealth(result);
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <main>
      <h1>Gear Library</h1>
      <p role="status">{MESSAGES[health]}</p>
    </main>
  );
}
