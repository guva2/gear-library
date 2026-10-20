import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Item } from "../items";
import { ADA, empty, fakeBackend, json } from "../test-backend";
import { renderAt } from "../test-render";

type Routes = Parameters<typeof fakeBackend>[0];

const NO_LOAN = { loan_status: "available", borrower: null, loan_inventory: null } as const;
const MIA = { id: 3, first_name: "Mia", last_name: "Lee", phone_number: "5551230003" };

const ROPE: Item = {
  id: 20,
  name: "Rope",
  description: "60 m dynamic",
  inventories: [
    { id: 8, name: "Camping Crew" },
    { id: 7, name: "Climbing Club" },
  ],
  ...NO_LOAN,
};
const AXE: Item = { id: 21, name: "Axe", description: "", inventories: [], ...NO_LOAN };

/** A backend whose item list changes as the page acts, so a reload shows the new state. */
function liveBackend(routes: (state: { items: Item[] }) => Routes = () => ({})) {
  const state = { items: [AXE, ROPE] };
  return fakeBackend({
    "GET /api/auth/me/": json(200, ADA),
    "GET /api/items/": () => json(200, state.items)({}),
    ...routes(state),
  });
}

async function open() {
  renderAt("/manage/items");
  await screen.findByRole("region", { name: "My items" });
  await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
}

function region(name: string) {
  return screen.getByRole("region", { name });
}

function itemFor(name: string) {
  const items = within(region("My items")).getAllByRole("listitem");
  const found = items.find((item) => within(item).queryByText(name, { exact: false }));
  if (!found) throw new Error(`No item ${name}`);
  return found;
}

function fill(container: HTMLElement, label: string, value: string) {
  fireEvent.change(within(container).getByLabelText(label), { target: { value } });
}

describe("my items", () => {
  it("shows each item with its description and where it is listed", async () => {
    liveBackend();

    await open();

    const items = within(region("My items")).getAllByRole("listitem");
    expect(items.map((item) => item.querySelector("p")?.textContent)).toEqual([
      "Axe",
      "Rope: 60 m dynamic",
    ]);
    expect(
      within(itemFor("Rope")).getByText("Listed in Camping Crew, Climbing Club."),
    ).toBeVisible();
    expect(within(itemFor("Axe")).getByText("Not listed in any inventory.")).toBeVisible();
  });

  it("says so when the user has no gear", async () => {
    liveBackend((state) => {
      state.items = [];
      return {};
    });

    await open();

    expect(within(region("My items")).getByText("You have no gear yet.")).toBeInTheDocument();
  });

  it("offers no way to list or unlist items", async () => {
    liveBackend();

    await open();

    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: /List|Remove/ })).toBeNull();
  });

  it("shows an error when the items cannot be loaded", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA), "GET /api/items/": json(500, {}) });

    renderAt("/manage/items");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load your items.");
  });
});

