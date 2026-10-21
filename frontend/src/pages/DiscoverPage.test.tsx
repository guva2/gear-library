import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DiscoverItem } from "../items";
import { ADA, empty, fakeBackend, json } from "../test-backend";
import { renderAt } from "../test-render";

type Routes = Parameters<typeof fakeBackend>[0];

const CAMPING = { id: 8, name: "Camping Crew" };
const CLIMBING = { id: 7, name: "Climbing Club" };
const BOB = { first_name: "Bob", last_name: "Stone" };

const ROPE: DiscoverItem = {
  id: 20,
  name: "Rope",
  description: "60 m dynamic",
  owner: BOB,
  loan_status: "available",
  borrowed_by_me: false,
  inventories: [CAMPING, CLIMBING],
};
const AXE: DiscoverItem = {
  ...ROPE,
  id: 21,
  name: "Axe",
  description: "",
  inventories: [CLIMBING],
};
const TENT: DiscoverItem = {
  ...AXE,
  id: 22,
  name: "Tent",
  loan_status: "requested",
  borrowed_by_me: true,
};
const STOVE: DiscoverItem = { ...AXE, id: 23, name: "Stove", loan_status: "on_loan" };

interface State {
  items: DiscoverItem[];
}

/** A backend whose item list changes as the page acts, so a reload shows the new state. */
function liveBackend(routes: (state: State) => Routes = () => ({})) {
  const state: State = { items: [AXE, ROPE, TENT, STOVE] };
  return fakeBackend({
    "GET /api/auth/me/": json(200, ADA),
    "GET /api/discover/": () => json(200, state.items)({}),
    ...routes(state),
  });
}

async function open(path = "/") {
  const page = renderAt(path);
  await screen.findByRole("heading", { name: "Discover" });
  await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
  return page;
}

function card(name: string) {
  const found = screen
    .getAllByRole("listitem")
    .find((item) => within(item).queryByRole("heading", { name }));
  if (!found) throw new Error(`No card ${name}`);
  return found;
}

