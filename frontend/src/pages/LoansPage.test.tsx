import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BorrowedItem, LendingItem } from "../items";
import { ADA, empty, fakeBackend, json } from "../test-backend";
import { renderAt } from "../test-render";

type Routes = Parameters<typeof fakeBackend>[0];

const CLIMBING = { id: 7, name: "Climbing Club" };
const MIA = { id: 3, first_name: "Mia", last_name: "Lee", phone_number: "5551230003" };
const BOB = { first_name: "Bob", last_name: "Stone" };

const ROPE: LendingItem = {
  id: 20,
  name: "Rope",
  description: "60 m",
  inventories: [CLIMBING],
  loan_status: "requested",
  borrower: MIA,
  loan_inventory: CLIMBING,
  owner: null,
  can_answer: true,
};
const AXE: LendingItem = { ...ROPE, id: 21, name: "Axe", description: "", loan_status: "on_loan" };
const CORD: LendingItem = {
  ...AXE,
  id: 22,
  name: "Cord",
  owner: BOB,
  can_answer: false,
};
const LAMP: LendingItem = { ...AXE, id: 23, name: "Lamp", loan_inventory: null, inventories: [] };

const STOVE: BorrowedItem = {
  id: 30,
  name: "Stove",
  description: "gas",
  loan_status: "requested",
  owner: BOB,
  loan_inventory: { id: 8, name: "Camping Crew" },
  can_return: false,
};
const TENT: BorrowedItem = {
  ...STOVE,
  id: 31,
  name: "Tent",
  description: "",
  loan_status: "on_loan",
  loan_inventory: null,
};
/** Held by Ada as an admin of its loan inventory. */
const BIVY: BorrowedItem = {
  ...TENT,
  id: 32,
  name: "Bivy",
  loan_inventory: CLIMBING,
  can_return: true,
};
/** Ada's own item, which she uses. */
const HEADLAMP: BorrowedItem = {
  ...TENT,
  id: 33,
  name: "Headlamp",
  owner: { first_name: ADA.first_name, last_name: ADA.last_name },
  can_return: true,
};

interface State {
  lending: LendingItem[];
  borrowed: BorrowedItem[];
}

/** A backend whose lists change as the page acts, so a reload shows the new state. */
function liveBackend(routes: (state: State) => Routes = () => ({})) {
  const state: State = {
    lending: [ROPE, AXE, CORD, LAMP],
    borrowed: [BIVY, HEADLAMP, STOVE, TENT],
  };
  return fakeBackend({
    "GET /api/auth/me/": json(200, ADA),
    "GET /api/lending/": () => json(200, state.lending)({}),
    "GET /api/borrowing/": () => json(200, state.borrowed)({}),
    ...routes(state),
  });
}

async function open() {
  renderAt("/loans");
  await screen.findByRole("heading", { name: "Loans" });
  await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
}

function region(name: string) {
  return screen.getByRole("region", { name });
}

function texts(name: string) {
  return within(region(name))
    .getAllByRole("listitem")
    .map((item) => item.firstChild?.textContent);
}

