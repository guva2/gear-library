import { useEffect, useRef, useState, type FormEvent } from "react";
import { useLocation, useSearchParams } from "react-router";
import { FormErrors, useChange } from "../forms";
import { fullName, getJson } from "../inventories";
import { borrowerText, LOAN_STATUS_LABELS, type DiscoverItem } from "../items";
import { useLoad } from "../load";

/** How long typing must pause before the search runs. */
const SEARCH_DELAY_MS = 300;
/** The page sends `q` only when it is at least this long once stripped; shorter lists
 * everything (see `docs/api.md`). */
const MIN_QUERY_LENGTH = 2;

/** The items found, with the query that found them. */
interface Found {
  query: string;
  items: DiscoverItem[];
}

async function loadItems(query: string, signal: AbortSignal): Promise<Found> {
  const search = query ? `?${new URLSearchParams({ q: query })}` : "";
  return { query, items: await getJson<DiscoverItem[]>(`/api/discover/${search}`, signal) };
}

/** The items the signed-in user can only borrow, narrowed by the search in `?q=`. */
export default function DiscoverPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const q = searchParams.get("q") ?? "";
  // What the box shows. It reaches the URL once typing pauses.
  const [text, setText] = useState(q);
  // The last `q` this page wrote: any other `q` came from navigation and replaces the text.
  const written = useRef(q);
  const trimmed = q.trim();
  const query = trimmed.length >= MIN_QUERY_LENGTH ? trimmed : "";
  const [found, reload] = useLoad((signal) => loadItems(query, signal), query);
  const { errors, change } = useChange(reload);
  // The item whose control was used last: only its card takes focus when it changes.
  const [actedOn, setActedOn] = useState<number | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (q !== written.current) {
      written.current = q;
      setText(q);
    }
  }, [q]);

  // Following any link here discards text still waiting for its delay. The page's own
  // writes are marked and left alone.
  useEffect(() => {
    if (!location.state?.written) setText(q);
    // Only a new location resets the box; `q` is read from the render that changed it.
  }, [location.key]);

  useEffect(() => {
    if (text === q) return;
    const timer = setTimeout(() => {
      written.current = text;
      setSearchParams(
        (params) => {
          const next = new URLSearchParams(params);
          if (text) next.set("q", text);
          else next.delete("q");
          return next;
        },
        { replace: true, state: { written: true } },
      );
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, q, setSearchParams]);

  // A new search is not a reaction to the last action, so it moves no focus.
  useEffect(() => setActedOn(null), [query]);

  // The acted-on card unmounts when the reload drops its item, and focus would fall to the
  // page body.
  useEffect(() => {
    if (
      actedOn !== null &&
      found.status === "ok" &&
      !found.data.items.some((i) => i.id === actedOn)
    ) {
      heading.current?.focus();
      setActedOn(null);
    }
  }, [found, actedOn]);

  return (
    <>
      <h2 ref={heading} tabIndex={-1}>
        Discover
      </h2>
      <p role="search">
        <label htmlFor="discover-search">Search</label>{" "}
        <input
          id="discover-search"
          type="search"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            // Typing is the latest action: a borrow still in flight must not take focus.
            setActedOn(null);
          }}
        />
      </p>
      <FormErrors errors={errors} />
      {found.status === "loading" && <p>Loading…</p>}
      {found.status === "error" && <p role="alert">Could not load the items.</p>}
      {found.status === "ok" &&
        (found.data.items.length === 0 ? (
          found.data.query ? (
            <p>No items match “{found.data.query}”.</p>
          ) : (
            <p>
              Nothing to borrow right now. Items others list in inventories where you are a
              member show up here.
            </p>
          )
        ) : (
          <ul className="cards">
            {found.data.items.map((item) => (
              <ItemCard
                key={item.id}
                item={item}
                actedOn={actedOn === item.id}
                onRequest={(inventoryId) => {
                  setActedOn(item.id);
                  change(`/api/inventories/${inventoryId}/items/${item.id}/borrow/`, "POST");
                }}
              />
            ))}
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
}

function ItemCard({ item, actedOn, onRequest }: ItemCardProps) {
  const available = item.loan_status === "available";
  const heading = useRef<HTMLHeadingElement>(null);
  const wasAvailable = useRef(available);

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
      <p className="status">
        {item.borrowed_by_me
          ? borrowerText(item.loan_status, "you")
          : LOAN_STATUS_LABELS[item.loan_status]}
      </p>
      {available && <BorrowButton item={item} onRequest={onRequest} />}
    </li>
  );
}

type BorrowButtonProps = Pick<ItemCardProps, "item" | "onRequest">;

/**
 * Borrows the item. With several inventories to borrow through it first asks which one,
 * with the first preselected.
 */
function BorrowButton({ item, onRequest }: BorrowButtonProps) {
  const { inventories } = item;
  const [choosing, setChoosing] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const select = useRef<HTMLSelectElement>(null);
  // Set when the choice closes: the closed form held focus.
  const refocus = useRef(false);
  const selectId = `borrow-through-${item.id}`;

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
        <button
          ref={button}
          type="button"
          aria-label={`Ask to borrow ${item.name}`}
          onClick={start}
        >
          Ask to borrow
        </button>
      </p>
    );
  }
  return (
    <form onSubmit={submit}>
      <p>
        <label htmlFor={selectId}>Borrow through</label>{" "}
        <select ref={select} id={selectId} name="inventory">
          {inventories.map((inventory) => (
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