describe("page-level errors", () => {
  it("are cleared when an add or an edit starts", async () => {
    liveBackend((state) => ({
      "DELETE /api/items/20/": json(404, { detail: "Item not found." }),
      "POST /api/items/": () => {
        state.items = [AXE, ROPE, { ...AXE, id: 22, name: "Tent" }];
        return json(201, state.items[2])({});
      },
      "PATCH /api/items/21/": json(200, AXE),
    }));
    await open();
    const failDelete = async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete Rope" }));
      fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Item not found.");
    };

    await failDelete();
    const add = region("Add an item");
    fill(add, "Name", "Tent");
    fireEvent.click(within(add).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());

    await failDelete();
    fireEvent.click(screen.getByRole("button", { name: "Edit Axe" }));
    fireEvent.click(within(itemFor("Axe")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});

describe("adding an item", () => {
  it("creates the item, clears the form and reloads the list", async () => {
    const TENT = { ...AXE, id: 22, name: "Tent" };
    const backend = liveBackend((state) => ({
      "POST /api/items/": () => {
        state.items = [AXE, ROPE, TENT];
        return json(201, TENT)({});
      },
    }));
    await open();
    const add = region("Add an item");

    fill(add, "Name", "Tent");
    fireEvent.click(within(add).getByRole("button", { name: "Add" }));

    expect(await within(region("My items")).findByText("Tent")).toBeInTheDocument();
    expect(backend.requests("POST /api/items/")).toEqual([{ name: "Tent", description: "" }]);
    expect(within(add).getByLabelText("Name")).toHaveValue("");
  });

  it("shows a field error next to its field and focuses it", async () => {
    liveBackend(() => ({
      "POST /api/items/": json(400, {
        description: ["Ensure this field has no more than 512 characters."],
      }),
    }));
    await open();
    const add = region("Add an item");

    fill(add, "Name", "Tent");
    fireEvent.click(within(add).getByRole("button", { name: "Add" }));

    const description = within(add).getByLabelText("Description");
    await waitFor(() =>
      expect(description).toHaveAccessibleDescription(
        "Ensure this field has no more than 512 characters.",
      ),
    );
    await waitFor(() => expect(description).toHaveFocus());
  });
});

describe("editing an item", () => {
  it("opens a form filled with the item and focuses its name", async () => {
    liveBackend();
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Edit Rope" }));

    const form = itemFor("Rope");
    await waitFor(() => expect(within(form).getByLabelText("Name")).toHaveFocus());
    expect(within(form).getByLabelText("Name")).toHaveValue("Rope");
    expect(within(form).getByLabelText("Description")).toHaveValue("60 m dynamic");
  });

  it("saves the changes, reloads, and returns focus to the item's Edit button", async () => {
    const backend = liveBackend((state) => ({
      "PATCH /api/items/20/": () => {
        state.items = [AXE, { ...ROPE, name: "Rope 70" }];
        return json(200, state.items[1])({});
      },
    }));
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Edit Rope" }));
    const form = itemFor("Rope");

    fill(form, "Name", "Rope 70");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    const edit = await screen.findByRole("button", { name: "Edit Rope 70" });
    await waitFor(() => expect(edit).toHaveFocus());
    expect(backend.requests("PATCH /api/items/20/")).toEqual([
      { name: "Rope 70", description: "60 m dynamic" },
    ]);
    expect(within(region("My items")).queryByLabelText("Name")).toBeNull();
  });

  it("keeps the form open with the field error after a refused edit", async () => {
    liveBackend(() => ({
      "PATCH /api/items/20/": json(400, { name: ["This field may not be blank."] }),
    }));
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Edit Rope" }));
    const form = itemFor("Rope");

    fill(form, "Name", "");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    const name = within(form).getByLabelText("Name");
    await waitFor(() => expect(name).toHaveAccessibleDescription("This field may not be blank."));
    await waitFor(() => expect(name).toHaveFocus());
  });

  it("explains and reloads when the item was deleted elsewhere", async () => {
    liveBackend((state) => ({
      "PATCH /api/items/20/": () => {
        state.items = [AXE];
        return json(404, { detail: "Item not found." })({});
      },
    }));
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Edit Rope" }));

    fireEvent.click(within(itemFor("Rope")).getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Item not found.");
    await waitFor(() =>
      expect(within(region("My items")).getAllByRole("listitem")).toHaveLength(1),
    );
  });

  it("cancels without saving", async () => {
    const backend = liveBackend();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Edit Rope" }));

    fireEvent.click(within(itemFor("Rope")).getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("button", { name: "Edit Rope" })).toHaveFocus();
    expect(backend.requests("PATCH /api/items/20/")).toHaveLength(0);
  });
});

describe("deleting an item", () => {
  it("deletes only after confirming, then reloads", async () => {
    const backend = liveBackend((state) => ({
      "DELETE /api/items/20/": () => {
        state.items = [AXE];
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Delete Rope" }));
    expect(screen.getByText(/Delete Rope\? This cannot be undone\./)).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(backend.requests("DELETE /api/items/20/")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Delete Rope" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));

    await waitFor(() =>
      expect(within(region("My items")).getAllByRole("listitem")).toHaveLength(1),
    );
    expect(backend.requests("DELETE /api/items/20/")).toHaveLength(1);
  });

  it("shows why a delete failed", async () => {
    liveBackend(() => ({ "DELETE /api/items/20/": json(404, { detail: "Item not found." }) }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Delete Rope" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Item not found.");
  });
});

describe("loans of my items", () => {
  const ON_LOAN: Item = {
    ...ROPE,
    loan_status: "on_loan",
    borrower: MIA,
    loan_inventory: { id: 7, name: "Climbing Club" },
  };

  it("shows each item's loan state with the borrower's name and phone number", async () => {
    liveBackend((state) => {
      state.items = [
        { ...AXE, loan_status: "requested", borrower: MIA, loan_inventory: ON_LOAN.loan_inventory },
        ON_LOAN,
        { ...ON_LOAN, id: 23, name: "Tent", loan_inventory: null },
      ];
      return {};
    });

    await open();

    expect(
      within(itemFor("Axe")).getByText(
        "Requested by Mia Lee, (555) 123-0003, through Climbing Club.",
      ),
    ).toBeVisible();
    expect(
      within(itemFor("Rope")).getByText(
        "On loan to Mia Lee, (555) 123-0003, through Climbing Club.",
      ),
    ).toBeVisible();
    expect(within(itemFor("Tent")).getByText("On loan to Mia Lee, (555) 123-0003.")).toBeVisible();
  });

  it("says when an item is available", async () => {
    liveBackend();

    await open();

    expect(within(itemFor("Axe")).getByText("Available.")).toBeVisible();
  });

  it("offers Mark returned only on items on loan, and sends the borrower it showed", async () => {
    const backend = liveBackend((state) => {
      state.items = [AXE, ON_LOAN];
      return {
        "POST /api/items/20/return/": () => {
          state.items = [AXE, ROPE];
          return empty(204)({});
        },
      };
    });
    await open();
    expect(screen.getAllByRole("button", { name: /^Mark .* returned$/ })).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Mark Rope returned" }));

    expect(await within(itemFor("Rope")).findByText("Available.")).toBeVisible();
    expect(backend.requests("POST /api/items/20/return/")).toEqual([{ borrower_id: MIA.id }]);
  });

  it("explains why an item on loan cannot be deleted", async () => {
    liveBackend((state) => {
      state.items = [ON_LOAN];
      return {
        "DELETE /api/items/20/": json(409, {
          detail: "This item is on loan. It can be deleted once it is returned.",
        }),
      };
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Delete Rope" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This item is on loan. It can be deleted once it is returned.",
    );
  });
});
