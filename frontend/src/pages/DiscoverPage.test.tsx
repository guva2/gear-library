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

/** A backend whose item list changes as the page acts, so a reload shows the new state. */
function liveBackend(routes: (state: { items: DiscoverItem[] }) => Routes = () => ({})) {
  const state = { items: [AXE, ROPE, TENT, STOVE] };
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
    ["Tent", "Requested by you"],
    ["Stove", "On loan"],
  ])("greys out %s with its status and no Request", async (name, status) => {
    liveBackend();

    await open();

    expect(card(name)).toHaveClass("unavailable");
    expect(within(card(name)).getByText(status)).toBeInTheDocument();
    expect(within(card(name)).queryByRole("button")).toBeNull();
  });

  it("says when the caller's own request is on loan to them", async () => {
    liveBackend((state) => {
      state.items = [{ ...TENT, loan_status: "on_loan" }];
      return {};
    });

    await open();

    expect(within(card("Tent")).getByText("On loan to you")).toBeInTheDocument();
  });

  it("requests an item listed in one inventory through it, then reloads", async () => {
    const backend = liveBackend((state) => ({
      "POST /api/inventories/7/items/21/borrow/": () => {
        state.items = [{ ...AXE, loan_status: "requested", borrowed_by_me: true }];
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(within(card("Axe")).getByRole("button", { name: "Request Axe" }));

    expect(await within(card("Axe")).findByText("Requested by you")).toBeInTheDocument();
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

    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Request Rope" }));
    const through = within(card("Rope")).getByLabelText("Request through");
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

    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Request Rope" }));
    fireEvent.change(within(card("Rope")).getByLabelText("Request through"), {
      target: { value: "7" },
    });
    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Send request" }));

    expect(await within(card("Rope")).findByText("Requested by you")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(card("Rope")).getByRole("heading", { name: "Rope" })).toHaveFocus(),
    );
  });

  it("closes the inventory choice on Cancel without requesting", async () => {
    const backend = liveBackend();
    await open();

    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Request Rope" }));
    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Cancel" }));

    expect(within(card("Rope")).queryByLabelText("Request through")).toBeNull();
    await waitFor(() =>
      expect(within(card("Rope")).getByRole("button", { name: "Request Rope" })).toHaveFocus(),
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

    fireEvent.click(within(card("Axe")).getByRole("button", { name: "Request Axe" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This item has already been requested or is on loan.",
    );
    await waitFor(() => expect(loads).toBe(2));
  });

  it("says so when there is nothing to discover", async () => {
    liveBackend((state) => {
      state.items = [];
      return {};
    });

    await open();

    expect(screen.getByText(/Nothing to discover yet\./)).toBeInTheDocument();
  });

  it("shows an error when the items cannot be loaded", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA), "GET /api/discover/": json(500, {}) });

    renderAt("/");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the items.");
  });
});
