import type { User } from "./auth";
import { fullName, type PersonName } from "./inventories";
import { formatPhoneNumber } from "./phone";

export type LoanStatus = "available" | "requested" | "on_loan";

export const LOAN_STATUS_LABELS: Record<LoanStatus, string> = {
  available: "Available",
  requested: "Requested",
  on_loan: "On loan",
};

export interface InventoryRef {
  id: number;
  name: string;
}

/** An item as its owner sees it. */
export interface Item {
  id: number;
  name: string;
  description: string;
  /** The inventories it is listed in. */
  inventories: InventoryRef[];
  loan_status: LoanStatus;
  /** The requester or borrower. */
  borrower: User | null;
  /** The inventory the request was made through, or `null` once it is deleted. */
  loan_inventory: InventoryRef | null;
}

/** An item listed in an inventory, as one of the inventory's members sees it. */
export interface ListedItem {
  id: number;
  name: string;
  description: string;
  owner: PersonName;
  loan_status: LoanStatus;
  /** True when the signed-in user is the requester or the borrower. */
  borrowed_by_me: boolean;
  /** Set only for admins and owners, for a request or loan made through this inventory. */
  borrower: User | null;
}

/** An item the signed-in user has requested or borrowed. */
export interface BorrowedItem {
  id: number;
  name: string;
  description: string;
  loan_status: "requested" | "on_loan";
  owner: PersonName;
  loan_inventory: InventoryRef | null;
}

/** An item listed in the signed-in user's inventories that someone else owns. */
export interface DiscoverItem {
  id: number;
  name: string;
  description: string;
  owner: PersonName;
  loan_status: LoanStatus;
  /** True when the signed-in user is the requester or the borrower. */
  borrowed_by_me: boolean;
  /** The signed-in user's inventories it is listed in. */
  inventories: InventoryRef[];
}

/** A request or loan of someone else that the signed-in user may answer or close. */
export interface LendingItem extends Omit<Item, "loan_status" | "borrower"> {
  loan_status: "requested" | "on_loan";
  borrower: User;
  /** `null` when the item is the signed-in user's own. */
  owner: PersonName | null;
  /** True when the signed-in user may approve or decline the request. */
  can_answer: boolean;
}

/** The name, then the description when there is one. */
export function describeItem(item: { name: string; description: string }): string {
  return item.description ? `${item.name}: ${item.description}` : item.name;
}

/** "Requested by" or "On loan to", then `borrower` by name and phone number, or "you". */
export function borrowerText(loanStatus: LoanStatus, borrower: User | "you"): string {
  const who =
    borrower === "you"
      ? borrower
      : `${fullName(borrower)}, ${formatPhoneNumber(borrower.phone_number)}`;
  return loanStatus === "requested" ? `Requested by ${who}` : `On loan to ${who}`;
}
