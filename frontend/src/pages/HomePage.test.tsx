import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ADA, empty, fakeBackend, json } from "../test-backend";
import { fillIn, renderAt } from "../test-render";

const CLIMBING = { id: 7, name: "Climbing Club", role: "owner" };
const CAMPING = { id: 8, name: "Camping Crew", role: "member" };
const INVITE = {
  id: 30,
  inventory_name: "Camping Crew",
  invited_by: { first_name: "Sam", last_name: "Okafor" },
};

function signedIn(routes: Parameters<typeof fakeBackend>[0] = {}) {
  return fakeBackend({ "GET /api/auth/me/": json(200, ADA), ...routes });
}

function section(name: string) {
  return screen.getByRole("region", { name });
}

describe("my inventories", () => {
  it("lists each inventory with the user's role and a link to its page", async () => {
    signedIn({ "GET /api/inventories/": json(200, [CLIMBING, CAMPING]) });

    renderAt("/");

    const link = await screen.findByRole("link", { name: "Climbing Club" });
    expect(link).toHaveAttribute("href", "/inventories/7");
    const items = within(section("My inventories")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Climbing Club (owner)",
      "Camping Crew (member)",
    ]);
    expect(screen.getByText("Signed in as Ada Lovelace")).toBeInTheDocument();
  });

  it("links to My gear and My connections", async () => {
    signedIn();

    renderAt("/");

    expect(await screen.findByRole("link", { name: "My gear" })).toHaveAttribute("href", "/gear");
    expect(screen.getByRole("link", { name: "My connections" })).toHaveAttribute(
      "href",
      "/connections",
    );
  });

  it("says so when the user has no inventories or invites", async () => {
    signedIn();

    renderAt("/");

    expect(await screen.findByText("You are not in any inventory yet.")).toBeInTheDocument();
    expect(screen.getByText("No pending invites.")).toBeInTheDocument();
  });

  it("shows an error when the lists cannot be loaded", async () => {
    signedIn({ "GET /api/inventories/": json(500, {}) });

    renderAt("/");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load your inventories.",
    );
  });

  it("creates an inventory and opens its page", async () => {
    const backend = signedIn({
      "POST /api/inventories/": json(201, { id: 9, name: "Kayaks", role: "owner" }),
      "GET /api/inventories/9/": json(200, { id: 9, name: "Kayaks", role: "owner" }),
      "GET /api/inventories/9/members/": json(200, []),
      "GET /api/inventories/9/invites/": json(200, []),
      "GET /api/inventories/9/items/": json(200, []),
    });
    renderAt("/");
    await screen.findByText("You are not in any inventory yet.");

    fillIn("Inventory name", "Kayaks");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByRole("heading", { name: "Kayaks" })).toBeInTheDocument();
    expect(backend.requests("POST /api/inventories/")).toEqual([{ name: "Kayaks" }]);
  });

  it("shows a name error next to the name field", async () => {
    signedIn({
      "POST /api/inventories/": json(400, { name: ["This field may not be blank."] }),
    });
    renderAt("/");
    await screen.findByText("You are not in any inventory yet.");

    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    const name = screen.getByLabelText("Inventory name");
    await waitFor(() => expect(name).toHaveAccessibleDescription("This field may not be blank."));
    await waitFor(() => expect(name).toHaveFocus());
  });
});

describe("pending invites", () => {
  it("shows the inventory's name and who sent the invite", async () => {
    signedIn({ "GET /api/invites/": json(200, [INVITE]) });

    renderAt("/");

    expect(await screen.findByText("Camping Crew, from Sam Okafor")).toBeInTheDocument();
  });

  it("accepting joins the inventory and reloads both lists", async () => {
    let invites = [INVITE];
    let inventories: (typeof CAMPING)[] = [];
    const backend = signedIn({
      "GET /api/invites/": () => json(200, invites)({}),
      "GET /api/inventories/": () => json(200, inventories)({}),
      "POST /api/invites/30/accept/": () => {
        invites = [];
        inventories = [CAMPING];
        return json(200, CAMPING)({});
      },
    });
    renderAt("/");

    fireEvent.click(await screen.findByRole("button", { name: "Accept invite to Camping Crew" }));

    expect(await screen.findByRole("link", { name: "Camping Crew" })).toBeInTheDocument();
    expect(screen.getByText("No pending invites.")).toBeInTheDocument();
    expect(backend.requests("POST /api/invites/30/accept/")).toHaveLength(1);
  });

  it("declining removes the invite", async () => {
    let invites = [INVITE];
    const backend = signedIn({
      "GET /api/invites/": () => json(200, invites)({}),
      "POST /api/invites/30/decline/": () => {
        invites = [];
        return empty(204)({});
      },
    });
    renderAt("/");

    fireEvent.click(await screen.findByRole("button", { name: "Decline invite to Camping Crew" }));

    expect(await screen.findByText("No pending invites.")).toBeInTheDocument();
    expect(backend.requests("POST /api/invites/30/decline/")).toHaveLength(1);
  });

  it("shows why an invite could not be accepted", async () => {
    signedIn({
      "GET /api/invites/": json(200, [INVITE]),
      "POST /api/invites/30/accept/": json(404, { detail: "Invite not found." }),
    });
    renderAt("/");

    fireEvent.click(await screen.findByRole("button", { name: "Accept invite to Camping Crew" }));

    expect(await within(section("Invites")).findByRole("alert")).toHaveTextContent(
      "Invite not found.",
    );
  });
});
