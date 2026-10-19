import type { PersonName } from "./inventories";

/** An accepted connection. `user` is the other user. */
export interface Connection {
  id: number;
  status: "accepted";
  user: PersonName & { id: number; phone_number: string };
}

/** A pending request the caller received. `user` is the requester, by name only. */
export interface ReceivedRequest {
  id: number;
  status: "pending";
  user: PersonName;
}

/** A pending request the caller sent. `user` is the other user, by phone number only. */
export interface SentRequest {
  id: number;
  status: "pending";
  user: { phone_number: string };
}

export interface ConnectionRequests {
  received: ReceivedRequest[];
  sent: SentRequest[];
}
