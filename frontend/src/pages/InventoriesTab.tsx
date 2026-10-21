import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { Field, FormErrors, unreachable, useFocusFirstInvalid, useLatestChange } from "../forms";
import { fullName, getJson, type Inventory, type MyInvite } from "../inventories";
import { useLoad } from "../load";

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

/** The signed-in user's inventories, the form to create one, and their pending invites. */
export default function InventoriesTab() {
  const [lists, reload] = useLoad(loadLists);
  const start = useLatestChange();

  return (
    <>
      {lists.status === "loading" && <p>Loading…</p>}
      {lists.status === "error" && <p role="alert">Could not load your inventories.</p>}
      {lists.status === "ok" && (
        <>
          <InventoryList inventories={lists.data.inventories} reload={reload} start={start} />
          <Invites invites={lists.data.invites} reload={reload} start={start} />
        </>
      )}
    </>
  );
}

/** Starts a change; the check it returns says whether the change is still the latest. */
type StartChange = () => () => boolean;

interface InventoryListProps {
  inventories: Inventory[];
  reload: () => void;
  start: StartChange;
}

function InventoryList({ inventories, reload, start }: InventoryListProps) {
  return (
    <section aria-labelledby="my-inventories">
      <h3 id="my-inventories">My inventories</h3>
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
      <CreateInventory reload={reload} start={start} />
    </section>
  );
}

function CreateInventory({ reload, start }: { reload: () => void; start: StartChange }) {
  const navigate = useNavigate();
  const [errors, setErrors] = useState<FieldErrors>({});
  const formRef = useFocusFirstInvalid(errors);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const isLatest = start();
    try {
      const response = await apiFetch("/api/inventories/", {
        method: "POST",
        body: { name: form.get("name") },
      });
      if (!response.ok) {
        const errors = await readErrors(response, ["name"]);
        if (isLatest()) setErrors(errors);
        return;
      }
      const inventory = (await response.json()) as Inventory;
      // After a later change, the new inventory shows in the list instead of taking over.
      if (isLatest()) navigate(`/inventories/${inventory.id}`);
      else reload();
    } catch {
      if (isLatest()) setErrors(unreachable());
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

interface InvitesProps {
  invites: MyInvite[];
  reload: () => void;
  start: StartChange;
}

function Invites({ invites, reload, start }: InvitesProps) {
  const [errors, setErrors] = useState<FieldErrors>({});

  async function answer(invite: MyInvite, action: "accept" | "decline") {
    const isLatest = start();
    try {
      const response = await apiFetch(`/api/invites/${invite.id}/${action}/`, {
        method: "POST",
      });
      const errors = response.ok ? {} : await readErrors(response, []);
      if (isLatest()) setErrors(errors);
      reload();
    } catch {
      if (isLatest()) setErrors(unreachable());
    }
  }

  return (
    <section aria-labelledby="my-invites">
      <h3 id="my-invites">Invites</h3>
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
