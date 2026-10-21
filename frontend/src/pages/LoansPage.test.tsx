import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BorrowedItem, LendingItem } from "../items";
import { ADA, empty, fakeBackend, held, json } from "../test-backend";
import { expectLabelsInNames, renderAt } from "../test-render";

type Routes = Parameters<typeof fakeBackend>[0];

const CLIMBING = { id: 7, name: "Climbing Club" };
const MIA = { id: 3, first_name: "Mia", last_name: "Lee", phone_number: "5552230003" };
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

function nameOf(button: HTMLElement) {
  return button.getAttribute("aria-label");
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
      "Rope: 60 m, yours. Requested by Mia Lee, (555) 223-0003, through Climbing Club.",
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
      fireEvent.click(screen.getByRole("button", { name: `${label}: Rope` }));

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

    fireEvent.click(screen.getByRole("button", { name: "Approve: Rope" }));

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
      "Axe, yours. On loan to Mia Lee, (555) 223-0003, through Climbing Club.",
      "Cord, owned by Bob Stone. On loan to Mia Lee, (555) 223-0003, through Climbing Club.",
      "Lamp, yours. On loan to Mia Lee, (555) 223-0003.",
    ]);
  });

  it.each([
    ["Axe", "/api/items/21/return/"],
    ["Lamp", "/api/items/23/return/"],
    ["Cord", "/api/inventories/7/items/22/return/"],
  ])("marks %s returned through %s", async (name, path) => {
    const backend = liveBackend(() => ({ [`POST ${path}`]: empty(204) }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: `Mark returned: ${name}` }));

    await waitFor(() => expect(backend.requests(`POST ${path}`)).toEqual([{ borrower_id: 3 }]));
  });
});

