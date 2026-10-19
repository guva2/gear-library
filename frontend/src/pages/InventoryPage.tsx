import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { useAuth } from "../auth";
import { Field, FormErrors, unreachable, useFocusFirstInvalid } from "../forms";
import {
  fullName,
  getJson,
  hasRole,
  HttpError,
  ROLES,
  type Inventory,
  type InventoryInvite,
  type Member,
  type PersonName,
  type Role,
} from "../inventories";
import { useLoad } from "../load";
import { formatPhoneNumber } from "../phone";

/** What the API shows the caller, which depends on their role. */
type People = { staff: true; members: Member[] } | { staff: false; names: PersonName[] };

interface PageData {
  inventory: Inventory;
  people: People;
  invites: InventoryInvite[];
}

async function loadPage(base: string, signal: AbortSignal): Promise<PageData> {
  const inventory = await getJson<Inventory>(base, signal);
  const staff = hasRole(inventory.role, "admin");
  const [people, invites] = await Promise.all([
    staff
      ? getJson<Member[]>(`${base}members/`, signal).then(
          (members): People => ({ staff: true, members }),
        )
      : getJson<PersonName[]>(`${base}members/`, signal).then(
          (names): People => ({ staff: false, names }),
        ),
    staff ? getJson<InventoryInvite[]>(`${base}invites/`, signal) : [],
  ]);
  return { inventory, people, invites };
}

type Method = "POST" | "PATCH" | "DELETE";

type Send = (
  path: string,
  method: Method,
  options?: { body?: unknown; fields?: readonly string[] },
) => Promise<FieldErrors | null>;

export default function InventoryPage() {
  const { id } = useParams();
  // The router decodes the segment, so a `%3F` or `%2F` in it would change the API path.
  if (!id || !/^[0-9]+$/.test(id)) return <NotFound />;
  // A new id gets a fresh page, not the previous inventory's state.
  return <InventoryView key={id} base={`/api/inventories/${id}/`} />;
}

function NotFound() {
  return (
    <p>
      Inventory not found. <Link to="/">Go home</Link>
    </p>
  );
}

function InventoryView({ base }: { base: string }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [page, reload] = useLoad((signal) => loadPage(base, signal));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [refusal, setRefusal] = useState<FieldErrors>({});

  /**
   * Sends a change. Returns the errors for the caller to show, or `null` when it succeeded.
   * A 403 is shown here instead and returns no errors: the caller has lost a role, and the
   * reload can remove the section that sent the change.
   */
  const send: Send = async (path, method, { body, fields = [] } = {}) => {
    setRefusal({});
    try {
      const response = await apiFetch(path, { method, body });
      if (response.ok) return null;
      const errors = await readErrors(response, fields);
      // The refusal may come from a change someone else made; show the current state.
      reload();
      if (response.status !== 403) return errors;
      setRefusal(errors);
      return {};
    } catch {
      return unreachable();
    }
  };

  async function act(path: string, method: Method, body?: unknown) {
    const failed = await send(path, method, { body });
    setErrors(failed ?? {});
    if (!failed) reload();
  }

  async function leaveOrDelete(path: string) {
    const failed = await send(path, "DELETE");
    if (failed) setErrors(failed);
    else navigate("/");
  }

  if (page.status === "loading") return <p>Loading…</p>;
  if (page.status === "error") {
    if (page.error instanceof HttpError && page.error.status === 404) return <NotFound />;
    return <p role="alert">Could not load the inventory.</p>;
  }

  const { inventory, people, invites } = page.data;
  const isOwner = inventory.role === "owner";
  return (
    <>
      <h2>{inventory.name}</h2>
      <p>Your role: {inventory.role}</p>
      <p>
        <Link to="/">My inventories</Link>
      </p>
      <FormErrors errors={refusal} />
      <FormErrors errors={errors} />
      {people.staff ? (
        <MemberTable
          members={people.members}
          ownerId={isOwner ? user?.id : undefined}
          onSetRole={(member, role) => act(`${base}members/${member.id}/`, "PATCH", { role })}
          onRemove={(member) => act(`${base}members/${member.id}/`, "DELETE")}
        />
      ) : (
        <section aria-labelledby="people">
          <h3 id="people">Admins and owners</h3>
          <ul>
            {people.names.map((person, index) => (
              <li key={index}>{fullName(person)}</li>
            ))}
          </ul>
        </section>
      )}
      {people.staff && (
        <Invites
          invites={invites}
          send={send}
          base={base}
          reload={reload}
          onRevoke={(invite) => act(`/api/invites/${invite.id}/revoke/`, "POST")}
        />
      )}
      <p>
        <button type="button" onClick={() => leaveOrDelete(`${base}members/${user?.id}/`)}>
          Leave inventory
        </button>
      </p>
      {isOwner && (
        <Manage
          name={inventory.name}
          send={send}
          base={base}
          reload={reload}
          onDelete={() => leaveOrDelete(base)}
        />
      )}
    </>
  );
}

