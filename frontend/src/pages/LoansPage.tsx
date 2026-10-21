import { useEffect, useRef } from "react";
import { useAuth } from "../auth";
import { FormErrors, useChange } from "../forms";
import { fullName, getJson } from "../inventories";
import { borrowerText, describeItem, type BorrowedItem, type LendingItem } from "../items";
import { useLoad } from "../load";

interface PageData {
  lending: LendingItem[];
  borrowed: BorrowedItem[];
}

async function loadPage(signal: AbortSignal): Promise<PageData> {
  const [lending, borrowed] = await Promise.all([
    getJson<LendingItem[]>("/api/lending/", signal),
    getJson<BorrowedItem[]>("/api/borrowing/", signal),
  ]);
  return { lending, borrowed };
}

function lendingText(item: LendingItem): string {
  const owner = item.owner ? `owned by ${fullName(item.owner)}` : "yours";
  const through = item.loan_inventory ? `, through ${item.loan_inventory.name}` : "";
  const state = borrowerText(item.loan_status, item.borrower);
  return `${describeItem(item)}, ${owner}. ${state}${through}.`;
}

/**
 * The return path for an item the signed-in user holds and may mark returned. The owner's
 * own use has no loan inventory; any other is returned through its loan inventory.
 */
function holderReturnPath(item: BorrowedItem): string {
  if (item.loan_inventory === null) return `/api/items/${item.id}/return/`;
  return `/api/inventories/${item.loan_inventory.id}/items/${item.id}/return/`;
}

function usingText(item: BorrowedItem): string {
  if (item.loan_inventory === null) return `${describeItem(item)}, yours. In use by you.`;
  const owned = `${describeItem(item)}, owned by ${fullName(item.owner)}.`;
  return `${owned} In use by you, through ${item.loan_inventory.name}.`;
}

function borrowedText(item: BorrowedItem): string {
  const owned = `${describeItem(item)}, owned by ${fullName(item.owner)}.`;
  const through = item.loan_inventory ? ` through ${item.loan_inventory.name}` : "";
  const state = borrowerText(item.loan_status, "you");
  return `${owned} ${state}${through}.`;
}

interface Action {
  label: string;
  name: string;
  run: () => void;
}

export default function LoansPage() {
  const { user } = useAuth();
  const [page, reload] = useLoad(loadPage);
  const { errors, change } = useChange(reload);
  // The button used last. A reload that unmounts it, by removing its item or moving the
  // item to another section, would drop focus to the page body.
  const actedOn = useRef<HTMLButtonElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (page.status === "loading" || actedOn.current === null) return;
    if (!actedOn.current.isConnected) heading.current?.focus();
    actedOn.current = null;
  }, [page]);

  function act(button: HTMLButtonElement, action: Action) {
    actedOn.current = button;
    action.run();
  }

  /**
   * The signed-in user's own item is returned as its owner, anyone else's through its loan
   * inventory.
   */
  function returnPath(item: LendingItem): string | null {
    if (item.owner === null) return `/api/items/${item.id}/return/`;
    if (item.loan_inventory === null) return null;
    return `/api/inventories/${item.loan_inventory.id}/items/${item.id}/return/`;
  }

  function answers(item: LendingItem): Action[] {
    const inventory = item.loan_inventory;
    if (!item.can_answer || inventory === null) return [];
    const path = `/api/inventories/${inventory.id}/items/${item.id}/`;
    const body = { borrower_id: item.borrower.id };
    return [
      {
        label: "Approve",
        name: `Approve: ${item.name}`,
        run: () => change(`${path}approve/`, "POST", body),
      },
      {
        label: "Decline",
        name: `Decline: ${item.name}`,
        run: () => change(`${path}decline/`, "POST", body),
      },
    ];
  }

  function returning(item: LendingItem): Action[] {
    const path = returnPath(item);
    if (path === null) return [];
    const body = { borrower_id: item.borrower.id };
    return [
      {
        label: "Mark returned",
        name: `Mark returned: ${item.name}`,
        run: () => change(path, "POST", body),
      },
    ];
  }

  function markingAvailable(item: BorrowedItem): Action[] {
    if (!user) return [];
    const body = { borrower_id: user.id };
    return [
      {
        label: "Done using it",
        name: `Done using it: ${item.name}`,
        run: () => change(holderReturnPath(item), "POST", body),
      },
    ];
  }

  function cancelling(item: BorrowedItem): Action[] {
    return [
      {
        label: "Cancel request",
        name: `Cancel request: ${item.name}`,
        run: () => change(`/api/borrowing/${item.id}/cancel/`, "POST"),
      },
    ];
  }

  return (
    <>
      <h2 ref={heading} tabIndex={-1}>
        Loans
      </h2>
      <FormErrors errors={errors} />
      {page.status === "loading" && <p>Loading…</p>}
      {page.status === "error" && <p role="alert">Could not load your loans.</p>}
      {page.status === "ok" && (
        <>
          <LoanSection
            id="waiting"
            title="Waiting for your approval"
            empty="Nothing is waiting."
            items={page.data.lending.filter((item) => item.loan_status === "requested")}
            describe={lendingText}
            actions={answers}
            onAct={act}
          />
          <LoanSection
            id="lent-out"
            title="Lent out"
            empty="Nothing is lent out."
            items={page.data.lending.filter((item) => item.loan_status === "on_loan")}
            describe={lendingText}
            actions={returning}
            onAct={act}
          />
          <LoanSection
            id="my-requests"
            title="My requests"
            empty="You have no pending requests."
            items={page.data.borrowed.filter((item) => item.loan_status === "requested")}
            describe={borrowedText}
            actions={cancelling}
            onAct={act}
          />
          <LoanSection
            id="using"
            title="Using"
            empty="You are not using anything."
            items={page.data.borrowed.filter(
              (item) => item.loan_status === "on_loan" && item.can_return,
            )}
            describe={usingText}
            actions={markingAvailable}
            onAct={act}
          />
          <LoanSection
            id="borrowed"
            title="Borrowed"
            empty="You are not borrowing anything."
            items={page.data.borrowed.filter(
              (item) => item.loan_status === "on_loan" && !item.can_return,
            )}
            describe={borrowedText}
            actions={() => []}
            onAct={act}
          />
        </>
      )}
    </>
  );
}

interface LoanSectionProps<T> {
  id: string;
  title: string;
  empty: string;
  items: T[];
  describe: (item: T) => string;
  actions: (item: T) => Action[];
  onAct: (button: HTMLButtonElement, action: Action) => void;
}

function LoanSection<T extends { id: number }>({
  id,
  title,
  empty,
  items,
  describe,
  actions,
  onAct,
}: LoanSectionProps<T>) {
  return (
    <section aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {items.length === 0 ? (
        <p>{empty}</p>
      ) : (
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <span>{describe(item)}</span>
              {actions(item).map((action) => (
                <span key={action.name}>
                  {" "}
                  <button
                    type="button"
                    aria-label={action.name}
                    onClick={(event) => onAct(event.currentTarget, action)}
                  >
                    {action.label}
                  </button>
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
