import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ADA, empty, fakeBackend, json } from "../test-backend";
import { fillIn, renderAt } from "../test-render";

type Routes = Parameters<typeof fakeBackend>[0];

const PHONE_NUMBER = /\(?[0-9]{3}\)? ?[0-9]{3}-?[0-9]{4}/;

const WITH_BOB = {
  id: 10,
  status: "accepted",
  user: { id: 2, first_name: "Bob", last_name: "Stone", phone_number: "5551230002" },
};
const FROM_CY = { id: 11, status: "pending", user: { first_name: "Cy", last_name: "Young" } };
const TO_DEE = { id: 12, status: "pending", user: { first_name: "Dee", last_name: "Ford" } };

function signedIn(routes: Routes = {}) {
  return fakeBackend({ "GET /api/auth/me/": json(200, ADA), ...routes });
}

/** A backend whose lists change as the page acts, so a reload shows the new state. */
function liveBackend(routes: (state: State) => Routes) {
  const state: State = { connections: [WITH_BOB], received: [FROM_CY], sent: [TO_DEE] };
  return signedIn({
    "GET /api/connections/": () => json(200, state.connections)({}),
    "GET /api/connections/requests/": () =>
      json(200, { received: state.received, sent: state.sent })({}),
    ...routes(state),
  });
}

interface State {
  connections: (typeof WITH_BOB)[];
  received: (typeof FROM_CY)[];
  sent: (typeof TO_DEE)[];
}

async function open() {
  renderAt("/connections");
  await screen.findByRole("heading", { name: "My connections" });
  await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
}

function region(name: string) {
  return screen.getByRole("region", { name });
}

function items(name: string) {
  return within(region(name))
    .queryAllByRole("listitem")
    .map((item) => item.firstChild?.textContent);
}

describe("my connections", () => {
  it("shows connections with their phone number and requests by name only", async () => {
    liveBackend(() => ({}));

    await open();

    expect(items("Connections")).toEqual(["Bob Stone, (555) 123-0002"]);
    expect(items("Requests received")).toEqual(["Cy Young"]);
    expect(items("Requests sent")).toEqual(["Dee Ford"]);
    const requests = [region("Requests received"), region("Requests sent")];
    for (const section of requests) expect(section.textContent).not.toMatch(PHONE_NUMBER);
  });

  it("says so when there are no connections or requests", async () => {
    signedIn();

    await open();

    expect(screen.getByText("No connections yet.")).toBeInTheDocument();
    expect(screen.getByText("No requests received.")).toBeInTheDocument();
    expect(screen.getByText("No requests sent.")).toBeInTheDocument();
  });

  it("shows an error when the lists cannot be loaded", async () => {
    signedIn({ "GET /api/connections/": json(500, {}) });

    renderAt("/connections");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load your connections.",
    );
  });

  it("is reached from the home page", async () => {
    signedIn();
    renderAt("/");

    fireEvent.click(await screen.findByRole("link", { name: "My connections" }));

    expect(await screen.findByRole("heading", { name: "My connections" })).toBeInTheDocument();
  });

  it("sends an anonymous user to the login page", async () => {
    fakeBackend({ "GET /api/auth/me/": json(403, { detail: "Not logged in." }) });

    renderAt("/connections");

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });
});

