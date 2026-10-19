# Database schema

The relational design for the whole app.

## Conventions

- Each table notes the milestone that builds it. Where a table's columns arrive in
  different milestones, its "Built in" column names the milestone for each column.
- PostgreSQL. Tables are Django models.
- Every table has Django's `id` primary key (`bigint`) and `created_at`
  (`timestamptz`, set on insert).
- US phone numbers only.
- Text columns are `varchar(n)` with the length shown. Text columns are `NOT NULL`. An
  optional text column stores `''`, not `NULL`.
- Enumerated values are short lowercase strings. Each has a check constraint that limits
  it to the listed values, in addition to Django `choices`.
- Foreign keys are `NO ACTION DEFERRABLE INITIALLY DEFERRED` in the database. The
  `on_delete` behaviour shown for each foreign key runs only through Django ORM deletes,
  not raw SQL.
- Each format rule (phone number) is enforced twice: by a field validator, and by a
  database check constraint that holds when validation is bypassed.

## Tables

### `User` (`gear_library_user`)

Custom user model (`AUTH_USER_MODEL = "gear_library.User"`). The phone number is the login.
There is no username.

| Column | Type | Rules | Built in |
|---|---|---|---|
| `phone_number` | `varchar(10)` | Unique. Exactly 10 ASCII digits, check `^[0-9]{10}$`. Login field. | M1 |
| `password` | `varchar(128)` | Django password hash. | M1 |
| `last_login` | `timestamptz` | Nullable. | M1 |
| `is_active` | `boolean` | Default `true`. | M1 |
| `is_staff` | `boolean` | Default `false`. Admin site access. | M1 |
| `is_superuser` | `boolean` | Default `false`. | M1 |
| `created_at` | `timestamptz` | | M1 |
| `first_name` | `varchar(32)` | | M3 |
| `last_name` | `varchar(32)` | | M3 |

`groups` and `user_permissions` come from `PermissionsMixin`.

### `Inventory` (`gear_library_inventory`)

Built in M4. A group of users who share gear.

| Column | Type | Rules |
|---|---|---|
| `name` | `varchar(32)` | |
| `created_at` | `timestamptz` | |

### `Membership` (`gear_library_membership`)

Built in M4. One row per user in an inventory. A user can be a member of any number of
inventories.

| Column | Type | Rules |
|---|---|---|
| `inventory_id` | → `Inventory` | `on_delete=models.CASCADE`. |
| `user_id` | → `User` | `on_delete=models.PROTECT`. |
| `role` | `varchar(6)` | `member`, `admin` or `owner`. |
| `created_at` | `timestamptz` | |

- Unique on (`inventory_id`, `user_id`).
- Each role has the rights of the roles before it:
  - `member`: sees the inventory and its items, and requests to borrow its items.
  - `admin`: also lists their own items in the inventory and removes them, approves and
    declines borrow requests made through the inventory, and marks those items returned.
  - `owner`: also invites users, revokes invites, removes members, sets any member's role,
    removes any item from the inventory, renames the inventory and deletes it.

### `InventoryInvite` (`gear_library_inventoryinvite`)

Built in M4.

| Column | Type | Rules |
|---|---|---|
| `inventory_id` | → `Inventory` | `on_delete=models.CASCADE`. |
| `invitee_id` | → `User` | `on_delete=models.PROTECT`. |
| `invited_by_id` | → `User` | `on_delete=models.PROTECT`. |
| `status` | `varchar(8)` | `pending`, `accepted`, `declined` or `revoked`. |
| `created_at` | `timestamptz` | |

- Partial unique index on (`inventory_id`, `invitee_id`) where `status = 'pending'`: at
  most one pending invite per inventory and invitee.

### `Item` (`gear_library_item`)

Built in M5. A piece of gear. A user owns it, and it can be listed in several inventories.
It is one physical object, so its loan state is on this row, not per inventory.

