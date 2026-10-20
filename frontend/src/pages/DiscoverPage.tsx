import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { FormErrors, useChange } from "../forms";
import { fullName, getJson, hasRole } from "../inventories";
import { LOAN_STATUS_LABELS, type BorrowedItem, type DiscoverItem } from "../items";
import { useLoad } from "../load";

interface PageData {
  items: DiscoverItem[];
  /** By item id, the return path of each item the signed-in user holds and may mark returned. */
  returnPaths: Map<number, string>;
}

async function loadPage(signal: AbortSignal): Promise<PageData> {
  const [items, borrowed] = await Promise.all([
    getJson<DiscoverItem[]>("/api/discover/", signal),
    getJson<BorrowedItem[]>("/api/borrowing/", signal),
  ]);
  const returnPaths = new Map<number, string>();
  for (const item of borrowed) {
    if (item.loan_status === "on_loan" && item.can_return && item.loan_inventory) {
      const path = `/api/inventories/${item.loan_inventory.id}/items/${item.id}/return/`;
      returnPaths.set(item.id, path);
    }
  }
  return { items, returnPaths };
}

function statusText(item: DiscoverItem, inUse: boolean): string {
  if (!item.borrowed_by_me) return LOAN_STATUS_LABELS[item.loan_status];
  if (inUse) return "In use by you";
  return item.loan_status === "requested" ? "Requested by you" : "On loan to you";
}

/** The items in the signed-in user's inventories that someone else owns. */
export default function DiscoverPage() {
  const { user } = useAuth();
  const [page, reload] = useLoad(loadPage);
  const { errors, change } = useChange(reload);
  // The item whose control was used last: only its card takes focus when it changes.
  const [actedOn, setActedOn] = useState<number | null>(null);

  return (
    <>
      <h2>Discover</h2>
      <FormErrors errors={errors} />
      {page.status === "loading" && <p>Loading…</p>}
      {page.status === "error" && <p role="alert">Could not load the items.</p>}
      {page.status === "ok" &&
        (page.data.items.length === 0 ? (
          <p>Nothing to discover yet. Items others list in your inventories show up here.</p>
        ) : (
          <ul className="cards">
            {page.data.items.map((item) => {
              const returnPath = page.data.returnPaths.get(item.id);
              return (
                <ItemCard
                  key={item.id}
                  item={item}
                  actedOn={actedOn === item.id}
                  onRequest={(inventoryId) => {
                    setActedOn(item.id);
                    change(`/api/inventories/${inventoryId}/items/${item.id}/borrow/`, "POST");
                  }}
                  onMarkAvailable={
                    returnPath && user
                      ? () => {
                          setActedOn(item.id);
                          change(returnPath, "POST", { borrower_id: user.id });
                        }
                      : undefined
                  }
                />
              );
            })}
          </ul>
        ))}
    </>
  );
}

interface ItemCardProps {
  item: DiscoverItem;
  /** True when the user's last action was on this card. */
  actedOn: boolean;
  /** Called with the inventory to borrow the item through. */
  onRequest: (inventoryId: number) => void;
  /** Set while the signed-in user holds the item and may mark it available. */
  onMarkAvailable?: () => void;
}

function ItemCard({ item, actedOn, onRequest, onMarkAvailable }: ItemCardProps) {
  const available = item.loan_status === "available";
  const heading = useRef<HTMLHeadingElement>(null);
  const wasAvailable = useRef(available);
  // The inventories where the user is an admin or owner. Through any of them they mark the
  // item unavailable without a request, whatever their role in the others.
  const usableThrough = item.inventories.filter((inventory) => hasRole(inventory.role, "admin"));

  // The card's controls unmount when the item changes between available and not; focus
  // would drop to the page. Only the card the user acted on takes it.
  useEffect(() => {
    if (actedOn && wasAvailable.current !== available) heading.current?.focus();
    wasAvailable.current = available;
  }, [available, actedOn]);

  return (
    <li className={available ? "card" : "card unavailable"}>
      <h3 ref={heading} tabIndex={-1}>
        {item.name}
      </h3>
      {item.description && <p>{item.description}</p>}
      <p className="meta">Owned by {fullName(item.owner)}</p>
      <p className="meta">In {item.inventories.map((inventory) => inventory.name).join(", ")}</p>
      <p className="status">{statusText(item, onMarkAvailable !== undefined)}</p>
      {available && (
        <BorrowButton
          item={item}
          inventories={usableThrough.length > 0 ? usableThrough : item.inventories}
          wording={usableThrough.length > 0 ? MARK_UNAVAILABLE : REQUEST}
          onRequest={onRequest}
        />
      )}
      {onMarkAvailable && (
        <p>
          <button
            type="button"
            aria-label={`Mark ${item.name} available`}
            onClick={onMarkAvailable}
          >
            Mark available
          </button>
        </p>
      )}
    </li>
  );
}

interface BorrowWording {
  button: string;
  /** The button's accessible name, given the item's name. */
  label: (itemName: string) => string;
  choose: string;
  submit: string;
  idPrefix: string;
}

const REQUEST: BorrowWording = {
  button: "Request",
  label: (itemName) => `Request ${itemName}`,
  choose: "Request through",
  submit: "Send request",
  idPrefix: "request-through",
};

const MARK_UNAVAILABLE: BorrowWording = {
  button: "Mark unavailable",
  label: (itemName) => `Mark ${itemName} unavailable`,
  choose: "Mark unavailable through",
  submit: "Mark unavailable",
  idPrefix: "use-through",
};

interface BorrowButtonProps extends Pick<ItemCardProps, "item" | "onRequest"> {
  /** The inventories offered to borrow through, in order; never empty. */
  inventories: DiscoverItem["inventories"];
  wording: BorrowWording;
}

/**
 * Borrows the item. With several inventories to borrow through it first asks which one,
 * with the first preselected.
 */
function BorrowButton({ item, inventories, wording, onRequest }: BorrowButtonProps) {
  const [choosing, setChoosing] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const select = useRef<HTMLSelectElement>(null);
  // Set when the choice closes: the closed form held focus.
  const refocus = useRef(false);
  const selectId = `${wording.idPrefix}-${item.id}`;

  useEffect(() => {
    if (choosing) select.current?.focus();
    else if (refocus.current) {
      button.current?.focus();
      refocus.current = false;
    }
  }, [choosing]);

  function start() {
    if (inventories.length === 1) onRequest(inventories[0].id);
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
        <button ref={button} type="button" aria-label={wording.label(item.name)} onClick={start}>
          {wording.button}
        </button>
      </p>
    );
  }
  return (
    <form onSubmit={submit}>
      <p>
        <label htmlFor={selectId}>{wording.choose}</label>{" "}
        <select ref={select} id={selectId} name="inventory">
          {inventories.map((inventory) => (
            <option key={inventory.id} value={inventory.id}>
              {inventory.name}
            </option>
          ))}
        </select>
      </p>
      <p>
        <button type="submit">{wording.submit}</button>{" "}
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
