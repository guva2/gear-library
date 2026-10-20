import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { useAuth } from "../auth";
import { Field, FormErrors, unreachable, useFocusFirstInvalid } from "../forms";
import HealthStatus from "../HealthStatus";
import { fullName, getJson, type Inventory, type MyInvite } from "../inventories";
import { useLoad } from "../load";
import { formatPhoneNumber } from "../phone";

interface Lists {
  inventories: Inventory[];
  invites: MyInvite[];
}

async function loadLists(signal: AbortSignal): Promise<Lists> {
  const [inventories, invites] = await Promise.all([
    getJson<Inventory[]>("/api/inventories/", signal),
    getJson<MyInvite[]>("/api/invites/", signal),
  ]);
  return { inventories, invites };
}

export default function HomePage() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const [errors, setErrors] = useState<FieldErrors>({});
  const [lists, reload] = useLoad(loadLists);

  async function logOut() {
    try {
      const response = await apiFetch("/api/auth/logout/", { method: "POST" });
      if (!response.ok) {
        const errors = await readErrors(response, []);
        // A 403 that is not a CSRF failure means the session is already gone.
        const csrfFailed = errors.form?.some((message) => message.startsWith("CSRF"));
        if (response.status !== 403 || csrfFailed) {
          setErrors(errors);
          return;
        }
      }
      setUser(null);
      navigate("/login", { replace: true });
    } catch {
      setErrors(unreachable());
    }
  }

  if (!user) return null;
  return (
    <>
      <p>Signed in as {`${user.first_name} ${user.last_name}`}</p>
      <p>{formatPhoneNumber(user.phone_number)}</p>
      <FormErrors errors={errors} />
      <button type="button" onClick={logOut}>
        Log out
      </button>
      <p>
        <Link to="/connections">My connections</Link>
      </p>
      {lists.status === "loading" && <p>Loading…</p>}
      {lists.status === "error" && <p role="alert">Could not load your inventories.</p>}
      {lists.status === "ok" && (
        <>
          <InventoryList inventories={lists.data.inventories} />
          <Invites invites={lists.data.invites} reload={reload} />
        </>
      )}
      <HealthStatus />
    </>
  );
}

function InventoryList({ inventories }: { inventories: Inventory[] }) {
  return (
    <section aria-labelledby="my-inventories">
      <h2 id="my-inventories">My inventories</h2>
      {inventories.length === 0 ? (
        <p>You are not in any inventory yet.</p>
      ) : (
        <ul>
          {inventories.map((inventory) => (
            <li key={inventory.id}>
              <Link to={`/inventories/${inventory.id}`}>{inventory.name}</Link> (
              {inventory.role})
            </li>
          ))}
        </ul>
      )}
      <CreateInventory />
    </section>
  );
}

function CreateInventory() {
  const navigate = useNavigate();
  const [errors, setErrors] = useState<FieldErrors>({});
  const formRef = useFocusFirstInvalid(errors);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const response = await apiFetch("/api/inventories/", {
        method: "POST",
        body: { name: form.get("name") },
      });
      if (!response.ok) {
        setErrors(await readErrors(response, ["name"]));
        return;
      }
      const inventory = (await response.json()) as Inventory;
      navigate(`/inventories/${inventory.id}`);
    } catch {
      setErrors(unreachable());
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} noValidate>
      <FormErrors errors={errors} />
      <Field name="name" label="Inventory name" errors={errors} />
      <button type="submit">Create</button>
    </form>
  );
}

function Invites({ invites, reload }: { invites: MyInvite[]; reload: () => void }) {
  const [errors, setErrors] = useState<FieldErrors>({});

  async function answer(invite: MyInvite, action: "accept" | "decline") {
    try {
      const response = await apiFetch(`/api/invites/${invite.id}/${action}/`, {
        method: "POST",
      });
      setErrors(response.ok ? {} : await readErrors(response, []));
      reload();
    } catch {
      setErrors(unreachable());
    }
  }

  return (
    <section aria-labelledby="my-invites">
      <h2 id="my-invites">Invites</h2>
      <FormErrors errors={errors} />
      {invites.length === 0 ? (
        <p>No pending invites.</p>
      ) : (
        <ul>
          {invites.map((invite) => (
            <li key={invite.id}>
              <span>{`${invite.inventory_name}, from ${fullName(invite.invited_by)}`}</span>{" "}
              <button
                type="button"
                aria-label={`Accept invite to ${invite.inventory_name}`}
                onClick={() => answer(invite, "accept")}
              >
                Accept
              </button>{" "}
              <button
                type="button"
                aria-label={`Decline invite to ${invite.inventory_name}`}
                onClick={() => answer(invite, "decline")}
              >
                Decline
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
