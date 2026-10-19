import type { PersonName } from "./inventories";

/** An accepted connection. `user` is the other user. */
export interface Connection {
  id: number;
  status: "accepted";
  user: PersonName & { id: number; phone_number: string };
}

/** A pending request, sent or received. `user` is the other user, by name only. */
export interface ConnectionRequest {
  id: number;
  status: "pending";
  user: PersonName;
}

export interface ConnectionRequests {
  received: ConnectionRequest[];
  sent: ConnectionRequest[];
}
