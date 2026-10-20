import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BorrowedItem, DiscoverItem } from "../items";
import { ADA, empty, fakeBackend, json } from "../test-backend";
import { renderAt } from "../test-render";

type Routes = Parameters<typeof fakeBackend>[0];

const CAMPING = { id: 8, name: "Camping Crew", role: "member" } as const;
const CLIMBING = { id: 7, name: "Climbing Club", role: "member" } as const;
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
  borrowed: BorrowedItem[];
}

/** A backend whose item lists change as the page acts, so a reload shows the new state. */
function liveBackend(routes: (state: State) => Routes = () => ({})) {
  const state: State = { items: [AXE, ROPE, TENT, STOVE], borrowed: [] };
  return fakeBackend({
    "GET /api/auth/me/": json(200, ADA),
    "GET /api/discover/": () => json(200, state.items)({}),
    "GET /api/borrowing/": () => json(200, state.borrowed)({}),
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

describe("discover as an admin or owner", () => {
  const ADMIN_OF_CLIMBING = { ...CLIMBING, role: "admin" } as const;
  const OWNER_OF_CAMPING = { ...CAMPING, role: "owner" } as const;
  /** Held by Ada through Climbing Club, where she is an admin. */
  const HELD: BorrowedItem = {
    id: 21,
    name: "Axe",
    description: "",
    loan_status: "on_loan",
    owner: BOB,
    loan_inventory: CLIMBING,
    can_return: true,
  };

  it("uses an item through the inventory that makes the caller an admin", async () => {
    const backend = liveBackend((state) => {
      state.items = [{ ...ROPE, inventories: [CAMPING, ADMIN_OF_CLIMBING] }];
      return {
        "POST /api/inventories/7/items/20/borrow/": () => {
          state.items = [{ ...state.items[0], loan_status: "on_loan", borrowed_by_me: true }];
          state.borrowed = [{ ...HELD, id: 20, name: "Rope" }];
          return empty(204)({});
        },
      };
    });
    await open();
    expect(within(card("Rope")).queryByRole("button", { name: "Ask to borrow Rope" })).toBeNull();

    const button = within(card("Rope")).getByRole("button", { name: "Use it myself: Rope" });
    expect(button).toHaveTextContent(/^Use it myself$/);
    fireEvent.click(button);

    expect(within(card("Rope")).queryByLabelText("Borrow through")).toBeNull();
    expect(within(card("Rope")).queryByLabelText("Use through")).toBeNull();
    expect(await within(card("Rope")).findByText("In use by you")).toBeInTheDocument();
    expect(backend.requests("POST /api/inventories/7/items/20/borrow/")).toEqual([undefined]);
  });

  it("asks which inventory to use the item through when the caller is an admin in several", async () => {
    const HIKING = { id: 9, name: "Hiking Group", role: "member" } as const;
    const backend = liveBackend((state) => {
      state.items = [{ ...ROPE, inventories: [HIKING, OWNER_OF_CAMPING, ADMIN_OF_CLIMBING] }];
      return { "POST /api/inventories/7/items/20/borrow/": empty(204) };
    });
    await open();

    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Use it myself: Rope" }));
    const through = within(card("Rope")).getByLabelText("Use through");
    expect(
      within(through)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Camping Crew", "Climbing Club"]);
    expect(through).toHaveValue("8");
    await waitFor(() => expect(through).toHaveFocus());

    fireEvent.change(through, { target: { value: "7" } });
    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Use it myself" }));

    await waitFor(() =>
      expect(backend.requests("POST /api/inventories/7/items/20/borrow/")).toEqual([undefined]),
    );
    expect(backend.requests("POST /api/inventories/8/items/20/borrow/")).toHaveLength(0);
  });

  it("moves focus to the card heading after using the item from the inventory choice", async () => {
    liveBackend((state) => {
      state.items = [{ ...ROPE, inventories: [OWNER_OF_CAMPING, ADMIN_OF_CLIMBING] }];
      return {
        "POST /api/inventories/8/items/20/borrow/": () => {
          state.items = [{ ...state.items[0], loan_status: "on_loan", borrowed_by_me: true }];
          state.borrowed = [{ ...HELD, id: 20, name: "Rope", loan_inventory: CAMPING }];
          return empty(204)({});
        },
      };
    });
    await open();

    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Use it myself: Rope" }));
    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Use it myself" }));

    expect(await within(card("Rope")).findByText("In use by you")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(card("Rope")).getByRole("heading", { name: "Rope" })).toHaveFocus(),
    );
  });

  it("closes the use choice on Cancel without borrowing", async () => {
    const backend = liveBackend((state) => {
      state.items = [{ ...ROPE, inventories: [OWNER_OF_CAMPING, ADMIN_OF_CLIMBING] }];
      return {};
    });
    await open();

    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Use it myself: Rope" }));
    fireEvent.click(within(card("Rope")).getByRole("button", { name: "Cancel" }));

    expect(within(card("Rope")).queryByLabelText("Use through")).toBeNull();
    await waitFor(() =>
      expect(
        within(card("Rope")).getByRole("button", { name: "Use it myself: Rope" }),
      ).toHaveFocus(),
    );
    expect(backend.requests("POST /api/inventories/8/items/20/borrow/")).toHaveLength(0);
  });

  it("gives back an item it uses through its loan inventory", async () => {
    const backend = liveBackend((state) => {
      state.items = [
        { ...AXE, inventories: [ADMIN_OF_CLIMBING], loan_status: "on_loan", borrowed_by_me: true },
      ];
      state.borrowed = [HELD];
      return {
        "POST /api/inventories/7/items/21/return/": () => {
          state.items = [{ ...AXE, inventories: [ADMIN_OF_CLIMBING] }];
          state.borrowed = [];
          return empty(204)({});
        },
      };
    });
    await open();
    expect(card("Axe")).toHaveClass("unavailable");

    const button = within(card("Axe")).getByRole("button", { name: "Done using it: Axe" });
    expect(button).toHaveTextContent(/^Done using it$/);
    fireEvent.click(button);

    expect(
      await within(card("Axe")).findByRole("button", { name: "Use it myself: Axe" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(within(card("Axe")).getByRole("heading", { name: "Axe" })).toHaveFocus(),
    );
    expect(backend.requests("POST /api/inventories/7/items/21/return/")).toEqual([
      { borrower_id: ADA.id },
    ]);
  });

  it("focuses only the card acted on when another card changes in the same reload", async () => {
    liveBackend((state) => {
      state.items = [
        { ...AXE, inventories: [ADMIN_OF_CLIMBING], loan_status: "on_loan", borrowed_by_me: true },
        STOVE,
      ];
      state.borrowed = [HELD];
      return {
        "POST /api/inventories/7/items/21/return/": () => {
          state.items = [
            { ...AXE, inventories: [ADMIN_OF_CLIMBING] },
            { ...STOVE, loan_status: "available" },
          ];
          state.borrowed = [];
          return empty(204)({});
        },
      };
    });
    await open();

    fireEvent.click(within(card("Axe")).getByRole("button", { name: "Done using it: Axe" }));

    expect(
      await within(card("Stove")).findByRole("button", { name: "Ask to borrow Stove" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(within(card("Axe")).getByRole("heading", { name: "Axe" })).toHaveFocus(),
    );
  });

  it("offers nothing on a loan the caller may not give back", async () => {
    liveBackend((state) => {
      state.items = [
        { ...AXE, inventories: [ADMIN_OF_CLIMBING], loan_status: "on_loan", borrowed_by_me: true },
      ];
      state.borrowed = [{ ...HELD, can_return: false }];
      return {};
    });

    await open();

    expect(within(card("Axe")).getByText("Borrowed by you")).toBeInTheDocument();
    expect(within(card("Axe")).queryByRole("button")).toBeNull();
  });
});
