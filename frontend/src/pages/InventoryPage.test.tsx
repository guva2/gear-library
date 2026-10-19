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
  });

  it("offers only Leave", async () => {
    asRole("member", { [`GET ${URL}members/`]: json(200, NAMES) });

    await open();

    expect(screen.getByRole("button", { name: "Leave inventory" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Phone number")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove|Rename|Delete|Revoke/ })).toBeNull();
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

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove|Rename|Delete/ })).toBeNull();
  });

  it("invites by phone number and reloads the pending invites", async () => {
    let invites: (typeof INVITE)[] = [];
    const backend = asRole("admin", {
      [`GET ${URL}invites/`]: () => json(200, invites)({}),
      [`POST ${URL}invites/`]: () => {
        invites = [INVITE];
        return json(201, INVITE)({});
      },
    });
    await open();

    fillIn("Phone number", "(555) 123-0004");
    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    expect(await within(region("Pending invites")).findByText(/123-0004/)).toBeInTheDocument();
    expect(backend.requests(`POST ${URL}invites/`)).toEqual([{ phone_number: "(555) 123-0004" }]);
    expect(screen.getByLabelText("Phone number")).toHaveValue("");
  });

  it("shows an unknown number next to the phone number field", async () => {
    asRole("admin", {
      [`POST ${URL}invites/`]: json(400, { phone_number: ["No user has this phone number."] }),
    });
    await open();

    fillIn("Phone number", "5559999999");
    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    const phone = screen.getByLabelText("Phone number");
    await waitFor(() =>
      expect(phone).toHaveAccessibleDescription("No user has this phone number."),
    );
  });

  it("shows a conflict for the whole invite form", async () => {
    asRole("admin", {
      [`POST ${URL}invites/`]: json(409, { detail: "This user is already a member." }),
    });
    await open();

    fillIn("Phone number", "5551230003");
    fireEvent.click(screen.getByRole("button", { name: "Invite" }));

    expect(await within(region("Pending invites")).findByRole("alert")).toHaveTextContent(
      "This user is already a member.",
    );
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

    fillIn("Phone number", "5551230004");
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
