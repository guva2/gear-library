import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ADA, empty, fakeBackend, held, json } from "../test-backend";
import type { ListedItem } from "../items";
import { expectLabelsInNames, fillIn, renderAt } from "../test-render";

type Routes = Parameters<typeof fakeBackend>[0];
type Role = "member" | "admin" | "owner";

const URL = "/api/inventories/7/";
// The loan fields of a listed item that nobody has requested.
const AVAILABLE = { loan_status: "available", borrowed_by_me: false, borrower: null } as const;
const PHONE_NUMBER = /\(?[0-9]{3}\)? ?[0-9]{3}-?[0-9]{4}/;

const BOB = { id: 2, first_name: "Bob", last_name: "Stone", phone_number: "5552230002" };
const MIA = { id: 3, first_name: "Mia", last_name: "Lee", phone_number: "5552230003" };
const INVITE = {
  id: 40,
  invitee: { phone_number: "5552230004" },
  invited_by: { first_name: "Bob", last_name: "Stone" },
};

// Accepted connections of the caller: Bob is a member, Cal has the pending invite, and
// Dee and Eve can be invited.
const CONNECTIONS = [
  BOB,
  { id: 4, first_name: "Cal", last_name: "Reyes", phone_number: "5552230004" },
  { id: 5, first_name: "Dee", last_name: "Park", phone_number: "5552230005" },
  { id: 6, first_name: "Eve", last_name: "Moss", phone_number: "5552230006" },
].map((user) => ({ id: 100 + user.id, status: "accepted", user }));

function members(role: Role) {
  return [
    { ...ADA, role },
    { ...BOB, role: "admin" },
    { ...MIA, role: "member" },
  ];
}

function asRole(role: Role, routes: Routes = {}) {
  const staffRoutes: Routes =
    role === "member"
      ? {}
      : {
          [`GET ${URL}members/`]: json(200, members(role)),
          [`GET ${URL}invites/`]: json(200, [INVITE]),
          "GET /api/connections/": json(200, CONNECTIONS),
        };
  return fakeBackend({
    "GET /api/auth/me/": json(200, ADA),
    [`GET ${URL}`]: json(200, { id: 7, name: "Climbing Club", role }),
    [`GET ${URL}items/`]: json(200, []),
    "GET /api/borrowing/": json(200, []),
    ...staffRoutes,
    ...routes,
  });
}

async function open() {
  renderAt("/inventories/7");
  await screen.findByRole("heading", { name: "Climbing Club" });
}

function region(name: string) {
  return screen.getByRole("region", { name });
}

describe("as a member", () => {
  // Names only. The extra phone number checks that the page renders nothing but names.
  const NAMES = [
    { first_name: "Olive", last_name: "Grant", phone_number: "5552230009" },
    { first_name: "Bob", last_name: "Stone" },
  ];

  it("shows the names of the admins and owners and nothing about other members", async () => {
    const backend = asRole("member", { [`GET ${URL}members/`]: json(200, NAMES) });

    await open();

    expect(screen.getByText("Your role: member")).toBeInTheDocument();
    const people = region("Admins and owners");
    expect(within(people).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Olive Grant",
      "Bob Stone",
    ]);
    expect(document.body.textContent).not.toMatch(PHONE_NUMBER);
    expect(screen.queryByText("Mia Lee")).not.toBeInTheDocument();
    expect(backend.requests(`GET ${URL}invites/`)).toHaveLength(0);
    expect(backend.requests("GET /api/connections/")).toHaveLength(0);
  });

  it("offers only Leave", async () => {
    asRole("member", { [`GET ${URL}members/`]: json(200, NAMES) });

    await open();

    expect(screen.getByRole("button", { name: "Leave inventory" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Invite|Remove|Rename|Delete|Revoke/ })).toBeNull();
  });
});

