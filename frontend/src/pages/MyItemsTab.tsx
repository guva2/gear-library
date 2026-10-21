import { useEffect, useRef, useState, type FormEvent } from "react";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import {
  Confirmation,
  Field,
  FormErrors,
  unreachable,
  useChange,
  useFocusFirstInvalid,
} from "../forms";
import { useAuth } from "../auth";
import { getJson } from "../inventories";
import { borrowerText, describeItem, type Item } from "../items";
import { useLoad } from "../load";

const FIELDS = ["name", "description"] as const;

function itemFields(form: HTMLFormElement) {
  const data = new FormData(form);
  return { name: data.get("name"), description: data.get("description") };
}

function listedIn(item: Item): string {
  if (item.inventories.length === 0) return "Not listed in any inventory.";
  return `Listed in ${item.inventories.map((inventory) => inventory.name).join(", ")}.`;
}

/** True while the signed-in user, the item's owner, uses it. */
function inUse(item: Item, userId: number | undefined): boolean {
  return item.loan_status === "on_loan" && item.borrower?.id === userId;
}

function loanState(item: Item, userId: number | undefined): string {
  if (!item.borrower) return "Available.";
  if (inUse(item, userId)) return "In use by you.";
  const state = borrowerText(item.loan_status, item.borrower);
  return item.loan_inventory ? `${state}, through ${item.loan_inventory.name}.` : `${state}.`;
}

/** Every item the signed-in user owns, listed or not. */
export default function MyItemsTab() {
  const [page, reload] = useLoad((signal) => getJson<Item[]>("/api/items/", signal));
  const { errors, setErrors, change, begin, sent } = useChange(reload);

  return (
    <>
      <FormErrors errors={errors} />
      {page.status === "loading" && <p>Loading…</p>}
      {page.status === "error" && <p role="alert">Could not load your items.</p>}
      {page.status === "ok" && (
        <ItemList
          items={page.data}
          reload={reload}
          onSubmit={begin}
          sent={sent}
          onGone={(errors) => {
            if (errors) setErrors(errors);
            reload();
          }}
          onDelete={(item) => change(`/api/items/${item.id}/`, "DELETE")}
          onReturn={(item, borrowerId) =>
            change(`/api/items/${item.id}/return/`, "POST", { borrower_id: borrowerId })
          }
          onUse={(item) => change(`/api/items/${item.id}/use/`, "POST")}
        />
      )}
      <AddItem reload={reload} onSubmit={begin} sent={sent} />
    </>
  );
}

interface ItemListProps {
  items: Item[];
  reload: () => void;
  /** Called when an edit is submitted. Returns whether the edit is still the latest change. */
  onSubmit: () => () => boolean;
  /** The page's count of changes started. A change from elsewhere on the page clears the errors. */
  sent: number;
  /**
   * Called when an edit was refused because the item no longer exists, with its errors, or
   * `null` when a later change was sent meanwhile.
   */
  onGone: (errors: FieldErrors | null) => void;
  onDelete: (item: Item) => void;
  /** Called with the borrower the page showed. */
  onReturn: (item: Item, borrowerId: number) => void;
  onUse: (item: Item) => void;
}