describe("removing a connection", () => {
  it("asks first and removes only after confirming", async () => {
    const backend = liveBackend((state) => ({
      "DELETE /api/connections/10/": () => {
        state.connections = [];
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Remove Bob Stone" }));
    expect(screen.getByText("Remove Bob Stone from your connections?")).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(backend.requests("DELETE /api/connections/10/")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Remove Bob Stone" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, remove" }));

    expect(await screen.findByText("No connections yet.")).toBeInTheDocument();
    expect(backend.requests("DELETE /api/connections/10/")).toHaveLength(1);
    expect(screen.queryByText(/from your connections\?/)).not.toBeInTheDocument();
  });

  it("shows why a connection could not be removed and reloads", async () => {
    let loads = 0;
    signedIn({
      "GET /api/connections/": () => {
        loads += 1;
        return json(200, [WITH_BOB])({});
      },
      "DELETE /api/connections/10/": json(404, { detail: "Connection not found." }),
    });
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Remove Bob Stone" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, remove" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Connection not found.");
    await waitFor(() => expect(loads).toBe(2));
  });
});

describe("answering requests", () => {
  it("accepting moves the request to the connections", async () => {
    const CY = {
      id: 11,
      status: "accepted",
      user: { id: 3, first_name: "Cy", last_name: "Young", phone_number: "5551230003" },
    };
    const backend = liveBackend((state) => ({
      "POST /api/connections/11/accept/": () => {
        state.received = [];
        state.connections = [WITH_BOB, CY];
        return json(200, CY)({});
      },
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Accept request from Cy Young" }));

    expect(await screen.findByText("No requests received.")).toBeInTheDocument();
    expect(items("Connections")).toEqual([
      "Bob Stone, (555) 123-0002",
      "Cy Young, (555) 123-0003",
    ]);
    expect(backend.requests("POST /api/connections/11/accept/")).toHaveLength(1);
  });

  it("declining removes the request", async () => {
    const backend = liveBackend((state) => ({
      "POST /api/connections/11/decline/": () => {
        state.received = [];
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Decline request from Cy Young" }));

    expect(await screen.findByText("No requests received.")).toBeInTheDocument();
    expect(backend.requests("POST /api/connections/11/decline/")).toHaveLength(1);
  });

  it("cancelling removes a sent request", async () => {
    const backend = liveBackend((state) => ({
      "POST /api/connections/12/cancel/": () => {
        state.sent = [];
        return empty(204)({});
      },
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Cancel request to Dee Ford" }));

    expect(await screen.findByText("No requests sent.")).toBeInTheDocument();
    expect(backend.requests("POST /api/connections/12/cancel/")).toHaveLength(1);
  });

  it("shows a conflict and reloads the current state", async () => {
    liveBackend((state) => ({
      "POST /api/connections/12/cancel/": () => {
        state.sent = [];
        const dee = { ...WITH_BOB.user, id: 4, first_name: "Dee", last_name: "Ford" };
        state.connections = [WITH_BOB, { ...WITH_BOB, id: 12, user: dee }];
        return json(409, { detail: "This is not a pending request." })({});
      },
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Cancel request to Dee Ford" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This is not a pending request.");
    await waitFor(() => expect(items("Requests sent")).toEqual([]));
    expect(items("Connections")).toContain("Dee Ford, (555) 123-0002");
  });

  it("says when the backend cannot be reached", async () => {
    liveBackend(() => ({
      "POST /api/connections/11/accept/": () => {
        throw new TypeError("offline");
      },
    }));
    await open();

    fireEvent.click(screen.getByRole("button", { name: "Accept request from Cy Young" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the backend.");
  });
});

describe("sending a request", () => {
  async function send(phoneNumber: string) {
    fillIn("Phone number", phoneNumber);
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
  }

  it("sends the number, says who it went to and lists the request", async () => {
    const MIA = { id: 13, status: "pending", user: { first_name: "Mia", last_name: "Lee" } };
    const backend = liveBackend((state) => ({
      "POST /api/connections/": () => {
        state.sent = [TO_DEE, MIA];
        return json(201, MIA)({});
      },
    }));
    await open();

    await send("(555) 123-0007");

    expect(await screen.findByRole("status")).toHaveTextContent("Request sent to Mia Lee.");
    await waitFor(() => expect(items("Requests sent")).toEqual(["Dee Ford", "Mia Lee"]));
    expect(backend.requests("POST /api/connections/")).toEqual([
      { phone_number: "(555) 123-0007" },
    ]);
    expect(screen.getByLabelText("Phone number")).toHaveValue("");
  });

  it("says when the request connected at once", async () => {
    const CY = {
      id: 11,
      status: "accepted",
      user: { id: 3, first_name: "Cy", last_name: "Young", phone_number: "5551230003" },
    };
    liveBackend((state) => ({
      "POST /api/connections/": () => {
        state.received = [];
        state.connections = [WITH_BOB, CY];
        return json(200, CY)({});
      },
    }));
    await open();

    await send("5551230003");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "You are now connected with Cy Young.",
    );
    await waitFor(() => expect(items("Requests received")).toEqual([]));
  });

  it("shows an unknown number next to the phone number field", async () => {
    signedIn({
      "POST /api/connections/": json(400, { phone_number: ["No user has this phone number."] }),
    });
    await open();

    await send("5559999999");

    const phone = screen.getByLabelText("Phone number");
    await waitFor(() =>
      expect(phone).toHaveAccessibleDescription("No user has this phone number."),
    );
    await waitFor(() => expect(phone).toHaveFocus());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows a conflict for the whole form", async () => {
    signedIn({
      "POST /api/connections/": json(409, { detail: "You are already connected." }),
    });
    await open();

    await send("5551230002");

    const form = screen.getByRole("button", { name: "Send request" }).closest("form")!;
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "You are already connected.",
    );
  });
});
