import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "./App";
import { ADA, empty, fakeBackend, json } from "./test-backend";

const ANONYMOUS = json(403, { detail: "Authentication credentials were not provided." });

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

function fillIn(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("home page", () => {
  it("shows who is signed in, their phone number and the health line", async () => {
    fakeBackend({ "GET /api/auth/me/": json(200, ADA) });

    renderAt("/");

    expect(await screen.findByText("Signed in as Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("(555) 123-4567")).toBeInTheDocument();
    expect(await screen.findByText("Backend and database are ok.")).toBeInTheDocument();
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
});