describe("discover", () => {
  it("shows one card per item with its owner and inventories", async () => {
    liveBackend();

    await open();

    const rope = card("Rope");
    expect(within(rope).getByText("60 m dynamic")).toBeInTheDocument();
    expect(within(rope).getByText("Owned by Bob Stone")).toBeInTheDocument();
    expect(within(rope).getByText("In Camping Crew, Climbing Club")).toBeInTheDocument();
    expect(within(rope).getByText("Available")).toBeInTheDocument();
    expect(rope).not.toHaveClass("unavailable");
  });

  it.each([
    ["Tent", "Waiting for approval"],
    ["Stove", "On loan"],
  ])("greys out %s with its status and no Ask to borrow", async (name, status) => {
    liveBackend();

    await open();

    expect(card(name)).toHaveClass("unavailable");
    expect(within(card(name)).getByText(status)).toBeInTheDocument();
    expect(within(card(name)).queryByRole("button")).toBeNull();
  });

  it("says when the caller has borrowed the item", async () => {
    liveBackend((state) => {
      state.items = [{ ...TENT, loan_status: "on_loan" }];
      return {};
    });

    await open();

    expect(within(card("Tent")).getByText("Borrowed by you")).toBeInTheDocument();
  });

  it("requests an item listed in one inventory through it, then reloads", async () => {
    const backend = liveBackend((state) => ({
      "POST /api/inventories/7/items/21/borrow/": () => {
        state.items = [{ ...AXE, loan_status: "requested", borrowed_by_me: true }];
        return empty(204)({});
      },
    }));
    await open();

    const button = within(card("Axe")).getByRole("button", { name: "Ask to borrow Axe" });
    expect(button).toHaveTextContent(/^Ask to borrow$/);
    fireEvent.click(button);

    expect(await within(card("Axe")).findByText("Waiting for approval")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(card("Axe")).getByRole("heading", { name: "Axe" })).toHaveFocus(),
    );
    expect(backend.requests("POST /api/inventories/7/items/21/borrow/")).toEqual([undefined]);
  });

  it("asks which inventory to request through when the item is in several", async () => {
    const backend = liveBackend(() => ({
      "POST /api/inventories/7/items/20/borrow/": empty(204),
    }));
    await open();

    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Ask to borrow Rope" }));
    const through = within(card("Rope")).getByLabelText("Borrow through");
    expect(through).toHaveValue("8");
    expect(backend.requests("POST /api/inventories/8/items/20/borrow/")).toHaveLength(0);

    fireEvent.change(through, { target: { value: "7" } });
    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Send request" }));

    await waitFor(() =>
      expect(backend.requests("POST /api/inventories/7/items/20/borrow/")).toHaveLength(1),
    );
  });

  it("moves focus to the card heading after a request sent from the inventory choice", async () => {
    liveBackend((state) => ({
      "POST /api/inventories/7/items/20/borrow/": () => {
        state.items = [{ ...ROPE, loan_status: "requested", borrowed_by_me: true }];
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Ask to borrow Rope" }));
    fireEvent.change(within(card("Rope")).getByLabelText("Borrow through"), {
      target: { value: "7" },
    });
    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Send request" }));

    expect(await within(card("Rope")).findByText("Waiting for approval")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(card("Rope")).getByRole("heading", { name: "Rope" })).toHaveFocus(),
    );
  });

  it("focuses only the card acted on when another card changes in the same reload", async () => {
    liveBackend((state) => ({
      "POST /api/inventories/7/items/21/borrow/": () => {
        state.items = [
          { ...AXE, loan_status: "requested", borrowed_by_me: true },
          { ...STOVE, loan_status: "available" },
        ];
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(within(card("Axe")).getByRole("button", { name: "Ask to borrow Axe" }));

    expect(
      await within(card("Stove")).findByRole("button", { name: "Ask to borrow Stove" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(within(card("Axe")).getByRole("heading", { name: "Axe" })).toHaveFocus(),
    );
  });

  it("focuses the page heading when the item acted on is gone after the reload", async () => {
    liveBackend((state) => ({
      "POST /api/inventories/7/items/21/borrow/": () => {
        state.items = [ROPE];
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(within(card("Axe")).getByRole("button", { name: "Ask to borrow Axe" }));

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Axe" })).toBeNull());
    await waitFor(() => expect(screen.getByRole("heading", { name: "Discover" })).toHaveFocus());
  });

  it("closes the inventory choice on Cancel without requesting", async () => {
    const backend = liveBackend();
    await open();

    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Ask to borrow Rope" }));
    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Cancel" }));

    expect(within(card("Rope")).queryByLabelText("Borrow through")).toBeNull();
    await waitFor(() =>
      expect(within(card("Rope")).getByRole("button", { name: "Ask to borrow Rope" })).toHaveFocus(),
    );
    expect(backend.requests("POST /api/inventories/8/items/20/borrow/")).toHaveLength(0);
  });

  it("shows why a request was refused and reloads", async () => {
    let loads = 0;
    liveBackend((state) => ({
      "GET /api/discover/": () => {
        loads += 1;
        return json(200, state.items)({});
      },
      "POST /api/inventories/7/items/21/borrow/": json(409, {
        detail: "This item has already been requested or is on loan.",
      }),
    }));
    await open();

    fireEvent.click(within(card("Axe")).getByRole("button", { name: "Ask to borrow Axe" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This item has already been requested or is on loan.",
    );
    await waitFor(() => expect(loads).toBe(2));
  });

  it("says so when there is nothing to borrow", async () => {
    liveBackend((state) => {
      state.items = [];
      return {};
    });

    await open();

    expect(screen.getByText(/^Nothing to borrow right now\./)).toBeInTheDocument();
  });

  it("shows an error when the items cannot be loaded", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA), "GET /api/discover/": json(500, {}) });

    renderAt("/");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the items.");
  });
});

function searchUrl(q: string) {
  return `GET /api/discover/?${new URLSearchParams({ q })}`;
}

function cardNames() {
  return screen.queryAllByRole("heading", { level: 3 }).map((heading) => heading.textContent);
}

function type(text: string) {
  fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
    target: { value: text },
  });
}

function wait(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

/** A handler that answers only when `resolve` is called, with `items`. */
function deferred(items: DiscoverItem[]) {
  let answer: () => void = () => {};
  const seen: { signal?: AbortSignal | null } = {};
  const handler = (init: RequestInit) =>
    new Promise<Response>((resolve) => {
      seen.signal = init.signal;
      answer = () => resolve(json(200, items)(init));
    });
  return { handler, resolve: () => answer(), seen };
}

describe("discover search", () => {
  beforeEach(() => {
    // The clock also follows real time, so Testing Library's waitFor still times out.
    vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["setTimeout", "clearTimeout"] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("searches 300 ms after the last keystroke, with one request, and puts it in the URL", async () => {
    const backend = liveBackend(() => ({ [searchUrl("tent")]: json(200, [TENT]) }));
    const page = await open();

    for (const text of ["t", "te", "ten", "tent"]) {
      type(text);
      wait(200);
    }
    wait(99);
    expect(backend.keys().filter((key) => key.includes("?"))).toEqual([]);
    wait(1);

    await waitFor(() => expect(cardNames()).toEqual(["Tent"]));
    expect(backend.keys().filter((key) => key.includes("?"))).toEqual([searchUrl("tent")]);
    expect(page.location()).toEqual({ path: "/?q=tent", navigation: "REPLACE" });
  });

  it("keystrokes do not move focus", async () => {
    liveBackend(() => ({ [searchUrl("tent")]: json(200, [TENT]) }));
    await open();
    const box = screen.getByRole("searchbox", { name: "Search" });
    box.focus();

    type("tent");
    wait(300);

    await waitFor(() => expect(cardNames()).toEqual(["Tent"]));
    expect(box).toHaveFocus();
  });

  it("runs the search in the URL when the page opens", async () => {
    const backend = liveBackend(() => ({ [searchUrl("tent")]: json(200, [TENT]) }));

    await open("/?q=tent");

    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("tent");
    expect(cardNames()).toEqual(["Tent"]);
    expect(backend.requests("GET /api/discover/")).toHaveLength(0);
  });

  it("ignores the reply to a search replaced by a newer one", async () => {
    const rope = deferred([ROPE]);
    liveBackend(() => ({ [searchUrl("rope")]: rope.handler, [searchUrl("axe")]: json(200, [AXE]) }));
    await open();

    type("rope");
    wait(300);
    await waitFor(() => expect(rope.seen.signal).toBeDefined());
    type("axe");
    wait(300);
    await waitFor(() => expect(cardNames()).toEqual(["Axe"]));
    expect(rope.seen.signal?.aborted).toBe(true);
    rope.resolve();

    await act(async () => {});
    expect(cardNames()).toEqual(["Axe"]);
  });

  it("does not show a cancelled search as an error", async () => {
    let started = false;
    liveBackend(() => ({
      [searchUrl("rope")]: (init) =>
        new Promise<Response>((_, reject) => {
          started = true;
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("The operation was aborted.", "AbortError")),
          );
        }),
      [searchUrl("axe")]: json(200, [AXE]),
    }));
    await open();

    type("rope");
    wait(300);
    await waitFor(() => expect(started).toBe(true));
    type("axe");
    wait(300);

    await waitFor(() => expect(cardNames()).toEqual(["Axe"]));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("returns to the full list when the box is cleared", async () => {
    const backend = liveBackend(() => ({ [searchUrl("axe")]: json(200, [AXE]) }));
    const page = await open("/?q=axe");

    type("");
    wait(300);

    await waitFor(() => expect(cardNames()).toEqual(["Axe", "Rope", "Tent", "Stove"]));
    expect(page.location().path).toBe("/");
    expect(backend.requests("GET /api/discover/")).toHaveLength(1);
  });

  it("keeps the full list for a one-letter query without asking again", async () => {
    const backend = liveBackend();
    await open();

    type("t");
    wait(300);
    await act(async () => {});

    expect(cardNames()).toEqual(["Axe", "Rope", "Tent", "Stove"]);
    expect(backend.keys().filter((key) => key.startsWith("GET /api/discover/"))).toEqual([
      "GET /api/discover/",
    ]);
  });

  it("drops a NUL in the URL's query instead of sending it", async () => {
    const backend = liveBackend(() => ({ [searchUrl("axe")]: json(200, [AXE]) }));

    await open("/?q=a%00xe");

    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("axe");
    expect(cardNames()).toEqual(["Axe"]);
    expect(backend.keys().filter((key) => key.includes("%00"))).toEqual([]);
  });

  it("drops a NUL typed or pasted into the box", async () => {
    liveBackend(() => ({ [searchUrl("axe")]: json(200, [AXE]) }));
    const page = await open();

    type("a\0xe");
    wait(300);

    await waitFor(() => expect(cardNames()).toEqual(["Axe"]));
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("axe");
    expect(page.location().path).toBe("/?q=axe");
  });

  it("counts an emoji as one character, so it lists everything without a search", async () => {
    const backend = fakeBackend({
      "GET /api/auth/me/": json(200, ADA),
      "GET /api/discover/": json(200, []),
    });

    await open(`/?${new URLSearchParams({ q: "😀" })}`);

    expect(screen.getByText(/^Nothing to borrow right now\./)).toBeInTheDocument();
    expect(backend.keys().filter((key) => key.includes("?"))).toEqual([]);
  });

  // The server strips what Python's str.strip() does: U+0085 but not U+FEFF.
  it.each([
    ["U+0085", "\u0085a", null],
    ["U+001C", "\u001ca", null],
    ["U+FEFF", "\ufeffa", "\ufeffa"],
  ])("treats %s at the ends of the query as the server does", async (_, text, sent) => {
    const backend = liveBackend(() => (sent ? { [searchUrl(sent)]: json(200, [AXE]) } : {}));

    await open(`/?${new URLSearchParams({ q: text })}`);

    const searches = backend.keys().filter((key) => key.includes("?"));
    expect(searches).toEqual(sent ? [searchUrl(sent)] : []);
  });

  it("says when nothing matches the query", async () => {
    liveBackend(() => ({ [searchUrl("xyz")]: json(200, []) }));

    await open("/?q=xyz");

    expect(screen.getByText("No items match “xyz”.")).toBeInTheDocument();
    expect(screen.queryByText(/^Nothing to borrow right now\./)).toBeNull();
  });

  it("reloads the search after a request", async () => {
    const backend = liveBackend(() => ({
      [searchUrl("axe")]: json(200, [AXE]),
      "POST /api/inventories/7/items/21/borrow/": empty(204),
    }));
    await open("/?q=axe");

    fireEvent.click(within(card("Axe")).getByRole("button", { name: "Ask to borrow Axe" }));

    await waitFor(() => expect(backend.requests(searchUrl("axe"))).toHaveLength(2));
    expect(backend.requests("GET /api/discover/")).toHaveLength(0);
  });

  it("keeps focus in the box when a search drops the item last acted on", async () => {
    liveBackend((state) => ({
      [searchUrl("rope")]: json(200, [ROPE]),
      "POST /api/inventories/7/items/21/borrow/": () => {
        state.items = [{ ...AXE, loan_status: "requested", borrowed_by_me: true }, ROPE];
        return empty(204)({});
      },
    }));
    await open();
    fireEvent.click(within(card("Axe")).getByRole("button", { name: "Ask to borrow Axe" }));
    await waitFor(() =>
      expect(within(card("Axe")).getByRole("heading", { name: "Axe" })).toHaveFocus(),
    );
    const box = screen.getByRole("searchbox", { name: "Search" });
    box.focus();

    type("rope");
    wait(300);

    await waitFor(() => expect(cardNames()).toEqual(["Rope"]));
    await act(async () => {});
    expect(box).toHaveFocus();
  });

  it("clears the box when the Discover link is followed", async () => {
    liveBackend(() => ({ [searchUrl("axe")]: json(200, [AXE]) }));
    await open("/?q=axe");

    fireEvent.click(screen.getByRole("link", { name: "Discover" }));

    await waitFor(() => expect(cardNames()).toEqual(["Axe", "Rope", "Tent", "Stove"]));
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("");
  });

  it("does not let a borrow still in flight take focus from the box", async () => {
    let finish: (() => void) | null = null;
    liveBackend((state) => ({
      "POST /api/inventories/7/items/21/borrow/": () =>
        new Promise<Response>((resolve) => {
          finish = () => {
            state.items = [{ ...AXE, loan_status: "requested", borrowed_by_me: true }, ROPE];
            resolve(empty(204)({}));
          };
        }),
    }));
    await open();
    fireEvent.click(within(card("Axe")).getByRole("button", { name: "Ask to borrow Axe" }));
    const box = screen.getByRole("searchbox", { name: "Search" });
    box.focus();
    type("r");

    await waitFor(() => expect(finish).not.toBeNull());
    await act(async () => finish?.());

    await waitFor(() => expect(within(card("Axe")).queryByRole("button")).toBeNull());
    await act(async () => {});
    expect(box).toHaveFocus();
  });

  it("keeps the empty message with the query that found nothing while a new search loads", async () => {
    const axe = deferred([AXE]);
    liveBackend(() => ({ [searchUrl("xyz")]: json(200, []), [searchUrl("axe")]: axe.handler }));
    await open("/?q=xyz");

    type("axe");
    wait(300);
    await waitFor(() => expect(axe.seen.signal).toBeDefined());

    expect(screen.getByText("No items match “xyz”.")).toBeInTheDocument();
    expect(screen.queryByText("No items match “axe”.")).toBeNull();
    axe.resolve();
    await waitFor(() => expect(cardNames()).toEqual(["Axe"]));
  });

  it("drops text still waiting to be searched when the Discover link is followed", async () => {
    const backend = liveBackend(() => ({ [searchUrl("ro")]: json(200, [ROPE]) }));
    const page = await open("/");

    type("ro");
    wait(100);
    fireEvent.click(screen.getByRole("link", { name: "Discover" }));
    wait(300);
    await act(async () => {});

    expect(page.location().path).toBe("/");
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("");
    expect(backend.requests(searchUrl("ro"))).toHaveLength(0);
  });
});
