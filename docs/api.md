# API

A draft of the HTTP API. It lists paths, methods, who may call each endpoint and the main
error codes. Request and response fields are filled in for the milestones that have been
built; each later milestone adds them when it builds its endpoints. The roles and rules
behind "who may call" are in [`schema.md`](schema.md).

## Conventions

- Every path starts with `/api/` and ends with `/`. Bodies are JSON.
- Authentication is a Django session cookie. Unsafe methods (`POST`, `PATCH`, `DELETE`)
  need the CSRF token from the `csrftoken` cookie in the `X-CSRFToken` header.
- "Logged in" means any authenticated user. "Member", "admin" and "owner" mean a role in
  the inventory named by the path, or an equal or higher one.
- Common errors:
  - `400`: the request body is invalid.
  - `403`: not logged in, or logged in without the role the endpoint needs. Session
    authentication sends no `WWW-Authenticate` challenge, so an anonymous caller gets
    `403`, not `401`.
  - `404`: the object does not exist, or the caller may not see it. An inventory is
    `404` to anyone who is not a member, so its existence is not disclosed.
  - `409`: the object is in a state that does not allow the action, for example an item
    that is already requested, or a request that changed after the caller saw it.

## Health (M2)

| Method | Path | Who | Result |
|---|---|---|---|
| `GET` | `/api/health/` | Anyone | `200` `{"status": "ok", "database": "ok"}`. `503` `{"status": "error", "database": "unavailable"}` when the database query fails. |

## Users and sessions (M3)

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/auth/csrf/` | Anyone. Sets the `csrftoken` cookie. | |
| `POST` | `/api/auth/register/` | Not logged in. Creates a user. | `400`: invalid or duplicate phone number, weak password (a duplicate number and a weak password are reported together). `403`: logged in. |
| `POST` | `/api/auth/login/` | Anyone. | `400`: wrong phone number or password. |
| `POST` | `/api/auth/logout/` | Logged in. | `403` |
| `GET` | `/api/auth/me/` | Logged in. The current user. | `403` when anonymous. |

`register` and `login` check the CSRF token for anonymous callers too, so call
`/api/auth/csrf/` first. A successful `register` or `login` replaces the `csrftoken`
cookie: read it again before the next unsafe request.

### Phone numbers

Requests may format a phone number with spaces, dots, dashes and parentheses, and may
start it with `1` or `+1`: `(555) 123-4567`, `+1 555-123-4567` and `5551234567` are the
same number. Responses always carry 10 digits. Any other value is a `400` on
`phone_number`.

### User

The body of `register`, `login` and `me` responses.

| Field | Type | |
|---|---|---|
| `id` | integer | |
| `phone_number` | string | 10 digits. |
| `first_name` | string | 1 to 32 characters. |
| `last_name` | string | 1 to 32 characters. |

### `GET /api/auth/csrf/`

`204` with no body. The `csrftoken` cookie is in the response.

### `POST /api/auth/register/`

| Field | Type | |
|---|---|---|
| `phone_number` | string | Required. See [Phone numbers](#phone-numbers). |
| `first_name` | string | Required. 1 to 32 characters after trimming spaces. |
| `last_name` | string | Required. 1 to 32 characters after trimming spaces. |
| `password` | string | Required. Must pass Django's password validators: at least 8 characters, not too common, not all digits, not too similar to the phone number or the names. |

`201` with the new [User](#user). The caller is logged in.

`400` errors are keyed by field, each a list of messages:

```json
{"phone_number": ["A user with this phone number already exists."]}
```

```json
{"password": ["This password is too short. It must contain at least 8 characters."]}
```

`403` `{"detail": "You are already logged in."}` for a logged-in caller.

### `POST /api/auth/login/`

| Field | Type | |
|---|---|---|
| `phone_number` | string | Required. See [Phone numbers](#phone-numbers). |
| `password` | string | Required. |

`200` with the [User](#user). The caller is logged in.

`400` for a wrong phone number, a wrong password or an inactive user, with one message:

```json
{"non_field_errors": ["Wrong phone number or password."]}
```

A missing field, or a `phone_number` that is not a phone number, is a `400` keyed by that
field instead.

### `POST /api/auth/logout/`

No body. `204` with no body. The session ends.

### `GET /api/auth/me/`

`200` with the [User](#user).

## Inventories (M4)

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/inventories/` | Logged in. The caller's inventories. | |
| `POST` | `/api/inventories/` | Logged in. The caller becomes its owner. | `400` |
| `GET` | `/api/inventories/{id}/` | Member. | `404` |
| `PATCH` | `/api/inventories/{id}/` | Owner. Renames it. | `400`, `403`, `404` |
| `DELETE` | `/api/inventories/{id}/` | Owner. Deletes it with its memberships and invites. | `403`, `404` |