describe("waiting for your approval", () => {
  it("lists requests with the requester and the inventory", async () => {
    liveBackend();

    await open();

    expect(texts("Waiting for your approval")).toEqual([
      "Rope: 60 m, yours. Requested by Mia Lee, (555) 123-0003, through Climbing Club.",
    ]);
  });

  it.each(["approve", "decline"])(
    "sends %s through the loan inventory with the requester it showed",
    async (action) => {
      const backend = liveBackend((state) => ({
        [`POST /api/inventories/7/items/20/${action}/`]: () => {
          state.lending = [AXE];
          return empty(204)({});
        },
      }));
      await open();

      const label = action === "approve" ? "Approve" : "Decline";
      fireEvent.click(screen.getByRole("button", { name: `${label} request for Rope` }));

      expect(
        await within(region("Waiting for your approval")).findByText("Nothing is waiting."),
      ).toBeInTheDocument();
      expect(backend.requests(`POST /api/inventories/7/items/20/${action}/`)).toEqual([
        { borrower_id: MIA.id },
      ]);
    },
  );

  it("offers no answer when the caller may not answer", async () => {
    liveBackend((state) => {
      state.lending = [{ ...ROPE, can_answer: false }];
      return {};
    });

    await open();

    expect(within(region("Waiting for your approval")).queryByRole("button")).toBeNull();
  });

  it("shows why an answer was refused", async () => {
    liveBackend(() => ({
      "POST /api/inventories/7/items/20/approve/": json(409, {
        detail: "This request or loan changed. Try again.",
      }),
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Approve request for Rope" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This request or loan changed. Try again.",
    );
  });
});

describe("lent out", () => {
  it("lists loans with the owner, the borrower and the inventory", async () => {
    liveBackend();

    await open();

    expect(texts("Lent out")).toEqual([
      "Axe, yours. On loan to Mia Lee, (555) 123-0003, through Climbing Club.",
      "Cord, owned by Bob Stone. On loan to Mia Lee, (555) 123-0003, through Climbing Club.",
      "Lamp, yours. On loan to Mia Lee, (555) 123-0003.",
    ]);
  });

  it.each([
    ["Axe", "/api/items/21/return/"],
    ["Lamp", "/api/items/23/return/"],
    ["Cord", "/api/inventories/7/items/22/return/"],
  ])("marks %s returned through %s", async (name, path) => {
    const backend = liveBackend(() => ({ [`POST ${path}`]: empty(204) }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: `Mark ${name} returned` }));

    await waitFor(() => expect(backend.requests(`POST ${path}`)).toEqual([{ borrower_id: 3 }]));
  });
});

describe("my requests and borrowed", () => {
  it("lists requests and loans apart, with owner and inventory", async () => {
    liveBackend();

    await open();

    expect(texts("My requests")).toEqual([
      "Stove: gas, owned by Bob Stone. Requested through Camping Crew.",
    ]);
    expect(texts("Borrowed")).toEqual(["Tent, owned by Bob Stone. On loan to you."]);
    expect(within(region("Borrowed")).queryByRole("button")).toBeNull();
  });

  it("lists what the caller may mark available under Using, apart from Borrowed", async () => {
    liveBackend();

    await open();

    expect(texts("Using")).toEqual([
      "Bivy, owned by Bob Stone. In use by you, through Climbing Club.",
      "Headlamp, yours. In use by you.",
    ]);
    expect(texts("Borrowed")).toEqual(["Tent, owned by Bob Stone. On loan to you."]);
  });

  it.each([
    ["Bivy", "/api/inventories/7/items/32/return/"],
    ["Headlamp", "/api/items/33/return/"],
  ])("marks %s available through %s, then reloads", async (name, path) => {
    const backend = liveBackend((state) => ({
      [`POST ${path}`]: () => {
        state.borrowed = state.borrowed.filter((item) => item.name !== name);
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: `Mark ${name} available` }));

    await waitFor(() => expect(texts("Using")).toHaveLength(1));
    expect(backend.requests(`POST ${path}`)).toEqual([{ borrower_id: ADA.id }]);
  });

  it("cancels a pending request and reloads", async () => {
    const backend = liveBackend((state) => ({
      "POST /api/borrowing/30/cancel/": () => {
        state.borrowed = [TENT];
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Cancel request for Stove" }));

    expect(
      await within(region("My requests")).findByText("You have no pending requests."),
    ).toBeInTheDocument();
    expect(backend.requests("POST /api/borrowing/30/cancel/")).toEqual([undefined]);
  });

  it("shows why a cancel was refused", async () => {
    liveBackend(() => ({
      "POST /api/borrowing/30/cancel/": json(409, {
        detail: "This request was approved, so it cannot be cancelled.",
      }),
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Cancel request for Stove" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This request was approved, so it cannot be cancelled.",
    );
  });
});

describe("loans page", () => {
  it("says so in each section when there is nothing", async () => {
    liveBackend((state) => {
      state.lending = [];
      state.borrowed = [];
      return {};
    });

    await open();

    expect(
      [
        "Waiting for your approval",
        "Lent out",
        "My requests",
        "Using",
        "Borrowed",
      ].map((name) => within(region(name)).getByRole("paragraph").textContent),
    ).toEqual([
      "Nothing is waiting.",
      "Nothing is lent out.",
      "You have no pending requests.",
      "You are not using anything.",
      "You are not borrowing anything.",
    ]);
  });

  it("shows an error when the loans cannot be loaded", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA), "GET /api/lending/": json(500, {}) });

    renderAt("/loans");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load your loans.");
  });
});