function ItemList({
  items,
  reload,
  onSubmit,
  sent,
  onGone,
  onDelete,
  onReturn,
  onUse,
}: ItemListProps) {
  const { user } = useAuth();
  const [editing, setEditing] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<Item | null>(null);
  const list = useRef<HTMLUListElement>(null);
  // The item whose edit form just closed. The form held focus, so its Edit button takes it.
  const closed = useRef<number | null>(null);

  useEffect(() => {
    if (closed.current === null) return;
    const button = list.current?.querySelector<HTMLElement>(`[data-edit="${closed.current}"]`);
    if (!button) return;
    button.focus();
    closed.current = null;
  }, [editing, items]);

  function close(item: Item) {
    closed.current = item.id;
    setEditing(null);
  }

  return (
    <section aria-labelledby="my-items">
      <h3 id="my-items">My items</h3>
      {items.length === 0 ? (
        <p>You have no gear yet.</p>
      ) : (
        <ul ref={list}>
          {items.map((item) => (
            <li key={item.id}>
              {editing === item.id ? (
                <EditItem
                  item={item}
                  onSubmit={onSubmit}
                  sent={sent}
                  onSaved={() => {
                    close(item);
                    reload();
                  }}
                  onGone={(errors) => {
                    setEditing(null);
                    onGone(errors);
                  }}
                  onCancel={() => close(item)}
                />
              ) : (
                <>
                  <p>{describeItem(item)}</p>
                  <p>{listedIn(item)}</p>
                  <p>{loanState(item, user?.id)}</p>
                  <p>
                    <button
                      type="button"
                      data-edit={item.id}
                      aria-label={`Edit ${item.name}`}
                      onClick={() => setEditing(item.id)}
                    >
                      Edit
                    </button>{" "}
                    <button
                      type="button"
                      aria-label={`Delete ${item.name}`}
                      onClick={() => setDeleting(item)}
                    >
                      Delete
                    </button>
                    {" "}
                    <LoanButton
                      item={item}
                      inUse={inUse(item, user?.id)}
                      onReturn={onReturn}
                      onUse={onUse}
                    />
                  </p>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {deleting && (
        <Confirmation
          message={`Delete ${deleting.name}? This cannot be undone.`}
          confirm="Yes, delete"
          onConfirm={() => {
            onDelete(deleting);
            setDeleting(null);
          }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </section>
  );
}

interface LoanButtonProps {
  item: Item;
  inUse: boolean;
  onReturn: (item: Item, borrowerId: number) => void;
  onUse: (item: Item) => void;
}

/**
 * Use it myself while the item is available, Done using it while the owner uses it, and
 * Mark returned while someone else has it on loan. One button, so focus stays on it when
 * the item changes state.
 */
function LoanButton({ item, inUse, onReturn, onUse }: LoanButtonProps) {
  const borrower = item.borrower;
  let action: { label: string; name: string; run: () => void };
  if (item.loan_status === "available") {
    action = {
      label: "Use it myself",
      name: `Use it myself: ${item.name}`,
      run: () => onUse(item),
    };
  } else if (item.loan_status === "on_loan" && borrower) {
    const run = () => onReturn(item, borrower.id);
    action = inUse
      ? { label: "Done using it", name: `Done using it: ${item.name}`, run }
      : { label: "Mark returned", name: `Mark returned: ${item.name}`, run };
  } else {
    return null;
  }
  return (
    <button type="button" aria-label={action.name} onClick={action.run}>
      {action.label}
    </button>
  );
}

interface EditItemProps {
  item: Item;
  onSubmit: () => () => boolean;
  /** The page's count of changes started. A change from elsewhere on the page clears the errors. */
  sent: number;
  onSaved: () => void;
  onGone: (errors: FieldErrors | null) => void;
  onCancel: () => void;
}

function EditItem({ item, onSubmit, sent, onSaved, onGone, onCancel }: EditItemProps) {
  const [errors, setErrors] = useState<FieldErrors>({});
  useEffect(() => setErrors({}), [sent]);
  const formRef = useFocusFirstInvalid(errors);

  useEffect(() => {
    formRef.current?.querySelector<HTMLElement>("input")?.focus();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const isLatest = onSubmit();
    try {
      const response = await apiFetch(`/api/items/${item.id}/`, {
        method: "PATCH",
        body: itemFields(event.currentTarget),
      });
      if (response.ok) onSaved();
      else if (response.status === 404) {
        const errors = await readErrors(response, []);
        onGone(isLatest() ? errors : null);
      } else {
        const errors = await readErrors(response, FIELDS);
        if (isLatest()) setErrors(errors);
      }
    } catch {
      if (isLatest()) setErrors(unreachable());
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} noValidate>
      <fieldset>
        <legend>Edit {item.name}</legend>
        <FormErrors errors={errors} />
        <Field id="edit-name" name="name" label="Name" errors={errors} defaultValue={item.name} />
        <Field
          id="edit-description"
          name="description"
          label="Description"
          errors={errors}
          required={false}
          defaultValue={item.description}
        />
        <button type="submit">Save</button>{" "}
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </fieldset>
    </form>
  );
}

interface AddItemProps {
  reload: () => void;
  /** Called when the form is submitted. Returns whether it is still the latest change. */
  onSubmit: () => () => boolean;
  /** The page's count of changes started. A change from elsewhere on the page clears the errors. */
  sent: number;
}

function AddItem({ reload, onSubmit, sent }: AddItemProps) {
  const [errors, setErrors] = useState<FieldErrors>({});
  useEffect(() => setErrors({}), [sent]);
  const formRef = useFocusFirstInvalid(errors);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const isLatest = onSubmit();
    try {
      const response = await apiFetch("/api/items/", { method: "POST", body: itemFields(form) });
      if (!response.ok) {
        const errors = await readErrors(response, FIELDS);
        if (isLatest()) setErrors(errors);
        return;
      }
      setErrors({});
      form.reset();
      reload();
    } catch {
      if (isLatest()) setErrors(unreachable());
    }
  }

  return (
    <section aria-labelledby="add-item">
      <h3 id="add-item">Add an item</h3>
      <form ref={formRef} onSubmit={submit} noValidate>
        <FormErrors errors={errors} />
        <Field name="name" label="Name" errors={errors} />
        <Field name="description" label="Description" errors={errors} required={false} />
        <button type="submit">Add</button>
      </form>
    </section>
  );
}
