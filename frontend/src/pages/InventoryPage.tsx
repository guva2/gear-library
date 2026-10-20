import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { useAuth } from "../auth";
import type { Connection } from "../connections";
import { Confirmation, Field, FormErrors, unreachable, useFocusFirstInvalid } from "../forms";
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
import { describeItem, type Item, type ListedItem } from "../items";
import { useLoad } from "../load";
import { formatPhoneNumber } from "../phone";

/** What the API shows the caller, which depends on their role. */
type People = { staff: true; members: Member[] } | { staff: false; names: PersonName[] };

interface PageData {
  inventory: Inventory;
  people: People;
  invites: InventoryInvite[];
  /** The caller's accepted connections. Loaded only for admins and owners. */
  connections: Connection[];
  listed: ListedItem[];
  /** The caller's own items. Loaded only for admins and owners. */
  myItems: Item[];
}

async function loadPage(base: string, signal: AbortSignal): Promise<PageData> {
  const inventory = await getJson<Inventory>(base, signal);
  const staff = hasRole(inventory.role, "admin");
  const [people, invites, connections, listed, myItems] = await Promise.all([
    staff
      ? getJson<Member[]>(`${base}members/`, signal).then(
          (members): People => ({ staff: true, members }),
        )
      : getJson<PersonName[]>(`${base}members/`, signal).then(
          (names): People => ({ staff: false, names }),
        ),
    staff ? getJson<InventoryInvite[]>(`${base}invites/`, signal) : [],
    staff ? getJson<Connection[]>("/api/connections/", signal) : [],
    getJson<ListedItem[]>(`${base}items/`, signal),
    staff ? getJson<Item[]>("/api/items/", signal) : [],
  ]);
  return { inventory, people, invites, connections, listed, myItems };
}

type Method = "POST" | "PATCH" | "DELETE";

type Send = (
  path: string,
  method: Method,
  options?: { body?: unknown; fields?: readonly string[] },
) => Promise<Failure | null>;

/** A change that did not succeed. `status` is `null` when there was no response. */
interface Failure {
  errors: FieldErrors;
  status: number | null;
}

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
  // Counts the changes sent, so the pickers can drop messages left by an earlier one.
  const [sent, setSent] = useState(0);

  /**
   * Sends a change. Returns the failure for the caller to show, or `null` when it succeeded.
   * A 403 is shown here instead and returns no errors: the caller has lost a role, and the
   * reload can remove the section that sent the change.
   */
  const send: Send = async (path, method, { body, fields = [] } = {}) => {
    setRefusal({});
    setErrors({});
    setSent((count) => count + 1);
    try {
      const response = await apiFetch(path, { method, body });
      if (response.ok) return null;
      const errors = await readErrors(response, fields);
      // The refusal may come from a change someone else made; show the current state.
      reload();
      if (response.status !== 403) return { errors, status: response.status };
      setRefusal(errors);
      return { errors: {}, status: 403 };
    } catch {
      return { errors: unreachable(), status: null };
    }
  };

  async function act(path: string, method: Method, body?: unknown) {
    const failed = await send(path, method, { body });
    setErrors(failed?.errors ?? {});
    if (!failed) reload();
  }

  async function leaveOrDelete(path: string) {
    const failed = await send(path, "DELETE");
    if (failed) setErrors(failed.errors);
    else navigate("/");
  }

  if (page.status === "loading") return <p>Loading…</p>;
  if (page.status === "error") {
    if (page.error instanceof HttpError && page.error.status === 404) return <NotFound />;
    return <p role="alert">Could not load the inventory.</p>;
  }

  const { inventory, people, invites, connections, listed, myItems } = page.data;
  const isOwner = inventory.role === "owner";
  const myItemIds = new Set(myItems.map((item) => item.id));
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
          invitable={invitable(connections, people.members, invites)}
          send={send}
          sent={sent}
          base={base}
          reload={reload}
          onRevoke={(invite) => act(`/api/invites/${invite.id}/revoke/`, "POST")}
        />
      )}
      <Items
        listed={listed}
        listable={people.staff ? listable(myItems, listed) : null}
        removable={(item) => people.staff && (isOwner || myItemIds.has(item.id))}
        send={send}
        sent={sent}
        base={base}
        reload={reload}
        onRemove={(item) => act(`${base}items/${item.id}/`, "DELETE")}
      />
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
      {controls && ownRole && (
        <Confirmation
          message={`Change your role to ${ownRole.role}? You will no longer be an owner.`}
          confirm="Yes, change my role"
          onConfirm={() => {
            onSetRole(ownRole.member, ownRole.role);
            setOwnRole(null);
          }}
          onCancel={() => setOwnRole(null)}
        />
      )}
    </section>
  );
}

/**
 * The connections who are not members and have no pending invite. A pending invite shows
 * the invitee by phone number only, so it is matched by phone number.
 */
function invitable(
  connections: Connection[],
  members: Member[],
  invites: InventoryInvite[],
): Connection["user"][] {
  const memberIds = new Set(members.map((member) => member.id));
  const invited = new Set(invites.map((invite) => invite.invitee.phone_number));
  return connections
    .map((connection) => connection.user)
    .filter((user) => !memberIds.has(user.id) && !invited.has(user.phone_number));
}

interface InvitesProps {
  invites: InventoryInvite[];
  invitable: Connection["user"][];
  send: Send;
  sent: number;
  base: string;
  reload: () => void;
  onRevoke: (invite: InventoryInvite) => void;
}

