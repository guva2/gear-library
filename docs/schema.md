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
| `user_id` | → `User` | `on_delete=models.CASCADE`. |
| `role` | `varchar(6)` | `member`, `admin` or `owner`. |
| `created_at` | `timestamptz` | |

- Unique on (`inventory_id`, `user_id`).
- Each role has the rights of the roles before it:
  - `member`: sees the inventory and its items, lists their own items in it, and requests
    to borrow its items.
  - `admin`: also approves and declines borrow requests made through the inventory, and
    marks those items returned.
  - `owner`: also invites users, removes members, sets any member's role, removes any item
    from the inventory, renames the inventory and deletes it.

### `InventoryInvite` (`gear_library_inventoryinvite`)

Built in M4.

| Column | Type | Rules |
|---|---|---|
| `inventory_id` | → `Inventory` | `on_delete=models.CASCADE`. |
| `invitee_id` | → `User` | `on_delete=models.CASCADE`. |
| `invited_by_id` | → `User` | Nullable. `on_delete=models.SET_NULL`. |
| `status` | `varchar(8)` | `pending`, `accepted` or `declined`. |
| `created_at` | `timestamptz` | |

- Partial unique index on (`inventory_id`, `invitee_id`) where `status = 'pending'`: at
  most one pending invite per inventory and invitee.

### `Item` (`gear_library_item`)

Built in M5. A piece of gear. A user owns it, and it can be listed in several inventories.
It is one physical object, so its loan state is on this row, not per inventory.

| Column | Type | Rules |
|---|---|---|
| `owner_id` | → `User` | `on_delete=models.CASCADE`. |
| `name` | `varchar(64)` | |
| `description` | `varchar(512)` | Optional. |
| `borrower_id` | → `User` | Nullable. `on_delete=models.PROTECT`. |
| `loan_inventory_id` | → `Inventory` | Nullable. `on_delete=models.PROTECT`. The inventory the borrow request was made through. |
| `loan_status` | `varchar(9)` | `available`, `requested` or `on_loan`. |
| `created_at` | `timestamptz` | |

- Check: `borrower_id` and `loan_inventory_id` are both null exactly when
  `loan_status = 'available'`.
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

- Creating an inventory makes the creator its owner.
- An inventory always has at least one owner. The last owner cannot leave, be removed, or
  take a lower role. They must make another member an owner or delete the inventory.
- Only owners invite. Invites go only to users who are not members. Accepting checks this
  again. The invitee joins with the `member` role.
- A user lists only their own items, and only in inventories they are a member of.
- An item leaves an inventory when its owner removes it, when an owner of the inventory
  removes it, or when the item's owner leaves or is removed from the inventory.
- Only members of an inventory see it and the items listed in it.
- A borrow request names the inventory it is made through. The requester must be a member
  of that inventory, the item must be listed in it, and the requester must not own the
  item.
- A borrow request is one conditional update: set the borrower and loan inventory only if
  the item is `available`. One requester at a time, across all of the item's inventories.
  Other requests are blocked until the request is declined or cancelled, or the item is
  returned.
- Admins and owners of the loan inventory approve, decline, or mark an item returned. The
  borrower cancels while the request is pending.
- A pending request is cancelled when the item leaves the loan inventory, when the
  requester leaves or is removed from it, or when the item is deleted.
- While an item is `on_loan`, its owner cannot delete it, and it cannot leave its loan
  inventory. So its owner cannot leave or be removed from that inventory, and the
  inventory cannot be deleted, until the item is returned. The borrower can leave; admins
  of the loan inventory still mark the item returned.
- Deleting an inventory deletes its memberships, invites and listings. The items stay with
  their owners.