describe("my requests and borrowed", () => {
  it("lists requests and loans apart, with owner and inventory", async () => {
    liveBackend();

    await open();

    expect(texts("My requests")).toEqual([
      "Stove: gas, owned by Bob Stone. Waiting for approval through Camping Crew.",
    ]);
    expect(texts("Borrowed")).toEqual(["Tent, owned by Bob Stone. Borrowed by you."]);
    expect(within(region("Borrowed")).queryByRole("button")).toBeNull();
  });

  it("lists what the caller may give back itself under Using, apart from Borrowed", async () => {
    liveBackend();

    await open();

    expect(texts("Using")).toEqual([
      "Bivy, owned by Bob Stone. In use by you, through Climbing Club.",
      "Headlamp, yours. In use by you.",
    ]);
    expect(texts("Borrowed")).toEqual(["Tent, owned by Bob Stone. Borrowed by you."]);
  });

  it.each([
    ["Bivy", "/api/inventories/7/items/32/return/"],
    ["Headlamp", "/api/items/33/return/"],
  ])("is done using %s through %s, then reloads", async (name, path) => {
    const backend = liveBackend((state) => ({
      [`POST ${path}`]: () => {
        state.borrowed = state.borrowed.filter((item) => item.name !== name);
        return empty(204)({});
      },
    }));
    await open();

    const button = screen.getByRole("button", { name: `Done using it: ${name}` });
    expect(button).toHaveTextContent(/^Done using it$/);
    fireEvent.click(button);

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

    fireEvent.click(screen.getByRole("button", { name: "Cancel request: Stove" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Cancel request: Stove" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This request was approved, so it cannot be cancelled.",
    );
  });
});

describe("loans page", () => {
  it("names each button with its visible text, then the item", async () => {
    liveBackend();

    await open();

    expectLabelsInNames(document.body);
    expect(within(region("Lent out")).getAllByRole("button").map(nameOf)).toEqual([
      "Mark returned: Axe",
      "Mark returned: Cord",
      "Mark returned: Lamp",
    ]);
  });

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

describe("focus after an action", () => {
  it.each([
    [
      "Approve: Rope",
      "POST /api/inventories/7/items/20/approve/",
      (state: State) => {
        state.lending = state.lending.map((item) =>
          item.id === ROPE.id ? { ...item, loan_status: "on_loan" } : item,
        );
      },
    ],
    [
      "Decline: Rope",
      "POST /api/inventories/7/items/20/decline/",
      (state: State) => {
        state.lending = state.lending.filter((item) => item.id !== ROPE.id);
      },
    ],
    [
      "Mark returned: Axe",
      "POST /api/items/21/return/",
      (state: State) => {
        state.lending = state.lending.filter((item) => item.id !== AXE.id);
      },
    ],
    [
      "Cancel request: Stove",
      "POST /api/borrowing/30/cancel/",
      (state: State) => {
        state.borrowed = state.borrowed.filter((item) => item.id !== STOVE.id);
      },
    ],
    [
      "Done using it: Bivy",
      "POST /api/inventories/7/items/32/return/",
      (state: State) => {
        state.borrowed = state.borrowed.filter((item) => item.id !== BIVY.id);
      },
    ],
  ])("moves focus to the page heading when %s removes the button", async (name, key, act) => {
    liveBackend((state) => ({
      [key]: () => {
        act(state);
        return empty(204)({});
      },
    }));
    await open();
    const button = screen.getByRole("button", { name });
    button.focus();

    fireEvent.click(button);

    await waitFor(() => expect(button).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("heading", { name: "Loans" })).toHaveFocus());
  });

  it("leaves focus on the button when the item stays where it was", async () => {
    const backend = liveBackend(() => ({
      "POST /api/inventories/7/items/20/approve/": json(409, {
        detail: "This request or loan changed. Try again.",
      }),
    }));
    await open();
    const button = screen.getByRole("button", { name: "Approve: Rope" });
    button.focus();

    fireEvent.click(button);

    await screen.findByRole("alert");
    await waitFor(() =>
      expect(backend.keys().filter((key) => key === "GET /api/lending/")).toHaveLength(2),
    );
    expect(button).toHaveFocus();
  });
});

describe("two changes in flight", () => {
  it("moves focus to the heading when a later action removes its button last", async () => {
    const approve = held();
    const markReturned = held();
    let lists: State | undefined;
    const backend = liveBackend((state) => {
      lists = state;
      return {
        "POST /api/inventories/7/items/20/approve/": approve.route,
        "POST /api/items/21/return/": markReturned.route,
      };
    });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Approve: Rope" }));
    const button = screen.getByRole("button", { name: "Mark returned: Axe" });
    button.focus();
    fireEvent.click(button);
    await waitFor(() => expect(backend.requests("POST /api/items/21/return/")).toHaveLength(1));
    const lendingLoads = () => backend.keys().filter((key) => key === "GET /api/lending/");

    approve.respond(empty(204));
    await waitFor(() => expect(lendingLoads()).toHaveLength(2));
    await waitFor(() => expect(screen.queryByText("Loading…")).toBeNull());
    expect(button).toHaveFocus();

    markReturned.respond(() => {
      lists!.lending = lists!.lending.filter((item) => item.id !== AXE.id);
      return empty(204)({});
    });

    await waitFor(() => expect(button).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("heading", { name: "Loans" })).toHaveFocus());
  });

  it("shows no message for the older change when its reply comes last", async () => {
    const approve = held();
    liveBackend((state) => ({
      "POST /api/inventories/7/items/20/approve/": approve.route,
      "POST /api/borrowing/30/cancel/": () => {
        state.borrowed = state.borrowed.filter((item) => item.id !== STOVE.id);
        return empty(204)({});
      },
    }));
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Approve: Rope" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel request: Stove" }));
    await within(region("My requests")).findByText("You have no pending requests.");

    approve.respond(json(409, { detail: "This request or loan changed. Try again." }));

    await waitFor(() => expect(texts("Waiting for your approval")).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
