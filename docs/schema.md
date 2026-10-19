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
| `invitee_id` | → `User` | `on_delete=models.CASCADE`. |
| `invited_by_id` | → `User` | Nullable. `on_delete=models.SET_NULL`. |
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
| `loan_listing_id` | → `InventoryItem` | Nullable. `on_delete=models.PROTECT`. The listing the borrow request was made through. Its inventory is the loan inventory. |
| `loan_status` | `varchar(9)` | `available`, `requested` or `on_loan`. |
| `created_at` | `timestamptz` | |

- Check: `borrower_id` and `loan_listing_id` are both null exactly when
  `loan_status = 'available'`.
- `loan_listing` must be a listing of this item. A check constraint cannot read another
  row, so the borrowing service enforces this.
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

- The app never deletes a user. A user is deactivated with `is_active`. The `PROTECT`
  foreign keys make an ORM delete of a user with memberships or items fail.

### Concurrency

- Every change to an inventory's memberships, invites, listings, or to the loan state of an
  item through one of its listings, first locks that inventory's row
  (`select_for_update`). The change then re-reads and re-checks the rows it depends on.
  This makes the last-owner rule and the borrow rules hold when two requests run at the
  same time.

### Inventories and roles

- Creating an inventory makes the creator its owner.
- An inventory always has at least one owner. The last owner cannot leave, be removed, or
  take a lower role. They must make another member an owner or delete the inventory.
- Only owners invite and revoke invites. Invites go only to users who are not members.
  Accepting checks this again. The invitee joins with the `member` role. A pending invite
  stays valid if its sender loses the owner role.
- Only members of an inventory see it and the items listed in it. A borrower also sees
  the item they hold, after they leave its loan inventory.

### Listings

- Only admins and owners list items, and only their own items.
- An admin removes only their own items. An owner removes any item.
- A listing is removed when its item's owner leaves, is removed, or takes the `member`
  role in that inventory.

### Borrowing

- A borrow request names the listing it is made through. The requester must be a member
  of its inventory and must not own the item.
- A borrow request is one conditional update: set the borrower and loan listing only if
  the item is `available`. One requester at a time, across all of the item's listings.
  Other requests are blocked until the request is declined or cancelled, or the item is
  returned.
- Admins and owners of the loan inventory approve, decline, or mark an item returned. An
  admin or owner cannot approve their own request. The borrower cancels while the request
  is pending.
- A pending request is cancelled when its listing is removed, when the requester leaves or
  is removed from the loan inventory, or when the item is deleted. The cancel runs first,
  in the same transaction, because `loan_listing` is `PROTECT`.
- While an item is `on_loan`, its loan listing cannot be removed and the item cannot be
  deleted. So until it is returned, its owner cannot leave the loan inventory, be removed
  from it, or take the `member` role in it, and the inventory cannot be deleted. The
  borrower can leave; admins of the loan inventory still mark the item returned.

### Deleting

- Deleting an inventory first cancels the pending requests made through its listings. It
  then deletes its memberships, invites and listings. The items stay with their owners.