Every endpoint under `/api/inventories/{id}/` checks the caller's membership and role
before it reads the body: a non-member gets `404` and a member without the role gets
`403`, whatever the body holds.

### Inventory

The body of the inventory responses.

| Field | Type | |
|---|---|---|
| `id` | integer | |
| `name` | string | 1 to 32 characters. |
| `role` | string | The caller's role: `member`, `admin` or `owner`. |

`GET /api/inventories/` returns a list of [Inventory](#inventory), sorted by name.

### `POST /api/inventories/` and `PATCH /api/inventories/{id}/`

| Field | Type | |
|---|---|---|
| `name` | string | Required. 1 to 32 characters after trimming spaces. |

`POST` returns `201` with the new [Inventory](#inventory), whose `role` is `owner`. `PATCH`
returns `200` with the renamed [Inventory](#inventory). `400` errors are keyed by `name`.

`DELETE` returns `204` with no body.

### Members and roles

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/inventories/{id}/members/` | Member. What the caller sees depends on their role. | `404` |
| `PATCH` | `/api/inventories/{id}/members/{user_id}/` | Owner. Sets the member's role. | `400`, `403`, `404`, `409`: would leave no owner. |
| `DELETE` | `/api/inventories/{id}/members/{user_id}/` | Owner, to remove a member. Any member, for their own `user_id`, to leave. | `403`, `404`, `409`: would leave no owner. |

`GET` returns a list sorted by last name, then first name. An admin or owner gets every
member as a [Member](#member). A `member` gets only the admins and owners, each with
`first_name` and `last_name` and nothing else.

#### Member

| Field | Type | |
|---|---|---|
| `id` | integer | The user's id. |
| `first_name` | string | |
| `last_name` | string | |
| `phone_number` | string | 10 digits. |
| `role` | string | `member`, `admin` or `owner`. |

#### `PATCH /api/inventories/{id}/members/{user_id}/`

| Field | Type | |
|---|---|---|
| `role` | string | Required. `member`, `admin` or `owner`. |

`200` with the [Member](#member). `404` when `user_id` is not a member. `409`
`{"detail": "An inventory must keep at least one owner."}` when the last owner would take
a lower role.

`DELETE` returns `204` with no body. The last owner cannot leave or be removed (`409`).

### Invites

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/inventories/{id}/invites/` | Admin. The inventory's pending invites. | `403`, `404` |
| `POST` | `/api/inventories/{id}/invites/` | Admin. Invites one of the caller's accepted connections. | `400`: not one of the caller's connections. `403`, `404`. `409`: already a member, or an invite is pending. |
| `POST` | `/api/invites/{id}/revoke/` | Admin of the invite's inventory. Any pending invite. | `403`. `404`: no such invite. `409`: not a pending invite. |
| `GET` | `/api/invites/` | Logged in. The caller's pending invites. | |
| `POST` | `/api/invites/{id}/accept/` | The invitee. Joins as `member`. | `403`. `404`: no such invite. |
| `POST` | `/api/invites/{id}/decline/` | The invitee. | `403`. `404`: no such invite. `409`: not a pending invite. |

An invite is a pending membership, and an invite `id` is that membership's id. Accepting
makes it an active membership with the same id. Declining and revoking delete it, so its
id is then unknown (`404`).

Under `/api/invites/{id}/`, an invite is visible only to its invitee and to the admins and
owners of its inventory. Anyone else, including a `member` of the inventory and another
invitee, gets `404`, whether the invite is pending, accepted or gone. A caller who sees
the invite but may not take the action gets `403`: an admin who accepts or declines, or an
invitee who revokes.

A user with a pending invite is not a member: every `/api/inventories/{id}/` path of that
inventory returns `404` for them, and the inventory is not in their `GET /api/inventories/`.

#### Inventory invite

What `GET` and `POST /api/inventories/{id}/invites/` return. `GET` returns a list, oldest
first.

| Field | Type | |
|---|---|---|
| `id` | integer | |
| `invitee` | object | Only `phone_number` (10 digits). The name and user id appear in the members list once the invitee has joined. |
| `invited_by` | object | `first_name` and `last_name`. |

#### `POST /api/inventories/{id}/invites/`

| Field | Type | |
|---|---|---|
| `user_id` | integer | Required. The `id` of one of the caller's accepted connections, as in [Connection](#connection). |

The access check comes before the body: a non-member gets `404` and a `member` gets `403`
whatever they send.

`201` with the new [Inventory invite](#inventory-invite). `400` errors are keyed by
`user_id`. Any id that is not one of the caller's accepted connections gets one message,
whether no such user exists, the two are not connected, only a request is pending, or the
id is the caller's own:

```json
{"user_id": ["You can invite only your connections."]}
```

A missing or non-integer `user_id` gets the usual field error, such as
`{"user_id": ["This field is required."]}`.

`409` `{"detail": "This user is already a member or has a pending invite."}` when the
connection is a member or already invited. After a decline or revoke the same user can be
invited again. The connection is checked only when the invite is sent: removing it later
leaves the invite and the membership as they are.

#### My invite

What `GET /api/invites/` returns, as a list, oldest first. The invitee is not a member yet,
so it carries only the inventory's name.

| Field | Type | |
|---|---|---|
| `id` | integer | |
| `inventory_name` | string | |
| `invited_by` | object | `first_name` and `last_name`. |

#### Answering an invite

The three `POST /api/invites/{id}/` actions take no body. `accept` returns `200` with the
[Inventory](#inventory) just joined, whose `role` is `member`. Accepting is idempotent:
accepting an accepted invite again returns `200` with the inventory and the member's
current role. `decline` and `revoke` return `204` with no body. Declining or revoking an
accepted invite is a `409` `{"detail": "This is not a pending invite."}`. An invite
that was declined or revoked, or whose member has left, is a `404`
`{"detail": "Invite not found."}`.

## Connections (M5)

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/connections/` | Logged in. The caller's accepted connections. | |
| `GET` | `/api/connections/requests/` | Logged in. The caller's pending requests, received and sent. | |
| `POST` | `/api/connections/` | Logged in. Sends a request by phone number, or accepts the other user's pending request. | `400`: invalid number, no such user, or the caller's own number. `409`: already connected, or the caller's request is pending. |
| `POST` | `/api/connections/{id}/accept/` | The user who received the request. | `403`. `404`: no such connection. |
| `POST` | `/api/connections/{id}/decline/` | The user who received the request. | `403`. `404`: no such connection. `409`: not a pending request. |
| `POST` | `/api/connections/{id}/cancel/` | The user who sent the request. | `403`. `404`: no such connection. `409`: not a pending request. |
| `DELETE` | `/api/connections/{id}/` | Either user of an accepted connection. | `404`: no such connection. `409`: a pending request. |

A request and the connection it becomes are one row with one `id`. Declining, cancelling
and removing delete it, so its id is then unknown (`404`).

Under `/api/connections/{id}/`, a connection is visible only to its two users. Anyone else
gets `404`, whether it is pending, accepted or gone. One of the two who may not take the
action gets `403`, whatever the status: the requester who accepts or declines, or the
other user who cancels.

### Connection

An accepted connection. `GET /api/connections/` returns a list sorted by the other user's
last name, then first name.

| Field | Type | |
|---|---|---|
| `id` | integer | |
| `status` | string | `accepted`. |
| `user` | object | The other user: `id`, `first_name`, `last_name` and `phone_number` (10 digits). |

### Request

A pending request. A received request shows who sent it, and a sent request shows only the
number it went to, until it is accepted.

| Field | Type | |
|---|---|---|
| `id` | integer | |
| `status` | string | `pending`. |
| `user` | object | The other user. Received: `first_name` and `last_name` only. Sent: `phone_number` (10 digits) only, with no name and no `id`. |

`GET /api/connections/requests/` returns both lists, each oldest first:

```json
{"received": [{"id": 4, "status": "pending", "user": {"first_name": "Sam", "last_name": "Okafor"}}], "sent": [{"id": 5, "status": "pending", "user": {"phone_number": "5551230004"}}]}
```

### `POST /api/connections/`

| Field | Type | |
|---|---|---|
| `phone_number` | string | Required. See [Phone numbers](#phone-numbers). |

`201` with the new [Request](#request), a sent one: its `user` is the phone number only,
so sending and cancelling a request does not reveal whose number it is. `200` with the [Connection](#connection) when the
other user's request to the caller was pending: sending accepts it.

`400` errors are keyed by `phone_number`:

```json
{"phone_number": ["No user has this phone number."]}
```

```json
{"phone_number": ["You cannot send a request to yourself."]}
```

`409` with one of:

- `{"detail": "You are already connected."}`
- `{"detail": "You have already sent this user a request."}`
- `{"detail": "This connection changed. Try again."}` when the other user's request was
  cancelled or declined while this one was sent.

### Answering and removing

The three `POST /api/connections/{id}/` actions take no body. `accept` returns `200` with
the [Connection](#connection). `decline`, `cancel` and `DELETE` return `204` with no body.

Accepting an accepted connection is a `200` with the [Connection](#connection), the same
as a first accept. The user who sent a request cannot accept it (`403`). Declining or
cancelling an accepted connection is a `409`
`{"detail": "This is not a pending request."}`. Removing a pending request is a `409`
`{"detail": "You are not connected."}`. A connection that is gone is a `404`
`{"detail": "Connection not found."}`.

## Gear (M7)

### Items

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/items/` | Logged in. The caller's own items. | |
| `POST` | `/api/items/` | Logged in. The caller owns the new item. | `400` |
| `PATCH` | `/api/items/{id}/` | The item's owner. | `400`, `404` |
| `DELETE` | `/api/items/{id}/` | The item's owner. Deletes it and its listings. | `404`. `409`: on loan. |

Under `/api/items/{id}/`, an item that does not exist and an item the caller does not own
are both `404` `{"detail": "Item not found."}`, even for a member who sees the item in an
inventory. `PATCH` checks this before it reads the body.

#### Item

What the `/api/items/` endpoints return. `GET` returns a list sorted by name.

| Field | Type | |
|---|---|---|
| `id` | integer | |
| `name` | string | 1 to 64 characters. |
| `description` | string | 0 to 512 characters. `""` when there is none. |
| `inventories` | list | The inventories the item is listed in, sorted by name. Each has `id` and `name`. |
| `loan_status` | string | `available`, `requested` or `on_loan`. |
| `borrower` | object or `null` | The requester while `requested`, the borrower while `on_loan`: `id`, `first_name`, `last_name` and `phone_number`. `null` while `available`. |
| `loan_inventory` | object or `null` | The inventory the request was made through: `id` and `name`. `null` while `available`, and for a loan whose inventory was deleted. |

#### `POST /api/items/` and `PATCH /api/items/{id}/`

| Field | Type | |
|---|---|---|
| `name` | string | Required for `POST`. 1 to 64 characters after trimming spaces. |
| `description` | string | Optional. 0 to 512 characters after trimming spaces. |

`PATCH` changes only the fields it is sent. `POST` returns `201` with the new
[Item](#item), and `PATCH` returns `200` with the changed [Item](#item). `400` errors are
keyed by field.

`DELETE` returns `204` with no body. An item on loan is a `409`
`{"detail": "This item is on loan. It can be deleted once it is returned."}`. Deleting a
requested item cancels the request.

### Listings

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/inventories/{id}/items/` | Member. The items listed in the inventory. | `404` |
| `POST` | `/api/inventories/{id}/items/` | Admin, for an item they own. | `400`, `403`, `404`, `409`: already listed. |
| `DELETE` | `/api/inventories/{id}/items/{item_id}/` | Admin, for an item they own. Owner, for any item. | `403`, `404` |

A listing ends when its item's owner leaves the inventory, is removed from it, or takes
the `member` role there.

#### Listed item

What `GET` and `POST /api/inventories/{id}/items/` return. `GET` returns a list sorted by
name.

| Field | Type | |
|---|---|---|
| `id` | integer | The item's id. |
| `name` | string | |
| `description` | string | `""` when there is none. |
| `owner` | object | The item's owner: `first_name` and `last_name` only, so a `member` learns no user id. The owner is always an admin or owner of the inventory. |
| `loan_status` | string | `available`, `requested` or `on_loan`, whichever inventory the request was made through. |
| `borrowed_by_me` | boolean | `true` when the caller is the requester or the borrower. |
| `borrower` | object or `null` | For admins and owners, while the item is requested or on loan through this inventory: the requester or borrower's `id`, `first_name`, `last_name` and `phone_number`. `null` otherwise, and always `null` for a `member`. |

#### `POST /api/inventories/{id}/items/`

| Field | Type | |
|---|---|---|
| `item_id` | integer | Required. The `id` of one of the caller's items. |

The access check comes before the body: a non-member gets `404` and a `member` gets `403`
whatever they send.

`201` with the new [Listed item](#listed-item). `400` errors are keyed by `item_id`. Any id
that is not one of the caller's items gets one message, whether no such item exists or
someone else owns it:

```json
{"item_id": ["You can list only your own items."]}
```

A missing or non-integer `item_id` gets the usual field error.

`409` `{"detail": "This item is already listed in this inventory."}`.

#### `DELETE /api/inventories/{id}/items/{item_id}/`

`204` with no body. The item stays with its owner. An admin removing someone else's item
gets `403` `{"detail": "Only owners can remove other people's items."}`. An item that is
not listed in the inventory is a `404`
`{"detail": "This item is not listed in this inventory."}`.

## Search (M8)

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/search/?q=` | Logged in. Items listed in the caller's inventories. | `400`: no query. |

## Borrowing (M9)

A borrow request is made through one inventory, the item's loan inventory. One user at a
time can request an item, across all the inventories it is listed in. The rules are in
[`schema.md`](schema.md) under "Borrowing".

| Method | Path | Who | Main errors |
|---|---|---|---|
| `POST` | `/api/inventories/{id}/items/{item_id}/borrow/` | Member, for an item listed there that they do not own. | `403`: own item. `404`. `409`: not available. |
| `POST` | `/api/inventories/{id}/items/{item_id}/approve/` | Admin, for a request made through this inventory by someone else. | `400`, `403`, `404`, `409`: the request changed. |
| `POST` | `/api/inventories/{id}/items/{item_id}/decline/` | Admin, for a request made through this inventory by someone else. | `400`, `403`, `404`, `409`: the request changed. |
| `POST` | `/api/inventories/{id}/items/{item_id}/return/` | Admin, for a loan made through this inventory to someone else, while the item is listed there. | `400`, `403`, `404`, `409`: the loan changed. |
| `POST` | `/api/items/{id}/return/` | The item's owner. | `400`, `404`, `409`: the loan changed. |
| `GET` | `/api/borrowing/` | Logged in. Items the caller has requested or borrowed. | |
| `POST` | `/api/borrowing/{item_id}/cancel/` | The requester, while the request is pending. | `404`, `409`: already approved. |

Every action returns `204` with no body. The item's [Listed item](#listed-item) and
[Item](#item) show the new state.

### Requesting

`POST /api/inventories/{id}/items/{item_id}/borrow/` takes no body. The caller becomes the
requester and the inventory the loan inventory.

- `403` `{"detail": "You cannot borrow your own item."}`.
- `404` `{"detail": "This item is not listed in this inventory."}`.
- `409` `{"detail": "This item has already been requested or is on loan."}`, whichever
  inventory the earlier request was made through.

### Approving, declining and marking returned

`approve`, `decline` and `return` under `/api/inventories/{id}/items/{item_id}/`, and
`POST /api/items/{id}/return/`, take the requester or borrower the caller saw:

| Field | Type | |
|---|---|---|
| `borrower_id` | integer | Required. The `borrower.id` of the [Listed item](#listed-item) or [Item](#item). |

`approve` makes a request a loan. `decline` and `return` make the item available. Under
`/api/inventories/{id}/`, the access check comes before the body: a non-member gets `404`
and a `member` gets `403` whatever they send. Under `/api/items/{id}/`, an item the caller
does not own is a `404` `{"detail": "Item not found."}` before the body is read.

- `400` `{"borrower_id": ["This field is required."]}`, or another field error.
- `403` `{"detail": "You cannot approve or decline your own request."}` or
  `{"detail": "You cannot mark your own loan returned."}` when `borrower_id` is the caller.
- `404` `{"detail": "This item is not listed in this inventory."}`. The item's owner can
  still mark it returned through `/api/items/{id}/return/`.
- `409` `{"detail": "This request or loan changed. Try again."}` when the item is not
  requested (`approve`, `decline`) or on loan (`return`) by `borrower_id` through this
  inventory. Through `/api/items/{id}/return/`, the inventory does not need to match.

### Borrowed item

What `GET /api/borrowing/` returns, as a list sorted by name: the caller's pending
requests and the items they hold. A loan stays in the list after the borrower leaves the
inventory and after the inventory is deleted.

| Field | Type | |
|---|---|---|
| `id` | integer | The item's id. |
| `name` | string | |
| `description` | string | `""` when there is none. |
| `loan_status` | string | `requested` or `on_loan`. |
| `owner` | object | `first_name` and `last_name` only. |
| `loan_inventory` | object or `null` | `id` and `name`. `null` when the inventory was deleted. |

### `POST /api/borrowing/{item_id}/cancel/`

No body. Cancels the caller's pending request.

- `404` `{"detail": "Request not found."}` when the caller has not requested or borrowed
  the item.
- `409` `{"detail": "This request was approved, so it cannot be cancelled."}`.
