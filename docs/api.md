# API

A draft of the HTTP API. It lists paths, methods, who may call each endpoint and the main
error codes. Request and response fields are not here; each milestone adds them when it
builds its endpoints. The roles and rules behind "who may call" are in
[`schema.md`](schema.md).

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
| `POST` | `/api/auth/register/` | Not logged in. Creates a user. | `400`: invalid or duplicate phone number, weak password. `403`: logged in. |
| `POST` | `/api/auth/login/` | Anyone. | `400`: wrong phone number or password. |
| `POST` | `/api/auth/logout/` | Logged in. | `403` |
| `GET` | `/api/auth/me/` | Logged in. The current user. | `403` when anonymous. |

`register` and `login` check the CSRF token for anonymous callers too, so call
`/api/auth/csrf/` first. Both replace the `csrftoken` cookie: read it again before the
next unsafe request.

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
| `password` | string | Required. Must pass Django's password validators: at least 8 characters, not too common, not all digits, not too similar to the names. |

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
| `DELETE` | `/api/inventories/{id}/` | Owner. | `403`, `404` |

### Members and roles

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/inventories/{id}/members/` | Member. | `404` |
| `PATCH` | `/api/inventories/{id}/members/{user_id}/` | Owner. Sets the member's role. | `400`, `403`, `404`, `409`: would leave no owner. |
| `DELETE` | `/api/inventories/{id}/members/{user_id}/` | Owner, to remove a member. Any member, for their own `user_id`, to leave. | `403`, `404`, `409`: would leave no owner. |

### Invites

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/inventories/{id}/invites/` | Owner. The inventory's pending invites. | `403`, `404` |
| `POST` | `/api/inventories/{id}/invites/` | Owner. Invites a user by phone number. | `400`: no such user. `403`, `404`. `409`: already a member, or an invite is pending. |
| `POST` | `/api/invites/{id}/revoke/` | Owner of the invite's inventory. | `403`, `404`, `409`: not pending. |
| `GET` | `/api/invites/` | Logged in. The caller's pending invites. | |
| `POST` | `/api/invites/{id}/accept/` | The invitee. Joins as `member`. | `404`, `409`: not pending, or already a member. |
| `POST` | `/api/invites/{id}/decline/` | The invitee. | `404`, `409`: not pending. |

## Gear (M5)

### Items

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/items/` | Logged in. The caller's own items. | |
| `POST` | `/api/items/` | Logged in. The caller owns the new item. | `400` |
| `GET` | `/api/items/{id}/` | The item's owner, its borrower, or a member of an inventory it is listed in. | `404` |
| `PATCH` | `/api/items/{id}/` | The item's owner. | `400`. `403`: can see the item but does not own it. `404`. |
| `DELETE` | `/api/items/{id}/` | The item's owner. | `403`: can see the item but does not own it. `404`. `409`: on loan. |

### Listings

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/inventories/{id}/items/` | Member. The items listed in the inventory. | `404` |
| `POST` | `/api/inventories/{id}/items/` | Admin, for an item they own. | `400`, `403`, `404`, `409`: already listed. |
| `DELETE` | `/api/inventories/{id}/items/{item_id}/` | Admin, for an item they own. Owner, for any item. | `403`, `404` |

## Search (M6)

| Method | Path | Who | Main errors |
|---|---|---|---|
| `GET` | `/api/search/?q=` | Logged in. Items listed in the caller's inventories. | `400`: no query. |

## Borrowing (M7)

A request is made through one inventory. "Loan inventory" below is that inventory.
The approve, decline, cancel and return bodies carry what the caller saw, and the `409`
"the request changed" check compares it with the item. Which fields it compares, and the
owner's mark-returned exception, are in the Concurrency section of `schema.md`.

| Method | Path | Who | Main errors |
|---|---|---|---|
| `POST` | `/api/inventories/{id}/items/{item_id}/borrow/` | Member, for an item listed there that they do not own. | `403`, `404`, `409`: not available. |
| `GET` | `/api/inventories/{id}/requests/` | Admin. Pending requests made through the inventory. | `403`, `404` |
| `GET` | `/api/loans/` | Logged in. Items the caller has requested or borrowed. | |
| `POST` | `/api/items/{id}/approve/` | Admin of the loan inventory, other than the borrower. | `403`, `404`, `409`: the request changed. |
| `POST` | `/api/items/{id}/decline/` | Admin of the loan inventory. | `403`, `404`, `409`: the request changed. |
| `POST` | `/api/items/{id}/cancel/` | The borrower, while the request is pending. | `403`, `404`, `409`: not pending. |
| `POST` | `/api/items/{id}/return/` | Admin of the loan inventory while the item is listed there, or the item's owner. Never the borrower. | `403`, `404`, `409`: not on loan. |
