import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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

async function open() {
  renderAt("/");
  await screen.findByRole("heading", { name: "Discover" });
  await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
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
