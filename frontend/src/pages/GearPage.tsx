import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { apiFetch, readErrors, type FieldErrors } from "../api";
import { Confirmation, Field, FormErrors, unreachable, useFocusFirstInvalid } from "../forms";
import { getJson } from "../inventories";
import { describeItem, type Item } from "../items";
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

export default function GearPage() {
  const [page, reload] = useLoad((signal) => getJson<Item[]>("/api/items/", signal));
  const [errors, setErrors] = useState<FieldErrors>({});

  async function remove(item: Item) {
    setErrors({});
    try {
      const response = await apiFetch(`/api/items/${item.id}/`, { method: "DELETE" });
      if (!response.ok) setErrors(await readErrors(response, []));
      reload();
    } catch {
      setErrors(unreachable());
    }
  }

  return (
    <>
      <h2>My gear</h2>
      <p>
        <Link to="/">My inventories</Link>
      </p>
      <FormErrors errors={errors} />
      {page.status === "loading" && <p>Loading…</p>}
      {page.status === "error" && <p role="alert">Could not load your gear.</p>}
      {page.status === "ok" && (
        <ItemList
          items={page.data}
          reload={reload}
          onGone={(errors) => {
            setErrors(errors);
            reload();
          }}
          onDelete={remove}
        />
      )}
      <AddItem reload={reload} />
    </>
  );
}

interface ItemListProps {
  items: Item[];
  reload: () => void;
  /** Called with the errors of an edit refused because the item no longer exists. */
  onGone: (errors: FieldErrors) => void;
  onDelete: (item: Item) => void;
}

function ItemList({ items, reload, onGone, onDelete }: ItemListProps) {
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

interface EditItemProps {
  item: Item;
  onSaved: () => void;
  onGone: (errors: FieldErrors) => void;
  onCancel: () => void;
}

function EditItem({ item, onSaved, onGone, onCancel }: EditItemProps) {
  const [errors, setErrors] = useState<FieldErrors>({});
  const formRef = useFocusFirstInvalid(errors);

  useEffect(() => {
    formRef.current?.querySelector<HTMLElement>("input")?.focus();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const response = await apiFetch(`/api/items/${item.id}/`, {
        method: "PATCH",
        body: itemFields(event.currentTarget),
      });
      if (response.ok) onSaved();
      else if (response.status === 404) onGone(await readErrors(response, []));
      else setErrors(await readErrors(response, FIELDS));
    } catch {
      setErrors(unreachable());
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

function AddItem({ reload }: { reload: () => void }) {
  const [errors, setErrors] = useState<FieldErrors>({});
  const formRef = useFocusFirstInvalid(errors);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      const response = await apiFetch("/api/items/", { method: "POST", body: itemFields(form) });
      if (!response.ok) {
        setErrors(await readErrors(response, FIELDS));
        return;
      }
      setErrors({});
      form.reset();
      reload();
    } catch {
      setErrors(unreachable());
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
