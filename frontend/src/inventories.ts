import { apiFetch } from "./api";

export type Role = "member" | "admin" | "owner";

export const ROLES: readonly Role[] = ["member", "admin", "owner"];

/** True when `role` is `needed` or a higher one. */
export function hasRole(role: Role, needed: Role): boolean {
  return ROLES.indexOf(role) >= ROLES.indexOf(needed);
}

export interface Inventory {
  id: number;
  name: string;
  /** The signed-in user's role. */
  role: Role;
}

export interface PersonName {
  first_name: string;
  last_name: string;
}

export interface Member extends PersonName {
  id: number;
  phone_number: string;
  role: Role;
}

export interface InventoryInvite {
  id: number;
  invitee: PersonName & { id: number; phone_number: string };
  invited_by: PersonName;
}

export interface MyInvite {
  id: number;
  inventory_name: string;
  invited_by: PersonName;
}

export function fullName(person: PersonName): string {
  return `${person.first_name} ${person.last_name}`;
}

export class HttpError extends Error {
  status: number;

  constructor(status: number) {
    super(`Request failed: ${status}`);
    this.status = status;
  }
}

/** GETs `path` and parses its JSON body. A non-2xx response throws an `HttpError`. */
export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await apiFetch(path, { signal });
  if (!response.ok) throw new HttpError(response.status);
  return (await response.json()) as T;
}
