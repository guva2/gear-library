import { useEffect, useRef, useState, type FormEvent } from "react";
import { FormErrors, useChange } from "../forms";
import { fullName, getJson } from "../inventories";
import { LOAN_STATUS_LABELS, type DiscoverItem } from "../items";
import { useLoad } from "../load";

function statusText(item: DiscoverItem): string {
  if (!item.borrowed_by_me) return LOAN_STATUS_LABELS[item.loan_status];
  return item.loan_status === "requested" ? "Requested by you" : "On loan to you";
}

/** The items in the signed-in user's inventories that someone else owns. */
export default function DiscoverPage() {
  const [page, reload] = useLoad((signal) => getJson<DiscoverItem[]>("/api/discover/", signal));
  const { errors, change } = useChange(reload);

  return (
    <>
      <h2>Discover</h2>
      <FormErrors errors={errors} />
      {page.status === "loading" && <p>Loading…</p>}
      {page.status === "error" && <p role="alert">Could not load the items.</p>}
      {page.status === "ok" &&
        (page.data.length === 0 ? (
          <p>Nothing to discover yet. Items others list in your inventories show up here.</p>
        ) : (
          <ul className="cards">
            {page.data.map((item) => (
              <ItemCard
                key={item.id}
                item={item}
                onRequest={(inventoryId) =>
                  change(`/api/inventories/${inventoryId}/items/${item.id}/borrow/`, "POST")
                }
              />
            ))}
          </ul>
        ))}
    </>
  );
}

interface ItemCardProps {
  item: DiscoverItem;
  /** Called with the inventory to request the item through. */
  onRequest: (inventoryId: number) => void;
}

function ItemCard({ item, onRequest }: ItemCardProps) {
  const available = item.loan_status === "available";
  const heading = useRef<HTMLHeadingElement>(null);
  const wasAvailable = useRef(available);

  // The request control unmounts once the item is no longer available; focus would drop to the page.
  useEffect(() => {
    if (wasAvailable.current && !available) heading.current?.focus();
    wasAvailable.current = available;
  }, [available]);

  return (
    <li className={available ? "card" : "card unavailable"}>
      <h3 ref={heading} tabIndex={-1}>
        {item.name}
      </h3>
      {item.description && <p>{item.description}</p>}
      <p className="meta">Owned by {fullName(item.owner)}</p>
      <p className="meta">In {item.inventories.map((inventory) => inventory.name).join(", ")}</p>
      <p className="status">{statusText(item)}</p>
      {available && <RequestButton item={item} onRequest={onRequest} />}
    </li>
  );
}

/**
 * Requests the item. An item listed in several of the user's inventories first asks which
 * one to request through, with the first preselected.
 */
function RequestButton({ item, onRequest }: ItemCardProps) {
  const [choosing, setChoosing] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const select = useRef<HTMLSelectElement>(null);
  // Set when the choice closes: the closed form held focus.
  const refocus = useRef(false);
  const selectId = `request-through-${item.id}`;

  useEffect(() => {
    if (choosing) select.current?.focus();
    else if (refocus.current) {
      button.current?.focus();
      refocus.current = false;
    }
  }, [choosing]);

  function start() {
    if (item.inventories.length === 1) onRequest(item.inventories[0].id);
    else setChoosing(true);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onRequest(Number(new FormData(event.currentTarget).get("inventory")));
    refocus.current = true;
    setChoosing(false);
  }

  if (!choosing) {
    return (
      <p>
        <button ref={button} type="button" aria-label={`Request ${item.name}`} onClick={start}>
          Request
        </button>
      </p>
    );
  }
  return (
    <form onSubmit={submit}>
      <p>
        <label htmlFor={selectId}>Request through</label>{" "}
        <select ref={select} id={selectId} name="inventory">
          {item.inventories.map((inventory) => (
            <option key={inventory.id} value={inventory.id}>
              {inventory.name}
            </option>
          ))}
        </select>
      </p>
      <p>
        <button type="submit">Send request</button>{" "}
        <button
          type="button"
          onClick={() => {
            refocus.current = true;
            setChoosing(false);
          }}
        >
          Cancel
        </button>
      </p>
    </form>
  );
}
