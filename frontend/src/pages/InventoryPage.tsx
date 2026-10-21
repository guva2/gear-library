import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { useAuth } from "../auth";
import type { Connection } from "../connections";
import {
  Confirmation,
  Field,
  FormErrors,
  unreachable,
  useFocusFirstInvalid,
  useLatestChange,
} from "../forms";
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
import {
  borrowerText,
  describeItem,
  LOAN_STATUS_LABELS,
  type BorrowedItem,
  type Item,
  type ListedItem,
} from "../items";
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
  /** Ids of the items the caller holds, through any inventory, and may mark returned. */
  heldReturnable: ReadonlySet<number>;
}

async function loadPage(base: string, signal: AbortSignal): Promise<PageData> {
  const inventory = await getJson<Inventory>(base, signal);
  const staff = hasRole(inventory.role, "admin");
  const [people, invites, connections, listed, myItems, borrowed] = await Promise.all([
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
    getJson<BorrowedItem[]>("/api/borrowing/", signal),
  ]);
  const heldReturnable = new Set(
    borrowed
      .filter((item) => item.loan_status === "on_loan" && item.can_return)
      .map((item) => item.id),
  );
  return { inventory, people, invites, connections, listed, myItems, heldReturnable };
}

type Method = "POST" | "PATCH" | "DELETE";

type Send = (
  path: string,
  method: Method,
  options?: { body?: unknown; fields?: readonly string[] },
) => Promise<Reply>;

/** A change that did not succeed. `status` is `null` when there was no response. */
interface Failure {
  errors: FieldErrors;
  status: number | null;
}

interface Reply {
  /** `null` when the change succeeded. */
  failure: Failure | null;
  /** False when a later change was sent from the page: the caller shows no message. */
  latest: boolean;
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
      Inventory not found. <Link to="/manage/inventories">Back to my inventories</Link>
    </p>
  );
}

