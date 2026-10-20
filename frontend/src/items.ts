import type { PersonName } from "./inventories";

/** An item as its owner sees it. */
export interface Item {
  id: number;
  name: string;
  description: string;
  /** The inventories it is listed in. */
  inventories: { id: number; name: string }[];
}

/** An item listed in an inventory, as the inventory's members see it. */
export interface ListedItem {
  id: number;
  name: string;
  description: string;
  owner: PersonName;
}

/** The name, then the description when there is one. */
export function describeItem(item: { name: string; description: string }): string {
  return item.description ? `${item.name}: ${item.description}` : item.name;
}
