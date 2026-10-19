import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ADA, empty, fakeBackend, json } from "../test-backend";
import { fillIn, renderAt } from "../test-render";

type Routes = Parameters<typeof fakeBackend>[0];
type Role = "member" | "admin" | "owner";

const URL = "/api/inventories/7/";
const PHONE_NUMBER = /\(?[0-9]{3}\)? ?[0-9]{3}-?[0-9]{4}/;

const BOB = { id: 2, first_name: "Bob", last_name: "Stone", phone_number: "5551230002" };
const MIA = { id: 3, first_name: "Mia", last_name: "Lee", phone_number: "5551230003" };
const INVITE = {
  id: 40,
  invitee: { phone_number: "5551230004" },
  invited_by: { first_name: "Bob", last_name: "Stone" },
};

// Accepted connections of the caller: Bob is a member, Cal has the pending invite, and
// Dee and Eve can be invited.
const CONNECTIONS = [
  BOB,
  { id: 4, first_name: "Cal", last_name: "Reyes", phone_number: "5551230004" },
  { id: 5, first_name: "Dee", last_name: "Park", phone_number: "5551230005" },
  { id: 6, first_name: "Eve", last_name: "Moss", phone_number: "5551230006" },
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
    { first_name: "Olive", last_name: "Grant", phone_number: "5551230009" },
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
      "Ada Lovelace(555) 123-4567admin",
      "Bob Stone(555) 123-0002admin",
      "Mia Lee(555) 123-0003member",
    ]);
    expect(within(region("Pending invites")).getByText(/123-0004/)).toHaveTextContent(
      "(555) 123-0004, invited by Bob Stone",
    );
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
      "Dee Park, (555) 123-0005",
      "Eve Moss, (555) 123-0006",
    ]);
  });

  it("invites the chosen connection and reloads the invites and the picker", async () => {
    const EVE_INVITE = { ...INVITE, id: 41, invitee: { phone_number: "5551230006" } };
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
      "Dee Park, (555) 123-0005",
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
    expect(screen.queryByRole("combobox", { name: "Connection" })).toBeNull();
  });

  it("names the conflicting connection in the section alert after it leaves the picker", async () => {
    let connections = CONNECTIONS;
    asRole("admin", {
      "GET /api/connections/": () => json(200, connections)({}),
      [`POST ${URL}invites/`]: () => {
        connections = CONNECTIONS.filter(({ user }) => user.id !== 5);
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
    expect(screen.getByRole("combobox", { name: "Connection" })).toHaveDisplayValue(/Eve Moss/);
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

    fireEvent.click(screen.getByRole("button", { name: "Revoke invite for (555) 123-0004" }));

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
    expect(screen.getByRole("link", { name: "Go home" })).toHaveAttribute("href", "/");
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
