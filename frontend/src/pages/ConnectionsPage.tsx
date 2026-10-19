import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import type { Connection, ConnectionRequests, ReceivedRequest, SentRequest } from "../connections";
import { Confirmation, Field, FormErrors, unreachable, useFocusFirstInvalid } from "../forms";
import { fullName, getJson } from "../inventories";
import { useLoad } from "../load";
import { formatPhoneNumber } from "../phone";

interface PageData extends ConnectionRequests {
  connections: Connection[];
}

async function loadPage(signal: AbortSignal): Promise<PageData> {
  const [connections, requests] = await Promise.all([
    getJson<Connection[]>("/api/connections/", signal),
    getJson<ConnectionRequests>("/api/connections/requests/", signal),
  ]);
  return { connections, ...requests };
}

export default function ConnectionsPage() {
  const [page, reload] = useLoad(loadPage);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [sendErrors, setSendErrors] = useState<FieldErrors>({});
  const [sent, setSent] = useState<string | null>(null);

  function clearMessages() {
    setErrors({});
    setSendErrors({});
    setSent(null);
  }

  async function act(path: string, method: "POST" | "DELETE") {
    clearMessages();
    try {
      const response = await apiFetch(path, { method });
      if (!response.ok) setErrors(await readErrors(response, []));
      // A refusal may come from a change the other user made; show the current state.
      reload();
    } catch {
      setErrors(unreachable());
    }
  }

  const answer = (action: "accept" | "decline" | "cancel") => (request: { id: number }) =>
    act(`/api/connections/${request.id}/${action}/`, "POST");
  const receivedActions: RequestAction<ReceivedRequest>[] = [
    { label: "Accept", name: "Accept request from", run: answer("accept") },
    { label: "Decline", name: "Decline request from", run: answer("decline") },
  ];
  const sentActions: RequestAction<SentRequest>[] = [
    { label: "Cancel", name: "Cancel request to", run: answer("cancel") },
  ];

  return (
    <>
      <h2>My connections</h2>
      <p>
        <Link to="/">My inventories</Link>
      </p>
      <FormErrors errors={errors} />
      {page.status === "loading" && <p>Loading…</p>}
      {page.status === "error" && <p role="alert">Could not load your connections.</p>}
      {page.status === "ok" && (
        <>
          <ConnectionList
            connections={page.data.connections}
            onRemove={(connection) => act(`/api/connections/${connection.id}/`, "DELETE")}
          />
          <RequestList
            title="Requests received"
            empty="No requests received."
            requests={page.data.received}
            actions={receivedActions}
            describe={(request) => fullName(request.user)}
          />
          <RequestList
            title="Requests sent"
            empty="No requests sent."
            requests={page.data.sent}
            actions={sentActions}
            describe={(request) => formatPhoneNumber(request.user.phone_number)}
          />
        </>
      )}
      <SendRequest
        reload={reload}
        onStart={clearMessages}
        errors={sendErrors}
        setErrors={setSendErrors}
        sent={sent}
        onSent={setSent}
      />
    </>
  );
}

interface ConnectionListProps {
  connections: Connection[];
  onRemove: (connection: Connection) => void;
}

function ConnectionList({ connections, onRemove }: ConnectionListProps) {
  const [removing, setRemoving] = useState<Connection | null>(null);

  return (
    <section aria-labelledby="connections">
      <h3 id="connections">Connections</h3>
      {connections.length === 0 ? (
        <p>No connections yet.</p>
      ) : (
        <ul>
          {connections.map((connection) => (
            <li key={connection.id}>
              <span>
                {[fullName(connection.user), formatPhoneNumber(connection.user.phone_number)].join(
                  ", ",
                )}
              </span>{" "}
              <button
                type="button"
                aria-label={`Remove ${fullName(connection.user)}`}
                onClick={() => setRemoving(connection)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {removing && (
        <Confirmation
          message={`Remove ${fullName(removing.user)} from your connections?`}
          confirm="Yes, remove"
          onConfirm={() => {
            onRemove(removing);
            setRemoving(null);
          }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </section>
  );
}

interface RequestAction<R> {
  label: string;
  /** The accessible name before the other user's name or number, such as "Accept request from". */
  name: string;
  run: (request: R) => void;
}

interface RequestListProps<R extends { id: number }> {
  title: string;
  empty: string;
  requests: R[];
  actions: RequestAction<R>[];
  /** Who the request is from or to: a name for a received request, a number for a sent one. */
  describe: (request: R) => string;
}

function RequestList<R extends { id: number }>({
  title,
  empty,
  requests,
  actions,
  describe,
}: RequestListProps<R>) {
  const id = title.toLowerCase().replaceAll(" ", "-");
  return (
    <section aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {requests.length === 0 ? (
        <p>{empty}</p>
      ) : (
        <ul>
          {requests.map((request) => (
            <li key={request.id}>
              <span>{describe(request)}</span>
              {actions.map((action) => (
                <span key={action.label}>
                  {" "}
                  <button
                    type="button"
                    aria-label={`${action.name} ${describe(request)}`}
                    onClick={() => action.run(request)}
                  >
                    {action.label}
                  </button>
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface SendRequestProps {
  reload: () => void;
  onStart: () => void;
  errors: FieldErrors;
  setErrors: (errors: FieldErrors) => void;
  sent: string | null;
  onSent: (message: string) => void;
}

function SendRequest({ reload, onStart, errors, setErrors, sent, onSent }: SendRequestProps) {
  const formRef = useFocusFirstInvalid(errors);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    onStart();
    try {
      const response = await apiFetch("/api/connections/", {
        method: "POST",
        body: { phone_number: new FormData(form).get("phone_number") },
      });
      if (!response.ok) {
        setErrors(await readErrors(response, ["phone_number"]));
        return;
      }
      const result = (await response.json()) as Connection | SentRequest;
      setErrors({});
      onSent(
        result.status === "accepted"
          ? `You are now connected with ${fullName(result.user)}.`
          : `Request sent to ${formatPhoneNumber(result.user.phone_number)}.`,
      );
      form.reset();
      reload();
    } catch {
      setErrors(unreachable());
    }
  }

  return (
    <section aria-labelledby="send-request">
      <h3 id="send-request">Send a request</h3>
      <form ref={formRef} onSubmit={submit} noValidate>
        <FormErrors errors={errors} />
        <Field name="phone_number" label="Phone number" type="tel" errors={errors} />
        <button type="submit">Send request</button>
      </form>
      {sent && <p role="status">{sent}</p>}
    </section>
  );
}