function Invites({ invites, invitable, send, sent, base, reload, onRevoke }: InvitesProps) {
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
      <Picker
        options={invitable.map((user) => ({
          id: user.id,
          name: fullName(user),
          label: [fullName(user), formatPhoneNumber(user.phone_number)].join(", "),
        }))}
        field="user_id"
        label="Connection"
        action="Invite"
        notDone="was not invited"
        unknown="That person"
        empty={
          <>
            No connections to invite. Find people in{" "}
            <Link to="/connections">My connections</Link>.
          </>
        }
        path={`${base}invites/`}
        send={send}
        sent={sent}
        reload={reload}
      />
    </section>
  );
}

/** The caller's items that are not listed in this inventory. */
function listable(myItems: Item[], listed: ListedItem[]): Item[] {
  const listedIds = new Set(listed.map((item) => item.id));
  return myItems.filter((item) => !listedIds.has(item.id));
}

interface ItemsProps {
  listed: ListedItem[];
  /** The items the caller may list here, or `null` for a `member`, who lists nothing. */
  listable: Item[] | null;
  removable: (item: ListedItem) => boolean;
  send: Send;
  sent: number;
  base: string;
  reload: () => void;
  onRemove: (item: ListedItem) => void;
}

function Items({ listed, listable, removable, send, sent, base, reload, onRemove }: ItemsProps) {
  return (
    <section aria-labelledby="items">
      <h3 id="items">Items</h3>
      {listed.length === 0 ? (
        <p>No items listed yet.</p>
      ) : (
        <ul>
          {listed.map((item) => (
            <li key={item.id}>
              <span>{`${describeItem(item)}, owned by ${fullName(item.owner)}`}</span>
              {removable(item) && (
                <>
                  {" "}
                  <button
                    type="button"
                    aria-label={`Remove ${item.name} from the inventory`}
                    onClick={() => onRemove(item)}
                  >
                    Remove
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {listable && (
        <Picker
          options={listable.map((item) => ({ id: item.id, name: item.name, label: item.name }))}
          field="item_id"
          label="Item"
          action="List item"
          notDone="was not listed"
          unknown="That item"
          empty={
            <>
              No items to list. Add gear in <Link to="/gear">My gear</Link>.
            </>
          }
          path={`${base}items/`}
          send={send}
          sent={sent}
          reload={reload}
        />
      )}
    </section>
  );
}

interface PickerOption {
  id: number;
  /** What a refusal message calls the option. */
  name: string;
  label: string;
}

interface PickerProps {
  options: PickerOption[];
  /** The body field that carries the chosen option's id. */
  field: string;
  label: string;
  action: string;
  /** Follows the option's name in a refusal, such as "was not invited". */
  notDone: string;
  /** Stands in for the name of an option that is no longer offered. */
  unknown: string;
  /** Shown instead of the form when there are no options. */
  empty: ReactNode;
  path: string;
  send: Send;
  /** The page's count of changes sent. A change from elsewhere on the page clears the errors. */
  sent: number;
  reload: () => void;
}

/** A select of options and a button that POSTs the chosen one's id to `path`. */
function Picker({
  options,
  field,
  label,
  action,
  notDone,
  unknown,
  empty,
  path,
  send,
  sent,
  reload,
}: PickerProps) {
  const [errors, setErrors] = useState<FieldErrors>({});
  useEffect(() => setErrors({}), [sent]);
  const container = useRef<HTMLDivElement>(null);
  const emptyState = useRef<HTMLParagraphElement>(null);
  const hadForm = useRef(options.length > 0);

  // The form unmounts when the last option leaves the picker; focus would drop to the page.
  useEffect(() => {
    const hasForm = options.length > 0;
    if (hadForm.current && !hasForm) {
      (
        container.current?.querySelector<HTMLElement>('[role="alert"]') ?? emptyState.current
      )?.focus();
    }
    hadForm.current = hasForm;
  }, [options.length]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = Number(new FormData(event.currentTarget).get(field));
    const failed = await send(path, "POST", { body: { [field]: id }, fields: [field] });
    // A 400 or 409 means the chosen option was refused. It may leave the picker on reload,
    // so the message names it and sits above the picker instead of beside whichever option
    // the select falls back to. After a 5xx or no response the change may have gone
    // through, so the message stands alone and a network failure reloads to show it.
    const refused = options.find((option) => option.id === id);
    const reasons = [...(failed?.errors[field] ?? []), ...(failed?.errors.form ?? [])];
    const refusal = failed?.status === 400 || failed?.status === 409;
    setErrors(
      refusal && reasons.length > 0
        ? { form: [`${refused ? refused.name : unknown} ${notDone}. ${reasons.join(" ")}`] }
        : (failed?.errors ?? {}),
    );
    if (!failed || failed.status === null) reload();
  }

  return (
    <div ref={container}>
      <FormErrors errors={errors} />
      {options.length === 0 ? (
        <p ref={emptyState} tabIndex={-1}>
          {empty}
        </p>
      ) : (
        <form onSubmit={submit} noValidate>
          <p>
            <label htmlFor={field}>{label}</label>{" "}
            <select id={field} name={field}>
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>{" "}
            <button type="submit">{action}</button>
          </p>
        </form>
      )}
    </div>
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
    setErrors(failed?.errors ?? {});
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
        <Confirmation
          message={`Delete ${name}? This cannot be undone.`}
          confirm="Yes, delete"
          onConfirm={onDelete}
          onCancel={() => setConfirming(false)}
        />
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