interface MemberTableProps {
  members: Member[];
  /** The signed-in owner's id. Unset for an admin, who sees the table without controls. */
  ownerId: number | undefined;
  onSetRole: (member: Member, role: Role) => void;
  onRemove: (member: Member) => void;
}

function MemberTable({ members, ownerId, onSetRole, onRemove }: MemberTableProps) {
  const controls = ownerId !== undefined;
  // The owner's own new role, waiting for confirmation: any other role drops owner rights.
  const [ownRole, setOwnRole] = useState<{ member: Member; role: Role } | null>(null);

  function pickRole(member: Member, role: Role) {
    if (member.id === ownerId) setOwnRole({ member, role });
    else onSetRole(member, role);
  }

  return (
    <section aria-labelledby="members">
      <h3 id="members">Members</h3>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Phone number</th>
            <th>Role</th>
            {controls && <th>Remove</th>}
          </tr>
        </thead>
        <tbody>
          {members.map((member) => (
            <tr key={member.id}>
              <td>{fullName(member)}</td>
              <td>{formatPhoneNumber(member.phone_number)}</td>
              <td>
                {controls ? (
                  <select
                    aria-label={`Role for ${fullName(member)}`}
                    value={member.role}
                    onChange={(event) => pickRole(member, event.target.value as Role)}
                  >
                    {ROLES.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                ) : (
                  member.role
                )}
              </td>
              {controls && (
                <td>
                  {member.id !== ownerId && (
                    <button
                      type="button"
                      aria-label={`Remove ${fullName(member)}`}
                      onClick={() => onRemove(member)}
                    >
                      Remove
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {ownRole && (
        <p>
          {`Change your role to ${ownRole.role}? You will no longer be an owner.`}{" "}
          <button
            type="button"
            onClick={() => {
              onSetRole(ownRole.member, ownRole.role);
              setOwnRole(null);
            }}
          >
            Yes, change my role
          </button>{" "}
          <button type="button" onClick={() => setOwnRole(null)}>
            Cancel
          </button>
        </p>
      )}
    </section>
  );
}

interface InvitesProps {
  invites: InventoryInvite[];
  send: Send;
  base: string;
  reload: () => void;
  onRevoke: (invite: InventoryInvite) => void;
}

function Invites({ invites, send, base, reload, onRevoke }: InvitesProps) {
  const [errors, setErrors] = useState<FieldErrors>({});
  const formRef = useFocusFirstInvalid(errors);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const failed = await send(`${base}invites/`, "POST", {
      body: { phone_number: new FormData(form).get("phone_number") },
      fields: ["phone_number"],
    });
    setErrors(failed ?? {});
    if (!failed) {
      form.reset();
      reload();
    }
  }

  return (
    <section aria-labelledby="invites">
      <h3 id="invites">Pending invites</h3>
      {invites.length === 0 ? (
        <p>No pending invites.</p>
      ) : (
        <ul>
          {invites.map((invite) => (
            <li key={invite.id}>
              <span>
                {[
                  formatPhoneNumber(invite.invitee.phone_number),
                  `invited by ${fullName(invite.invited_by)}`,
                ].join(", ")}
              </span>{" "}
              <button
                type="button"
                aria-label={`Revoke invite for ${formatPhoneNumber(invite.invitee.phone_number)}`}
                onClick={() => onRevoke(invite)}
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
      <form ref={formRef} onSubmit={submit} noValidate>
        <FormErrors errors={errors} />
        <Field name="phone_number" label="Phone number" type="tel" errors={errors} />
        <button type="submit">Invite</button>
      </form>
    </section>
  );
}

interface ManageProps {
  name: string;
  send: Send;
  base: string;
  reload: () => void;
  onDelete: () => void;
}

function Manage({ name, send, base, reload, onDelete }: ManageProps) {
  const [errors, setErrors] = useState<FieldErrors>({});
  const [confirming, setConfirming] = useState(false);
  const formRef = useFocusFirstInvalid(errors);

  async function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const failed = await send(base, "PATCH", {
      body: { name: new FormData(form).get("name") },
      fields: ["name"],
    });
    setErrors(failed ?? {});
    if (!failed) {
      form.reset();
      reload();
    }
  }

  return (
    <section aria-labelledby="manage">
      <h3 id="manage">Manage inventory</h3>
      <form ref={formRef} onSubmit={rename} noValidate>
        <FormErrors errors={errors} />
        <Field name="name" label="New name" errors={errors} />
        <button type="submit">Rename</button>
      </form>
      {confirming ? (
        <p>
          {`Delete ${name}? This cannot be undone.`}{" "}
          <button type="button" onClick={onDelete}>
            Yes, delete
          </button>{" "}
          <button type="button" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </p>
      ) : (
        <p>
          <button type="button" onClick={() => setConfirming(true)}>
            Delete inventory
          </button>
        </p>
      )}
    </section>
  );
}
