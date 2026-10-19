import { useEffect, useState } from "react";

export type Loaded<T> =
  | { status: "loading" }
  | { status: "ok"; data: T }
  | { status: "error"; error: unknown };

/**
 * Runs `load` on mount and again on each call of the returned `reload`. A reload keeps the
 * previous result on screen until the new one arrives.
 */
export function useLoad<T>(load: (signal: AbortSignal) => Promise<T>): [Loaded<T>, () => void] {
  const [state, setState] = useState<Loaded<T>>({ status: "loading" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: "ok", data });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setState({ status: "error", error });
      },
    );
    return () => controller.abort();
    // `load` is read from the render that changed `version`, so it is current.
  }, [version]);

  return [state, () => setVersion((v) => v + 1)];
}
