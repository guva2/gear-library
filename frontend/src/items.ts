import type { User } from "./auth";
import type { PersonName } from "./inventories";

export type LoanStatus = "available" | "requested" | "on_loan";

export const LOAN_STATUS_LABELS: Record<LoanStatus, string> = {
  available: "Available",
  requested: "Requested",
  on_loan: "On loan",
};

interface InventoryRef {
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

/** The name, then the description when there is one. */
export function describeItem(item: { name: string; description: string }): string {
  return item.description ? `${item.name}: ${item.description}` : item.name;
}