| Column | Type | Rules |
|---|---|---|
| `owner_id` | → `User` | `on_delete=models.PROTECT`. |
| `name` | `varchar(64)` | |
| `description` | `varchar(512)` | Optional. |
| `borrower_id` | → `User` | Nullable. `on_delete=models.PROTECT`. The requester while `requested`, the borrower while `on_loan`. |
| `loan_inventory_id` | → `Inventory` | Nullable. `on_delete=models.SET_NULL`. The inventory the borrow request was made through. |
| `loan_status` | `varchar(9)` | `available`, `requested` or `on_loan`. |
| `created_at` | `timestamptz` | |

- Check, one of:
  - `available`, with `borrower_id` and `loan_inventory_id` both null.
  - `requested`, with `borrower_id` and `loan_inventory_id` both set.
  - `on_loan`, with `borrower_id` set. `loan_inventory_id` is null once that inventory is
    deleted.
- Check: `borrower_id <> owner_id`.
- There is no loan history. The row holds only the current loan state.

### `InventoryItem` (`gear_library_inventoryitem`)

Built in M5. An item listed in an inventory.

| Column | Type | Rules |
|---|---|---|
| `inventory_id` | → `Inventory` | `on_delete=models.CASCADE`. |
| `item_id` | → `Item` | `on_delete=models.CASCADE`. |
| `created_at` | `timestamptz` | |

- Unique on (`inventory_id`, `item_id`).

## Rules the app enforces

These rules span tables, so the database cannot check them alone.

### Users

- The app never deletes or deactivates a user. `is_active` stays `true`. The `PROTECT`
  foreign keys make an ORM delete of a user with memberships, invites or items fail.

### Concurrency

- Every change to an inventory's memberships, invites or listings, and every borrow
  request through it, first locks that inventory's row (`select_for_update`). An operation
  that touches several inventories, such as deleting an item listed in several, locks them
  in ascending `id` order.
- After locking, the operation re-reads and re-checks the rows it depends on, including the
  acting user's own membership and role.
- Approve, decline, cancel and mark returned are each one conditional update on the item.
  It matches the `loan_status`, `borrower_id` and `loan_inventory_id` the acting user saw.
  If no row matches, the request changed in the meantime and the action is rejected.

### Inventories and roles

- Creating an inventory makes the creator its owner.
- An inventory always has at least one owner. The last owner cannot leave, be removed, or
  take a lower role. They must make another member an owner or delete the inventory.
- Only owners invite and revoke invites. Invites go only to users who are not members.
  Accepting checks this again. The invitee joins with the `member` role. A pending invite
  stays valid if its sender loses the owner role.
- Only members of an inventory see it and the items listed in it. An item's owner always
  sees it. A borrower also sees the item they hold.

### Listings

- Only admins and owners list items, and only their own items.
- An admin removes only their own items. An owner removes any item.
- A listing is removed when its item's owner leaves, is removed, or takes the `member`
  role in that inventory.
- Removing a listing does not change a loan. The borrower and loan status are on the item.

### Borrowing

- A borrow request names the inventory it is made through. The requester must be a member
  of it, the item must be listed in it, and the requester must not own the item.
- A borrow request is one conditional update: set the borrower and loan inventory only if
  the item is `available`. One requester at a time, across all of the item's listings.
  Other requests are blocked until the request is declined or cancelled, or the item is
  returned.
- Admins and owners of the loan inventory approve and decline requests. The borrower
  cancels while the request is pending.
- Admins and owners of the loan inventory mark an item returned. The item's owner can
  always mark it returned, so a loan stays closable after its listing or loan inventory is
  gone.
- The borrower cannot approve their own request or mark their own loan returned.
- A pending request is cancelled when the item leaves the loan inventory, when the
  requester leaves or is removed from it, or when the item is deleted.
- An item cannot be deleted while it is `on_loan`.

### Deleting

- Deleting an inventory deletes its memberships, invites and listings. The items stay with
  their owners. Pending requests through it are cancelled first, in the same transaction;
  items on loan through it keep their borrower, and their `loan_inventory_id` becomes null.