describe("as an admin", () => {
  it("shows every member with phone number and role, and the pending invites", async () => {
    asRole("admin");

    await open();

    const rows = within(region("Members")).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "Ada Lovelace(555) 223-4567admin",
      "Bob Stone(555) 223-0002admin",
      "Mia Lee(555) 223-0003member",
    ]);
    expect(within(region("Pending invites")).getByText(/223-0004/)).toHaveTextContent(
      "(555) 223-0004, invited by Bob Stone",
    );
  });

  it("puts the members table in a labelled box that can be focused to scroll it", async () => {
    asRole("admin");

    await open();

    const box = within(region("Members")).getByRole("region", { name: "Members table" });
    expect(box).toHaveClass("table-scroll");
    expect(box).toHaveAttribute("tabindex", "0");
    expect(within(box).getByRole("table")).toBeInTheDocument();
  });

  it("cannot change roles, remove members, rename or delete", async () => {
    asRole("admin");

    await open();

    expect(screen.queryByRole("combobox", { name: /^Role for/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove|Rename|Delete/ })).toBeNull();
  });

  it("offers only connections who are not members and have no pending invite", async () => {
    asRole("admin");

    await open();

    const picker = screen.getByRole("combobox", { name: "Connection" });
    expect(within(picker).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Dee Park, (555) 223-0005",
      "Eve Moss, (555) 223-0006",
    ]);
  });

  it("invites the chosen connection and reloads the invites and the picker", async () => {
    const EVE_INVITE = { ...INVITE, id: 41, invitee: { phone_number: "5552230006" } };
    let invites = [INVITE];
    const backend = asRole("admin", {
      [`GET ${URL}invites/`]: () => json(200, invites)({}),
      [`POST ${URL}invites/`]: () => {
        invites = [INVITE, EVE_INVITE];
        return json(201, EVE_INVITE)({});
      },
    });
    await open();

    fireEvent.change(screen.getByRole("combobox", { name: "Connection" }), {
      target: { value: "6" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    await waitFor(() =>
      expect(within(region("Pending invites")).getAllByRole("listitem")).toHaveLength(2),
    );
    expect(backend.requests(`POST ${URL}invites/`)).toEqual([{ user_id: 6 }]);
    const picker = screen.getByRole("combobox", { name: "Connection" });
    expect(within(picker).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Dee Park, (555) 223-0005",
    ]);
  });

  it.each([
    ["every connection is a member or invited", CONNECTIONS.slice(0, 2)],
    ["there are no connections", []],
  ])("links to My connections when %s", async (_, connections) => {
    asRole("admin", { "GET /api/connections/": json(200, connections) });

    await open();

    const invites = region("Pending invites");
    expect(within(invites).getByText(/No connections to invite\./)).toBeInTheDocument();
    expect(within(invites).getByRole("link", { name: "My connections" })).toHaveAttribute(
      "href",
      "/connections",
    );
    expect(screen.queryByRole("combobox", { name: "Connection" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Invite" })).toBeNull();
  });

  const REFUSED = json(400, { user_id: ["You can invite only your connections."] });

  it("names a refused connection in the section alert when others remain in the picker", async () => {
    asRole("admin", { [`POST ${URL}invites/`]: REFUSED });
    await open();
    fireEvent.change(screen.getByRole("combobox", { name: "Connection" }), {
      target: { value: "5" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    expect(await within(region("Pending invites")).findByRole("alert")).toHaveTextContent(
      "Dee Park was not invited. You can invite only your connections.",
    );
    const picker = screen.getByRole("combobox", { name: "Connection" });
    expect(picker).not.toHaveAttribute("aria-invalid");
    expect(picker).not.toHaveAccessibleDescription(/only your connections/);
  });

  it("keeps the refusal visible when the refused connection was the only option", async () => {
    let connections = CONNECTIONS.slice(0, 3);
    asRole("admin", {
      "GET /api/connections/": () => json(200, connections)({}),
      [`POST ${URL}invites/`]: () => {
        connections = CONNECTIONS.slice(0, 2);
        return REFUSED({});
      },
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    expect(await within(region("Pending invites")).findByRole("alert")).toHaveTextContent(
      "Dee Park was not invited. You can invite only your connections.",
    );
    await waitFor(() => expect(screen.queryByRole("combobox", { name: "Connection" })).toBeNull());
  });

  const DEE_INVITE = { ...INVITE, id: 42, invitee: { phone_number: "5552230005" } };

  it("names the conflicting connection in the section alert after it leaves the picker", async () => {
    let invites = [INVITE];
    asRole("admin", {
      [`GET ${URL}invites/`]: () => json(200, invites)({}),
      [`POST ${URL}invites/`]: () => {
        invites = [INVITE, DEE_INVITE];
        return json(409, {
          detail: "This user is already a member or has a pending invite.",
        })({});
      },
    });
    await open();
    expect(screen.getByRole("combobox", { name: "Connection" })).toHaveDisplayValue(/Dee Park/);

    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    expect(await within(region("Pending invites")).findByRole("alert")).toHaveTextContent(
      "Dee Park was not invited. This user is already a member or has a pending invite.",
    );
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Connection" })).toHaveDisplayValue(/Eve Moss/),
    );
  });

  it("does not claim the person was not invited after a server error", async () => {
    asRole("admin", { [`POST ${URL}invites/`]: json(500, { detail: "Something broke." }) });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    const alert = await within(region("Pending invites")).findByRole("alert");
    expect(alert).toHaveTextContent(/^Something broke\.$/);
  });

  it("does not claim the person was not invited when there was no response, and reloads", async () => {
    let invites = [INVITE];
    const backend = asRole("admin", {
      [`GET ${URL}invites/`]: () => json(200, invites)({}),
      [`POST ${URL}invites/`]: () => {
        invites = [INVITE, DEE_INVITE];
        throw new TypeError("network down");
      },
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    const alert = await within(region("Pending invites")).findByRole("alert");
    expect(alert).toHaveTextContent(/^Could not reach the backend\.$/);
    await waitFor(() =>
      expect(within(region("Pending invites")).getAllByRole("listitem")).toHaveLength(2),
    );
    expect(backend.requests(`GET ${URL}invites/`)).toHaveLength(2);
  });

  describe("when the last person leaves the picker", () => {
    function onlyDee(post: () => Response) {
      let invites = [INVITE];
      asRole("admin", {
        "GET /api/connections/": json(200, CONNECTIONS.slice(0, 3)),
        [`GET ${URL}invites/`]: () => json(200, invites)({}),
        [`POST ${URL}invites/`]: () => {
          invites = [INVITE, DEE_INVITE];
          return post();
        },
      });
    }

    it("moves focus to the alert when one is shown", async () => {
      onlyDee(() => json(409, { detail: "Already invited." })({}));
      await open();

      fireEvent.click(screen.getByRole("button", { name: "Invite" }));

      const alert = await within(region("Pending invites")).findByRole("alert");
      await waitFor(() => expect(screen.queryByRole("combobox", { name: "Connection" })).toBeNull());
      await waitFor(() => expect(alert).toHaveFocus());
    });

    it("moves focus to the empty-state paragraph otherwise", async () => {
      onlyDee(() => json(201, DEE_INVITE)({}));
      await open();

      fireEvent.click(screen.getByRole("button", { name: "Invite" }));

      const empty = await within(region("Pending invites")).findByText(/No connections to invite/);
      await waitFor(() => expect(empty).toHaveFocus());
    });
  });

  it("explains a refused invite after losing the admin role in another session", async () => {
    let role: Role = "admin";
    asRole("admin", {
      [`GET ${URL}`]: () => json(200, { id: 7, name: "Climbing Club", role })({}),
      [`GET ${URL}members/`]: () => {
        const names = [{ first_name: "Bob", last_name: "Stone" }];
        return json(200, role === "admin" ? members("admin") : names)({});
      },
      [`POST ${URL}invites/`]: () => {
        role = "member";
        return json(403, { detail: "You do not have permission to perform this action." })({});
      },
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    expect(await screen.findByText("Your role: member")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Pending invites" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "You do not have permission to perform this action.",
    );
  });

  it("revokes an invite", async () => {
    let invites = [INVITE];
    const backend = asRole("admin", {
      [`GET ${URL}invites/`]: () => json(200, invites)({}),
      "POST /api/invites/40/revoke/": () => {
        invites = [];
        return empty(204)({});
      },
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Revoke invite for (555) 223-0004" }));

    expect(await screen.findByText("No pending invites.")).toBeInTheDocument();
    expect(backend.requests("POST /api/invites/40/revoke/")).toHaveLength(1);
  });
});

describe("as an owner", () => {
  it("sets a member's role", async () => {
    const backend = asRole("owner", {
      [`PATCH ${URL}members/3/`]: json(200, { ...MIA, role: "admin" }),
    });
    await open();

    fireEvent.change(screen.getByRole("combobox", { name: "Role for Mia Lee" }), {
      target: { value: "admin" },
    });

    await waitFor(() =>
      expect(backend.requests(`PATCH ${URL}members/3/`)).toEqual([{ role: "admin" }]),
    );
  });

  it("shows why the last owner cannot step down", async () => {
    asRole("owner", {
      [`PATCH ${URL}members/1/`]: json(409, {
        detail: "An inventory must keep at least one owner.",
      }),
    });
    await open();

    fireEvent.change(screen.getByRole("combobox", { name: "Role for Ada Lovelace" }), {
      target: { value: "member" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Yes, change my role" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An inventory must keep at least one owner.",
    );
    expect(screen.getByRole("combobox", { name: "Role for Ada Lovelace" })).toHaveValue("owner");
  });

  it("clears the last owner's refusal once a later change succeeds", async () => {
    asRole("owner", {
      [`PATCH ${URL}members/1/`]: json(409, {
        detail: "An inventory must keep at least one owner.",
      }),
      [`PATCH ${URL}`]: json(200, { id: 7, name: "Bouldering", role: "owner" }),
    });
    await open();
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Ada Lovelace" }), {
      target: { value: "member" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Yes, change my role" }));
    await screen.findByText("An inventory must keep at least one owner.");

    fillIn("New name", "Bouldering");
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));

    await waitFor(() =>
      expect(screen.queryByText("An inventory must keep at least one owner.")).toBeNull(),
    );
  });

  it("clears a permission refusal once a later change succeeds", async () => {
    asRole("owner", {
      [`PATCH ${URL}members/3/`]: json(403, { detail: "You do not have permission." }),
      [`PATCH ${URL}`]: json(200, { id: 7, name: "Bouldering", role: "owner" }),
    });
    await open();
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Mia Lee" }), {
      target: { value: "admin" },
    });
    await screen.findByText("You do not have permission.");

    fillIn("New name", "Bouldering");
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));

    await waitFor(() => expect(screen.queryByText("You do not have permission.")).toBeNull());
  });

  it("drops the own-role prompt when the user stops being an owner", async () => {
    let role: Role = "owner";
    asRole("owner", {
      [`GET ${URL}`]: () => json(200, { id: 7, name: "Climbing Club", role })({}),
      [`GET ${URL}members/`]: () => json(200, members(role))({}),
      [`PATCH ${URL}members/3/`]: () => {
        role = "admin";
        return json(403, { detail: "You do not have permission." })({});
      },
    });
    await open();
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Ada Lovelace" }), {
      target: { value: "member" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Mia Lee" }), {
      target: { value: "admin" },
    });

    expect(await screen.findByText("Your role: admin")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Yes, change my role" })).toBeNull();
  });

  it("moves focus to the own-role question and the delete question", async () => {
    asRole("owner");
    await open();

    fireEvent.change(screen.getByRole("combobox", { name: "Role for Ada Lovelace" }), {
      target: { value: "member" },
    });
    expect(screen.getByText(/Change your role to member\?/)).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Delete inventory" }));
    expect(screen.getByText(/Delete Climbing Club\?/)).toHaveFocus();
  });

  it("changes their own role only after confirming", async () => {
    const backend = asRole("owner", {
      [`PATCH ${URL}members/1/`]: json(200, { ...ADA, role: "admin" }),
    });
    await open();
    const own = () => screen.getByRole("combobox", { name: "Role for Ada Lovelace" });

    fireEvent.change(own(), { target: { value: "member" } });
    expect(
      screen.getByText(/Change your role to member\? You will no longer be an owner\./),
    ).toBeInTheDocument();
    expect(own()).toHaveValue("owner");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Yes, change my role" })).toBeNull();
    expect(backend.requests(`PATCH ${URL}members/1/`)).toHaveLength(0);

    fireEvent.change(own(), { target: { value: "admin" } });
    fireEvent.click(screen.getByRole("button", { name: "Yes, change my role" }));

    await waitFor(() =>
      expect(backend.requests(`PATCH ${URL}members/1/`)).toEqual([{ role: "admin" }]),
    );
  });

  it("removes another member, but offers no Remove for themselves", async () => {
    const backend = asRole("owner", { [`DELETE ${URL}members/2/`]: empty(204) });
    await open();

    expect(screen.queryByRole("button", { name: "Remove Ada Lovelace" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remove Bob Stone" }));

    await waitFor(() => expect(backend.requests(`DELETE ${URL}members/2/`)).toHaveLength(1));
  });

  it("renames the inventory", async () => {
    let name = "Climbing Club";
    const backend = asRole("owner", {
      [`GET ${URL}`]: () => json(200, { id: 7, name, role: "owner" })({}),
      [`PATCH ${URL}`]: () => {
        name = "Bouldering";
        return json(200, { id: 7, name, role: "owner" })({});
      },
    });
    await open();

    fillIn("New name", "Bouldering");
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));

    expect(await screen.findByRole("heading", { name: "Bouldering" })).toBeInTheDocument();
    expect(backend.requests(`PATCH ${URL}`)).toEqual([{ name: "Bouldering" }]);
  });

  it("clears the rename errors when another change is sent from the page", async () => {
    asRole("owner", {
      [`PATCH ${URL}`]: json(400, { name: ["Ensure this field has no more than 32 characters."] }),
      [`PATCH ${URL}members/3/`]: json(200, { ...MIA, role: "admin" }),
    });
    await open();
    fillIn("New name", "x".repeat(33));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    await screen.findByText("Ensure this field has no more than 32 characters.");

    fireEvent.change(screen.getByRole("combobox", { name: "Role for Mia Lee" }), {
      target: { value: "admin" },
    });

    await waitFor(() =>
      expect(screen.queryByText("Ensure this field has no more than 32 characters.")).toBeNull(),
    );
    expect(screen.getByLabelText("New name")).toBeValid();
  });

  it("shows no message for an older change whose reply comes after a later one", async () => {
    const remove = held();
    const backend = asRole("owner", {
      [`DELETE ${URL}members/2/`]: remove.route,
      [`PATCH ${URL}members/3/`]: json(200, { ...MIA, role: "admin" }),
    });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Remove Bob Stone" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Role for Mia Lee" }), {
      target: { value: "admin" },
    });
    await waitFor(() =>
      expect(backend.keys().filter((key) => key === `GET ${URL}`)).toHaveLength(2),
    );

    remove.respond(json(409, { detail: "Bob has items on loan here." }));

    await waitFor(() =>
      expect(backend.keys().filter((key) => key === `GET ${URL}`)).toHaveLength(3),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("Bob has items on loan here.")).toBeNull();
  });

  it("deletes the inventory only after confirming, then goes home", async () => {
    const backend = asRole("owner", { [`DELETE ${URL}`]: empty(204) });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Delete inventory" }));
    expect(screen.getByText(/Delete Climbing Club\? This cannot be undone\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(backend.requests(`DELETE ${URL}`)).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Delete inventory" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));

    expect(await screen.findByRole("heading", { name: "My inventories" })).toBeInTheDocument();
    expect(backend.requests(`DELETE ${URL}`)).toHaveLength(1);
  });
});

describe("items", () => {
  const ROPE: ListedItem = {
    id: 20,
    name: "Rope",
    description: "60 m dynamic",
    owner: { first_name: "Ada", last_name: "Lovelace" },
    ...AVAILABLE,
  };
  const TENT: ListedItem = {
    id: 21,
    name: "Tent",
    description: "",
    owner: { first_name: "Bob", last_name: "Stone" },
    ...AVAILABLE,
  };
  const HELMET = { id: 23, name: "Helmet", description: "", inventories: [] };
  // What listing the helmet returns.
  const LISTED_HELMET: ListedItem = {
    id: HELMET.id,
    name: HELMET.name,
    description: HELMET.description,
    owner: ROPE.owner,
    ...AVAILABLE,
  };
  // The caller's own items: the rope is listed here, the axe and the helmet are not.
  const MY_ITEMS = [
    { id: 22, name: "Axe", description: "", inventories: [] },
    HELMET,
    {
      id: ROPE.id,
      name: ROPE.name,
      description: ROPE.description,
      inventories: [{ id: 7, name: "Climbing Club" }],
    },
  ];

  function withItems(role: Role, routes: Routes = {}) {
    return asRole(role, {
      [`GET ${URL}items/`]: json(200, [ROPE, TENT]),
      "GET /api/items/": json(200, MY_ITEMS),
      ...(role === "member" ? { [`GET ${URL}members/`]: json(200, []) } : {}),
      ...routes,
    });
  }

  function itemTexts() {
    return within(region("Items"))
      .getAllByRole("listitem")
      .map((item) => item.firstChild?.textContent);
  }

  function pickerOptions() {
    const picker = screen.getByRole("combobox", { name: "Item" });
    return within(picker).getAllByRole("option").map((option) => option.textContent);
  }

  it("shows a member every listed item with its owner, and nothing to change", async () => {
    const backend = withItems("member");

    await open();

    expect(itemTexts()).toEqual([
      "Rope: 60 m dynamic, owned by Ada Lovelace",
      "Tent, owned by Bob Stone",
    ]);
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Item" })).toBeNull();
    expect(backend.requests("GET /api/items/")).toHaveLength(0);
  });

  it("says so when nothing is listed", async () => {
    asRole("member", { [`GET ${URL}members/`]: json(200, []) });

    await open();

    expect(within(region("Items")).getByText("No items listed yet.")).toBeInTheDocument();
  });

  it("lets an admin remove only their own items", async () => {
    withItems("admin");

    await open();

    expect(screen.getByRole("button", { name: "Remove Rope from the inventory" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Remove Tent from the inventory" })).toBeNull();
  });

  it("lets an owner remove any item, and reloads", async () => {
    let listed = [ROPE, TENT];
    const backend = withItems("owner", {
      [`GET ${URL}items/`]: () => json(200, listed)({}),
      [`DELETE ${URL}items/21/`]: () => {
        listed = [ROPE];
        return empty(204)({});
      },
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Remove Tent from the inventory" }));

    await waitFor(() =>
      expect(itemTexts()).toEqual(["Rope: 60 m dynamic, owned by Ada Lovelace"]),
    );
    expect(backend.requests(`DELETE ${URL}items/21/`)).toHaveLength(1);
  });

  it("offers an admin only their own items that are not listed here", async () => {
    withItems("admin");

    await open();

    expect(pickerOptions()).toEqual(["Axe", "Helmet"]);
  });

  it("tells apart two of the caller's items with the same name by their descriptions", async () => {
    withItems("admin", {
      "GET /api/items/": json(200, [
        { id: 30, name: "Stove", description: "gas", inventories: [] },
        { id: 31, name: "Stove", description: "", inventories: [] },
      ]),
    });

    await open();

    expect(pickerOptions()).toEqual(["Stove: gas", "Stove"]);
  });

  it("lists the chosen item and reloads the items and the picker", async () => {
    let listed = [ROPE, TENT];
    const backend = withItems("admin", {
      [`GET ${URL}items/`]: () => json(200, listed)({}),
      [`POST ${URL}items/`]: () => {
        listed = [LISTED_HELMET, ROPE, TENT];
        return json(201, LISTED_HELMET)({});
      },
    });
    await open();

    fireEvent.change(screen.getByRole("combobox", { name: "Item" }), { target: { value: "23" } });
    fireEvent.click(screen.getByRole("button", { name: "List item" }));

    await waitFor(() => expect(itemTexts()).toHaveLength(3));
    expect(backend.requests(`POST ${URL}items/`)).toEqual([{ item_id: 23 }]);
    expect(pickerOptions()).toEqual(["Axe"]);
  });

  it("names a refused item in the section alert", async () => {
    withItems("admin", {
      [`POST ${URL}items/`]: json(409, {
        detail: "This item is already listed in this inventory.",
      }),
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "List item" }));

    expect(await within(region("Items")).findByRole("alert")).toHaveTextContent(
      '"Axe" was not listed. This item is already listed in this inventory.',
    );
  });

  it("names a refused item the way its option is labelled", async () => {
    withItems("admin", {
      "GET /api/items/": json(200, [
        { id: 30, name: "Stove", description: "gas", inventories: [] },
        { id: 31, name: "Stove", description: "", inventories: [] },
      ]),
      [`POST ${URL}items/`]: json(409, { detail: "Not today." }),
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "List item" }));

    expect(await within(region("Items")).findByRole("alert")).toHaveTextContent(
      '"Stove: gas" was not listed. Not today.',
    );
  });

  it("clears an invite refusal when another action on the page succeeds", async () => {
    withItems("admin", {
      [`POST ${URL}invites/`]: json(400, { user_id: ["You can invite only your connections."] }),
      [`POST ${URL}items/`]: json(201, LISTED_HELMET),
    });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Invite" }));
    expect(await within(region("Pending invites")).findByRole("alert")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "List item" }));

    await waitFor(() => expect(within(region("Pending invites")).queryByRole("alert")).toBeNull());
  });

  it.each([
    ["every item is listed here", [MY_ITEMS[2]]],
    ["the user has no items", []],
  ])("links to My items when %s", async (_, mine) => {
    withItems("admin", { "GET /api/items/": json(200, mine) });

    await open();

    const items = region("Items");
    expect(within(items).getByText(/No items to list\./)).toBeInTheDocument();
    expect(within(items).getByRole("link", { name: "My items" })).toHaveAttribute(
      "href",
      "/manage/items",
    );
    expect(screen.queryByRole("combobox", { name: "Item" })).toBeNull();
  });

  it("moves focus to the empty-state paragraph when the last item is listed", async () => {
    let listed = [ROPE, TENT];
    withItems("admin", {
      "GET /api/items/": json(200, [HELMET, MY_ITEMS[2]]),
      [`GET ${URL}items/`]: () => json(200, listed)({}),
      [`POST ${URL}items/`]: () => {
        listed = [LISTED_HELMET, ROPE, TENT];
        return json(201, listed[0])({});
      },
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "List item" }));

    const empty = await within(region("Items")).findByText(/No items to list/);
    await waitFor(() => expect(empty).toHaveFocus());
  });
});

describe("borrowing", () => {
  const BOBS = { first_name: "Bob", last_name: "Stone" };
  const ROPE: ListedItem = { id: 20, name: "Rope", description: "", owner: BOBS, ...AVAILABLE };
  const TENT: ListedItem = { ...ROPE, id: 21, name: "Tent", loan_status: "requested" };
  const STOVE: ListedItem = { ...ROPE, id: 22, name: "Stove", loan_status: "on_loan" };
  const MIAS_PHONE = "(555) 223-0003";

  function withListed(role: Role, listed: () => ListedItem[], routes: Routes = {}) {
    return asRole(role, {
      [`GET ${URL}items/`]: () => json(200, listed())({}),
      ...(role === "member" ? { [`GET ${URL}members/`]: json(200, []) } : {}),
      ...routes,
    });
  }

  function itemFor(name: string) {
    const items = within(region("Items")).getAllByRole("listitem");
    const found = items.find((item) => item.firstChild?.textContent?.startsWith(name));
    if (!found) throw new Error(`No item ${name}`);
    return found;
  }

  function buttonNames() {
    return within(region("Items"))
      .queryAllByRole("button")
      .map((button) => button.getAttribute("aria-label") ?? button.textContent);
  }

  describe("as a member", () => {
    it("shows each item's status, and Ask to borrow only on available items", async () => {
      withListed("member", () => [ROPE, STOVE, TENT]);

      await open();

      expect(within(itemFor("Rope")).getByText("Available")).toBeVisible();
      expect(within(itemFor("Tent")).getByText("Requested")).toBeVisible();
      expect(within(itemFor("Stove")).getByText("On loan")).toBeVisible();
      expect(buttonNames()).toEqual(["Ask to borrow: Rope"]);
      expect(screen.getByRole("button", { name: "Ask to borrow: Rope" })).toHaveTextContent(
        /^Ask to borrow$/,
      );
    });

    it("requests an item, reloads, and then offers Cancel", async () => {
      let rope = ROPE;
      const backend = withListed("member", () => [rope], {
        [`POST ${URL}items/20/borrow/`]: () => {
          rope = { ...ROPE, loan_status: "requested", borrowed_by_me: true };
          return empty(204)({});
        },
      });
      await open();

      fireEvent.click(screen.getByRole("button", { name: "Ask to borrow: Rope" }));

      expect(await within(itemFor("Rope")).findByText("Waiting for approval")).toBeVisible();
      expect(buttonNames()).toEqual(["Cancel request: Rope"]);
      expectLabelsInNames(region("Items"));
      expect(backend.requests(`POST ${URL}items/20/borrow/`)).toEqual([undefined]);
    });

    it("cancels their own pending request and reloads", async () => {
      let rope: ListedItem = { ...ROPE, loan_status: "requested", borrowed_by_me: true };
      const backend = withListed("member", () => [rope], {
        "POST /api/borrowing/20/cancel/": () => {
          rope = ROPE;
          return empty(204)({});
        },
      });
      await open();

      fireEvent.click(screen.getByRole("button", { name: "Cancel request: Rope" }));

      expect(await within(itemFor("Rope")).findByText("Available")).toBeVisible();
      expect(backend.requests("POST /api/borrowing/20/cancel/")).toEqual([undefined]);
    });

    it("shows why a request was refused", async () => {
      withListed("member", () => [ROPE], {
        [`POST ${URL}items/20/borrow/`]: json(409, {
          detail: "This item has already been requested or is on loan.",
        }),
      });
      await open();

      fireEvent.click(screen.getByRole("button", { name: "Ask to borrow: Rope" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "This item has already been requested or is on loan.",
      );
    });

    it("shows their own loan with nothing to do", async () => {
      withListed("member", () => [{ ...STOVE, borrowed_by_me: true }]);

      await open();

      expect(within(itemFor("Stove")).getByText("Borrowed by you")).toBeVisible();
      expect(buttonNames()).toEqual([]);
    });
  });

  describe("as an admin", () => {
    const THROUGH_HERE = { borrower: MIA };
    // On loan through another inventory, so the admin sees no borrower.
    const LAMP: ListedItem = { ...STOVE, id: 23, name: "Lamp" };

    it("shows the requester or borrower of a loan through this inventory, with their phone number", async () => {
      withListed("admin", () => [
        LAMP,
        { ...STOVE, ...THROUGH_HERE },
        { ...TENT, ...THROUGH_HERE },
      ]);

      await open();

      const tent = within(itemFor("Tent"));
      expect(tent.getByText(`Requested by Mia Lee, ${MIAS_PHONE}`)).toBeVisible();
      const stove = within(itemFor("Stove"));
      expect(stove.getByText(`On loan to Mia Lee, ${MIAS_PHONE}`)).toBeVisible();
      expect(within(itemFor("Lamp")).getByText("On loan")).toBeVisible();
      expect(buttonNames()).toEqual([
        "Mark returned: Stove",
        "Approve: Tent",
        "Decline: Tent",
      ]);
      expectLabelsInNames(region("Items"));
    });

    it.each([
      ["Approve: Tent", "approve", "on_loan"],
      ["Decline: Tent", "decline", "available"],
    ] as const)("%s sends the requester it showed and reloads", async (button, action, after) => {
      let tent: ListedItem = { ...TENT, ...THROUGH_HERE };
      const backend = withListed("admin", () => [tent], {
        [`POST ${URL}items/21/${action}/`]: () => {
          tent = { ...TENT, loan_status: after, borrower: after === "on_loan" ? MIA : null };
          return empty(204)({});
        },
      });
      await open();

      fireEvent.click(screen.getByRole("button", { name: button }));

      await waitFor(() =>
        expect(screen.queryByRole("button", { name: button })).toBeNull(),
      );
      expect(backend.requests(`POST ${URL}items/21/${action}/`)).toEqual([{ borrower_id: MIA.id }]);
    });

    it("marks an item on loan through this inventory returned and reloads", async () => {
      let stove: ListedItem = { ...STOVE, ...THROUGH_HERE };
      const backend = withListed("admin", () => [stove], {
        [`POST ${URL}items/22/return/`]: () => {
          stove = { ...STOVE, loan_status: "available" };
          return empty(204)({});
        },
      });
      await open();

      fireEvent.click(screen.getByRole("button", { name: "Mark returned: Stove" }));

      expect(await within(itemFor("Stove")).findByText("Available")).toBeVisible();
      expect(backend.requests(`POST ${URL}items/22/return/`)).toEqual([{ borrower_id: MIA.id }]);
    });

    it("shows why an approval was refused", async () => {
      withListed("admin", () => [{ ...TENT, ...THROUGH_HERE }], {
        [`POST ${URL}items/21/approve/`]: json(409, {
          detail: "This request or loan changed. Try again.",
        }),
      });
      await open();

      fireEvent.click(screen.getByRole("button", { name: "Approve: Tent" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "This request or loan changed. Try again.",
      );
    });

    it("offers Done using it, not Approve, Decline or Mark returned, on their own", async () => {
      const mine = { borrower: ADA, borrowed_by_me: true };
      withListed("admin", () => [
        { ...STOVE, ...mine },
        { ...TENT, ...mine },
        // Held through another inventory: no borrower is shown here.
        { ...LAMP, borrowed_by_me: true },
      ]);

      await open();

      expect(within(itemFor("Tent")).getByText("Waiting for approval")).toBeVisible();
      expect(within(itemFor("Stove")).getByText("In use by you")).toBeVisible();
      expect(within(itemFor("Lamp")).getByText("Borrowed by you")).toBeVisible();
      expect(buttonNames()).toEqual(["Done using it: Stove", "Cancel request: Tent"]);
    });

    it("says In use by you for a use through another inventory, Borrowed by you for a loan", async () => {
      const held = { ...LAMP, borrowed_by_me: true };
      withListed("admin", () => [held, { ...STOVE, borrowed_by_me: true }], {
        "GET /api/borrowing/": json(200, [
          { id: 23, loan_status: "on_loan", can_return: true },
          { id: 22, loan_status: "on_loan", can_return: false },
        ]),
      });

      await open();

      expect(within(itemFor("Lamp")).getByText("In use by you")).toBeVisible();
      expect(within(itemFor("Stove")).getByText("Borrowed by you")).toBeVisible();
      expect(buttonNames()).toEqual([]);
    });

    it("uses someone else's item without a request, then is done using it", async () => {
      let rope = ROPE;
      const backend = withListed("admin", () => [rope], {
        [`POST ${URL}items/20/borrow/`]: () => {
          rope = { ...ROPE, loan_status: "on_loan", borrowed_by_me: true, borrower: ADA };
          return empty(204)({});
        },
        [`POST ${URL}items/20/return/`]: () => {
          rope = ROPE;
          return empty(204)({});
        },
      });
      await open();
      expect(buttonNames()).toEqual(["Use it myself: Rope"]);
      const button = screen.getByRole("button", { name: "Use it myself: Rope" });
      expect(button).toHaveTextContent(/^Use it myself$/);

      fireEvent.click(button);

      expect(await within(itemFor("Rope")).findByText("In use by you")).toBeVisible();
      expect(buttonNames()).toEqual(["Done using it: Rope"]);
      expect(screen.getByRole("button", { name: "Done using it: Rope" })).toBe(button);
      expect(button).toHaveTextContent(/^Done using it$/);
      expect(backend.requests(`POST ${URL}items/20/borrow/`)).toEqual([undefined]);

      fireEvent.click(screen.getByRole("button", { name: "Done using it: Rope" }));

      expect(await within(itemFor("Rope")).findByText("Available")).toBeVisible();
      expect(backend.requests(`POST ${URL}items/20/return/`)).toEqual([{ borrower_id: ADA.id }]);
    });

    describe("on their own items", () => {
      const MY_ROPE = {
        id: ROPE.id,
        name: ROPE.name,
        description: "",
        inventories: [{ id: 7, name: "Climbing Club" }],
        loan_status: "available",
        borrower: null,
        loan_inventory: null,
      };

      it("uses it as its owner, then is done using it", async () => {
        let rope: ListedItem = ROPE;
        const backend = withListed("admin", () => [rope], {
          "GET /api/items/": json(200, [MY_ROPE]),
          "POST /api/items/20/use/": () => {
            rope = { ...ROPE, loan_status: "on_loan", borrowed_by_me: true };
            return empty(204)({});
          },
          "POST /api/items/20/return/": () => {
            rope = ROPE;
            return empty(204)({});
          },
        });
        await open();
        expect(buttonNames()).toEqual(["Use it myself: Rope", "Remove Rope from the inventory"]);

        fireEvent.click(screen.getByRole("button", { name: "Use it myself: Rope" }));

        expect(await within(itemFor("Rope")).findByText("In use by you")).toBeVisible();
        expect(backend.requests("POST /api/items/20/use/")).toEqual([undefined]);

        fireEvent.click(screen.getByRole("button", { name: "Done using it: Rope" }));

        expect(await within(itemFor("Rope")).findByText("Available")).toBeVisible();
        expect(backend.requests("POST /api/items/20/return/")).toEqual([
          { borrower_id: ADA.id },
        ]);
        expect(backend.requests(`POST ${URL}items/20/borrow/`)).toHaveLength(0);
      });
    });
  });
});

describe("leaving", () => {
  it("removes the user's own membership and goes home", async () => {
    const backend = asRole("admin", { [`DELETE ${URL}members/1/`]: empty(204) });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Leave inventory" }));

    expect(await screen.findByRole("heading", { name: "My inventories" })).toBeInTheDocument();
    expect(backend.requests(`DELETE ${URL}members/1/`)).toHaveLength(1);
  });

  it("stays and explains when the last owner tries to leave", async () => {
    asRole("owner", {
      [`DELETE ${URL}members/1/`]: json(409, {
        detail: "An inventory must keep at least one owner.",
      }),
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Leave inventory" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An inventory must keep at least one owner.",
    );
    expect(screen.getByRole("heading", { name: "Climbing Club" })).toBeInTheDocument();
  });
});

describe("loading", () => {
  it("shows a not-found message for an inventory the user cannot see", async () => {
    fakeBackend({
      "GET /api/auth/me/": json(200, ADA),
      [`GET ${URL}`]: json(404, { detail: "Inventory not found." }),
    });

    renderAt("/inventories/7");

    expect(await screen.findByText("Inventory not found.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to my inventories" })).toHaveAttribute(
      "href",
      "/manage/inventories",
    );
  });

  it("shows not-found for an id that is not a number, without calling the API", async () => {
    const backend = fakeBackend({ "GET /api/auth/me/": json(200, ADA) });

    renderAt("/inventories/2%3Fx%3D");

    expect(await screen.findByText("Inventory not found.")).toBeInTheDocument();
    expect(backend.requests("GET /api/inventories/2?x=/")).toHaveLength(0);
  });

  it("shows an error when the backend cannot be reached", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA) });

    renderAt("/inventories/7");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the inventory.");
  });
});
