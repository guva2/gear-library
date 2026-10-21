import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useChange, useLatestChange } from "./forms";
import { empty, fakeBackend, held, json } from "./test-backend";

describe("useLatestChange", () => {
  it("reports only the change started last as the latest", () => {
    const { result } = renderHook(() => useLatestChange());

    const first = result.current();
    expect(first()).toBe(true);
    const second = result.current();

    expect(first()).toBe(false);
    expect(second()).toBe(true);
  });
});

describe("useChange", () => {
  it("ignores the errors of a reply that arrives after a later change", async () => {
    const first = held();
    fakeBackend({ "POST /api/first/": first.route, "POST /api/second/": empty(204) });
    const reload = vi.fn();
    const { result } = renderHook(() => useChange(reload));

    let firstDone: Promise<void> = Promise.resolve();
    act(() => {
      firstDone = result.current.change("/api/first/", "POST");
    });
    await act(() => result.current.change("/api/second/", "POST"));
    await act(async () => {
      first.respond(json(409, { detail: "First failed." }));
      await firstDone;
    });

    expect(result.current.errors).toEqual({});
  });

  it("still reloads after a reply to an older change, which may have changed the data", async () => {
    const first = held();
    fakeBackend({ "POST /api/first/": first.route, "POST /api/second/": empty(204) });
    const reload = vi.fn();
    const { result } = renderHook(() => useChange(reload));

    let firstDone: Promise<void> = Promise.resolve();
    act(() => {
      firstDone = result.current.change("/api/first/", "POST");
    });
    await act(() => result.current.change("/api/second/", "POST"));
    expect(reload).toHaveBeenCalledTimes(1);
    await act(async () => {
      first.respond(empty(204));
      await firstDone;
    });

    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("ignores a lost connection on an older change", async () => {
    let fail: (error: Error) => void = () => {};
    fakeBackend({
      "POST /api/first/": () => new Promise<Response>((_, reject) => (fail = reject)),
      "POST /api/second/": json(409, { detail: "Second failed." }),
    });
    const { result } = renderHook(() => useChange(vi.fn()));

    let firstDone: Promise<void> = Promise.resolve();
    act(() => {
      firstDone = result.current.change("/api/first/", "POST");
    });
    await act(() => result.current.change("/api/second/", "POST"));
    await act(async () => {
      fail(new TypeError("Failed to fetch"));
      await firstDone;
    });

    await waitFor(() => expect(result.current.errors).toEqual({ form: ["Second failed."] }));
  });
});