function InventoryView({ base }: { base: string }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [page, reload] = useLoad((signal) => loadPage(base, signal));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [refusal, setRefusal] = useState<FieldErrors>({});
  // Counts the changes sent from this page. A form that keeps its own errors clears them
  // when the count changes.
  const [sent, setSent] = useState(0);
  const start = useLatestChange();

  /**
   * Sends a change. Returns the failure for the caller to show, or `null` when it succeeded.
   * A 403 is shown here instead and returns no errors: the caller has lost a role, and the
   * reload can remove the section that sent the change.
   */
  const send: Send = async (path, method, { body, fields = [] } = {}) => {
    setRefusal({});
    setErrors({});
    setSent((count) => count + 1);
    const isLatest = start();
    try {
      const response = await apiFetch(path, { method, body });
      if (response.ok) return { failure: null, latest: isLatest() };
      const errors = await readErrors(response, fields);
      // The refusal may come from a change someone else made; show the current state.
      reload();
      if (response.status !== 403) {
        return { failure: { errors, status: response.status }, latest: isLatest() };
      }
      if (isLatest()) setRefusal(errors);
      return { failure: { errors: {}, status: 403 }, latest: isLatest() };
    } catch {
      return { failure: { errors: unreachable(), status: null }, latest: isLatest() };
    }
  };

  async function act(path: string, method: Method, body?: unknown) {
    const { failure, latest } = await send(path, method, { body });
    if (latest) setErrors(failure?.errors ?? {});
    if (!failure) reload();
  }

  async function leaveOrDelete(path: string) {
    const { failure, latest } = await send(path, "DELETE");
    if (!failure) navigate("/manage/inventories");
    else if (latest) setErrors(failure.errors);
  }

  if (page.status === "loading") return <p>Loading…</p>;
  if (page.status === "error") {
    if (page.error instanceof HttpError && page.error.status === 404) return <NotFound />;
    return <p role="alert">Could not load the inventory.</p>;
  }

  const { inventory, people, invites, connections, listed, myItems, heldReturnable } =
    page.data;
  const isOwner = inventory.role === "owner";
  const myItemIds = new Set(myItems.map((item) => item.id));
  return (
    <>
      <h2>{inventory.name}</h2>
      <p>Your role: {inventory.role}</p>
      <p>
        <Link to="/manage/inventories">My inventories</Link>
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
        staff={people.staff}
        listable={people.staff ? listable(myItems, listed) : null}
        removable={(item) => people.staff && (isOwner || myItemIds.has(item.id))}
        owned={(item) => myItemIds.has(item.id)}
        heldReturnable={heldReturnable}
        send={send}
        sent={sent}
        base={base}
        reload={reload}
        onRemove={(item) => act(`${base}items/${item.id}/`, "DELETE")}
        onLoanChange={(path, body) => act(path, "POST", body)}
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
          sent={sent}
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
      {/* Focusable so a keyboard user can scroll it when the table is wider than the screen. */}
      <div className="table-scroll" role="region" aria-label="Members table" tabIndex={0}>
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
      </div>
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

interface Holding {
  item: ListedItem;
  /** True for the caller's own items. */
  owned: boolean;
  /** True when the caller is an admin or owner here. */
  staff: boolean;
  base: string;
}

/**
 * Where the caller marks an item they hold returned: as its owner, or as an admin or owner
 * here when the item's `borrower` is present. `null` when they do not hold it or may not
 * mark it returned.
 */
function holderReturnPath({ item, owned, staff, base }: Holding): string | null {
  if (item.loan_status !== "on_loan" || !item.borrowed_by_me) return null;
  if (owned) return `/api/items/${item.id}/return/`;
  if (staff && item.borrower) return `${base}items/${item.id}/return/`;
  return null;
}

/**
 * The loan status, with who has requested or borrowed the item when the caller may see it.
 * `heldReturnable` is true when the caller holds the item through any inventory and may
 * mark it returned themselves.
 */
function loanText(holding: Holding, heldReturnable: boolean): string {
  const { item } = holding;
  if (heldReturnable || holderReturnPath(holding)) return "In use by you";
  const borrower = item.borrowed_by_me ? "you" : item.borrower;
  if (!borrower) return LOAN_STATUS_LABELS[item.loan_status];
  return borrowerText(item.loan_status, borrower);
}

interface LoanButtonsProps extends Holding {
  userId: number | undefined;
  onLoanChange: (path: string, body?: unknown) => void;
}

/**
 * The loan changes the caller may make. Approve, decline and mark returned send the
 * borrower the page showed. Use it myself and Done using it share a key, so the button
 * keeps focus when the item changes between them.
 */
function LoanButtons({ userId, onLoanChange, ...holding }: LoanButtonsProps) {
  const { item, owned, staff, base } = holding;
  const path = `${base}items/${item.id}/`;
  const buttons: { key?: string; label: string; name: string; onClick: () => void }[] = [];
  const asStaff = item.borrower && !item.borrowed_by_me ? { borrower_id: item.borrower.id } : null;
  const returnPath = holderReturnPath(holding);
  if (item.loan_status === "available" && (owned || staff)) {
    buttons.push({
      key: "availability",
      label: "Use it myself",
      name: `Use it myself: ${item.name}`,
      onClick: () => onLoanChange(owned ? `/api/items/${item.id}/use/` : `${path}borrow/`),
    });
  } else if (item.loan_status === "available") {
    buttons.push({
      label: "Ask to borrow",
      name: `Ask to borrow: ${item.name}`,
      onClick: () => onLoanChange(`${path}borrow/`),
    });
  }
  if (returnPath && userId !== undefined) {
    buttons.push({
      key: "availability",
      label: "Done using it",
      name: `Done using it: ${item.name}`,
      onClick: () => onLoanChange(returnPath, { borrower_id: userId }),
    });
  }
  if (item.loan_status === "requested" && item.borrowed_by_me) {
    buttons.push({
      label: "Cancel request",
      name: `Cancel request: ${item.name}`,
      onClick: () => onLoanChange(`/api/borrowing/${item.id}/cancel/`),
    });
  }
  if (item.loan_status === "requested" && asStaff) {
    buttons.push(
      {
        label: "Approve",
        name: `Approve: ${item.name}`,
        onClick: () => onLoanChange(`${path}approve/`, asStaff),
      },
      {
        label: "Decline",
        name: `Decline: ${item.name}`,
        onClick: () => onLoanChange(`${path}decline/`, asStaff),
      },
    );
  }
  if (item.loan_status === "on_loan" && asStaff) {
    buttons.push({
      label: "Mark returned",
      name: `Mark returned: ${item.name}`,
      onClick: () => onLoanChange(`${path}return/`, asStaff),
    });
  }
  return buttons.map((button) => (
    <span key={button.key ?? button.name}>
      {" "}
      <button type="button" aria-label={button.name} onClick={button.onClick}>
        {button.label}
      </button>
    </span>
  ));
}

interface ItemsProps {
  listed: ListedItem[];
  /** True when the caller is an admin or owner here. */
  staff: boolean;
  /** The items the caller may list here, or `null` for a `member`, who lists nothing. */
  listable: Item[] | null;
  removable: (item: ListedItem) => boolean;
  /** True for the caller's own items. */
  owned: (item: ListedItem) => boolean;
  /** Ids of the items the caller holds, through any inventory, and may mark returned. */
  heldReturnable: ReadonlySet<number>;
  send: Send;
  sent: number;
  base: string;
  reload: () => void;
  onRemove: (item: ListedItem) => void;
  onLoanChange: (path: string, body?: unknown) => void;
}

function Items({
  listed,
  staff,
  listable,
  removable,
  owned,
  heldReturnable,
  send,
  sent,
  base,
  reload,
  onRemove,
  onLoanChange,
}: ItemsProps) {
  const { user } = useAuth();
  return (
    <section aria-labelledby="items">
      <h3 id="items">Items</h3>
      {listed.length === 0 ? (
        <p>No items listed yet.</p>
      ) : (
        <ul>
          {listed.map((item) => (
            <li key={item.id}>
              <span>{`${describeItem(item)}, owned by ${fullName(item.owner)}`}</span>{" "}
              <span>{loanText({ item, owned: owned(item), staff, base }, heldReturnable.has(item.id))}</span>
              <LoanButtons
                item={item}
                owned={owned(item)}
                staff={staff}
                base={base}
                userId={user?.id}
                onLoanChange={onLoanChange}
              />
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
          options={listable.map((item) => ({
            id: item.id,
            name: `"${describeItem(item)}"`,
            label: describeItem(item),
          }))}
          field="item_id"
          label="Item"
          action="List item"
          notDone="was not listed"
          unknown="That item"
          empty={
            <>
              No items to list. Add gear in <Link to="/manage/items">My items</Link>.
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
    const { failure: failed, latest } = await send(path, "POST", {
      body: { [field]: id },
      fields: [field],
    });
    // A 400 or 409 means the chosen option was refused. It may leave the picker on reload,
    // so the message names it and sits above the picker instead of beside whichever option
    // the select falls back to. After a 5xx or no response the change may have gone
    // through, so the message stands alone and a network failure reloads to show it.
    const refused = options.find((option) => option.id === id);
    const reasons = [...(failed?.errors[field] ?? []), ...(failed?.errors.form ?? [])];
    const refusal = failed?.status === 400 || failed?.status === 409;
    if (latest) {
      setErrors(
        refusal && reasons.length > 0
          ? { form: [`${refused ? refused.name : unknown} ${notDone}. ${reasons.join(" ")}`] }
          : (failed?.errors ?? {}),
      );
    }
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
  /** The page's count of changes sent. A change from elsewhere on the page clears the errors. */
  sent: number;
  base: string;
  reload: () => void;
  onDelete: () => void;
}

function Manage({ name, send, sent, base, reload, onDelete }: ManageProps) {
  const [errors, setErrors] = useState<FieldErrors>({});
  useEffect(() => setErrors({}), [sent]);
  const [confirming, setConfirming] = useState(false);
  const formRef = useFocusFirstInvalid(errors);

  async function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const { failure: failed, latest } = await send(base, "PATCH", {
      body: { name: new FormData(form).get("name") },
      fields: ["name"],
    });
    if (latest) setErrors(failed?.errors ?? {});
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
