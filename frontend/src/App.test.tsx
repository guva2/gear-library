import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ADA, empty, fakeBackend, json } from "./test-backend";
import { fillIn, renderAt } from "./test-render";

const ANONYMOUS = json(403, { detail: "Authentication credentials were not provided." });

describe("home page", () => {
  it("shows who is signed in, with no health line", async () => {
    const backend = fakeBackend({ "GET /api/auth/me/": json(200, ADA) });

    renderAt("/");

    expect(await screen.findByText("Signed in as Ada Lovelace")).toBeInTheDocument();
    await screen.findByRole("heading", { name: "Discover" });
    expect(screen.queryByRole("status")).toBeNull();
    expect(backend.requests("GET /api/health/")).toHaveLength(0);
  });

  it("sends an anonymous user to the login page", async () => {
    fakeBackend({ "GET /api/auth/me/": ANONYMOUS });

    renderAt("/");

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("logs out and goes to the login page", async () => {
    const backend = fakeBackend({
      "GET /api/auth/me/": json(200, ADA),
      "POST /api/auth/logout/": empty(204),
    });
    renderAt("/");

    fireEvent.click(await screen.findByRole("button", { name: "Log out" }));

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(backend.requests("POST /api/auth/logout/")).toHaveLength(1);
  });

  it("stays signed in when logging out fails", async () => {
    fakeBackend({
      "GET /api/auth/me/": json(200, ADA),
      "POST /api/auth/logout/": json(403, { detail: "CSRF Failed: CSRF token missing." }),
    });
    renderAt("/");

    fireEvent.click(await screen.findByRole("button", { name: "Log out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("CSRF Failed");
    expect(screen.getByText("Signed in as Ada Lovelace")).toBeInTheDocument();
  });
});

describe("logout from a stale tab", () => {
  it("goes to the login page when the session is already gone", async () => {
    fakeBackend({
      "GET /api/auth/me/": json(200, ADA),
      "POST /api/auth/logout/": ANONYMOUS,
    });
    renderAt("/");

    fireEvent.click(await screen.findByRole("button", { name: "Log out" }));

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByText("Signed in as Ada Lovelace")).not.toBeInTheDocument();
  });
});

describe("login page", () => {
  it("logs in and shows the home page", async () => {
    fakeBackend({ "GET /api/auth/me/": ANONYMOUS, "POST /api/auth/login/": json(200, ADA) });
    renderAt("/");

    await screen.findByRole("heading", { name: "Log in" });
    fillIn("Phone number", "5551234567");
    fillIn("Password", "correct-horse-battery");
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByText("Signed in as Ada Lovelace")).toBeInTheDocument();
  });

  it("shows the wrong-credentials message for the whole form", async () => {
    fakeBackend({
      "POST /api/auth/login/": json(400, {
        non_field_errors: ["Wrong phone number or password."],
      }),
    });
    renderAt("/login");

    fillIn("Phone number", "5551234567");
    fillIn("Password", "wrong");
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Wrong phone number or password.",
    );
    expect(screen.getByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("shows a repeated form error in a new alert element", async () => {
    fakeBackend({
      "POST /api/auth/login/": json(400, {
        non_field_errors: ["Wrong phone number or password."],
      }),
    });
    renderAt("/login");

    fillIn("Phone number", "5551234567");
    fillIn("Password", "wrong");
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    const first = await screen.findByRole("alert");

    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => expect(screen.getByRole("alert")).not.toBe(first));
    expect(screen.getByRole("alert")).toHaveTextContent("Wrong phone number or password.");
  });

  it("shows a phone number error next to the phone number field", async () => {
    fakeBackend({
      "POST /api/auth/login/": json(400, { phone_number: ["Enter a US phone number."] }),
    });
    renderAt("/login");

    fillIn("Phone number", "555");
    fillIn("Password", "pw");
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    const phone = screen.getByLabelText("Phone number");
    expect(await screen.findByText("Enter a US phone number.")).toBeInTheDocument();
    expect(phone).toHaveAccessibleDescription("Enter a US phone number.");
    expect(phone).toBeInvalid();
    expect(screen.getByLabelText("Password")).toBeValid();
  });

  it("links to the register page", async () => {
    fakeBackend({});
    renderAt("/login");

    fireEvent.click(screen.getByRole("link", { name: "Create an account" }));

    expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument();
  });
});

describe("register page", () => {
  it("creates the account and shows the home page", async () => {
    const backend = fakeBackend({ "POST /api/auth/register/": json(201, ADA) });
    renderAt("/register");

    fillIn("Phone number", "(555) 123-4567");
    fillIn("First name", "Ada");
    fillIn("Last name", "Lovelace");
    fillIn("Password", "correct-horse-battery");
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Signed in as Ada Lovelace")).toBeInTheDocument();
    expect(backend.requests("POST /api/auth/register/")).toEqual([
      {
        phone_number: "(555) 123-4567",
        first_name: "Ada",
        last_name: "Lovelace",
        password: "correct-horse-battery",
      },
    ]);
  });

  it("shows each field's errors next to that field", async () => {
    fakeBackend({
      "POST /api/auth/register/": json(400, {
        phone_number: ["A user with this phone number already exists."],
        password: ["This password is too short.", "This password is too common."],
      }),
    });
    renderAt("/register");

    fillIn("Phone number", "5551234567");
    fillIn("First name", "Ada");
    fillIn("Last name", "Lovelace");
    fillIn("Password", "abc");
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(
      await screen.findByText("A user with this phone number already exists."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Phone number")).toHaveAccessibleDescription(
      "A user with this phone number already exists.",
    );
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      "This password is too short. This password is too common.",
    );
    expect(screen.getByLabelText("First name")).toBeValid();
  });

  it("shows an error for a field the page has no input for", async () => {
    fakeBackend({
      "POST /api/auth/register/": json(400, { __all__: ["Something about the account."] }),
    });
    renderAt("/register");

    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Something about the account.");
  });

  it("moves focus to the first invalid field after a failed submit", async () => {
    fakeBackend({
      "POST /api/auth/register/": json(400, {
        first_name: ["This field may not be blank."],
        password: ["This password is too short."],
      }),
    });
    renderAt("/register");

    fillIn("Phone number", "5551234567");
    fillIn("Password", "abc");
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await screen.findByText("This field may not be blank.");
    await waitFor(() => expect(screen.getByLabelText("First name")).toHaveFocus());
  });
});

describe("layout", () => {
  const PAGES = ["Discover", "Manage", "Loans", "Connections"];

  function current(name: string) {
    const nav = screen.getByRole("navigation", { name });
    return within(nav)
      .getAllByRole("link")
      .filter((link) => link.getAttribute("aria-current") === "page")
      .map((link) => link.textContent);
  }

  it.each([
    ["/", "Discover"],
    ["/manage/items", "Manage"],
    ["/inventories/7", "Manage"],
    ["/loans", "Loans"],
    ["/connections", "Connections"],
  ])("marks the current page in the sidebar at %s", async (path, page) => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA) });

    renderAt(path);

    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual(PAGES);
    expect(current("Main")).toEqual([page]);
  });

  it("links each sidebar entry to its page", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA) });

    renderAt("/");

    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/",
      "/manage",
      "/loans",
      "/connections",
    ]);
  });

  it("opens the Inventories tab at /manage", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA) });

    renderAt("/manage");

    expect(await screen.findByRole("heading", { name: "My inventories" })).toBeInTheDocument();
    expect(current("Manage")).toEqual(["Inventories"]);
  });

  it("switches Manage tabs through the URL", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA) });
    renderAt("/manage/inventories");
    await screen.findByRole("heading", { name: "My inventories" });

    fireEvent.click(screen.getByRole("link", { name: "My items" }));

    expect(await screen.findByRole("region", { name: "My items" })).toBeInTheDocument();
    expect(current("Manage")).toEqual(["My items"]);
    expect(screen.queryByRole("heading", { name: "My inventories" })).toBeNull();
  });

  it("shows not found at /gear", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA) });

    renderAt("/gear");

    expect(await screen.findByText(/Page not found\./)).toBeInTheDocument();
  });

  it("shows the login form without a sidebar", async () => {
    fakeBackend({});

    renderAt("/login");

    expect(screen.getByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("button", { name: "Log out" })).toBeNull();
  });
});
