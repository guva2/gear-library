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
inventories. A `pending` row is an invite: the user has been invited and has not
accepted. Only an `active` row makes the user a member.

| Column | Type | Rules |
|---|---|---|
| `inventory_id` | → `Inventory` | `on_delete=models.CASCADE`. |
| `user_id` | → `User` | `on_delete=models.PROTECT`. |
| `role` | `varchar(6)` | `member`, `admin` or `owner`. |
| `status` | `varchar(7)` | `pending` or `active`. |
| `invited_by_id` | → `User` | Nullable. `on_delete=models.PROTECT`. The user who sent the invite. Null for the membership that created the inventory. |
| `created_at` | `timestamptz` | |

- Unique on (`inventory_id`, `user_id`): one row per user and inventory, pending or
  active. It refuses an invite to a member and a second invite to the same user.
- Check: `status = 'pending'` implies `role = 'member'`.
- Each role has the rights of the roles before it:
  - `member`: sees the inventory and its items, sees the names of its admins and owners,
    and requests to borrow its items.
  - `admin`: also sees every member with their phone number and role, invites users, sees
    and revokes any pending invite, lists their own items in the inventory and removes
    them, approves and declines borrow requests made through the inventory, and marks
    those items returned.
  - `owner`: also removes members, sets any member's role, removes any item from the
    inventory, renames the inventory and deletes it.

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
  - `on_loan`, with `borrower_id` set. `loan_inventory_id` may be null.
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
  foreign keys make an ORM delete fail for a user who has memberships or items, or who
  is the `invited_by` of a membership.

### Concurrency

- Setting a role, removing a member and leaving lock the inventory's row
  (`select_for_update`), then re-read the acting user's membership and role, the target
  membership and the active owners. Two of these changes to one inventory run one at a
  time, so the inventory always keeps an owner.
- Deleting an inventory locks its row (`select_for_update`), then deletes its memberships
  and the row. Every operation that locks the inventory row does so before it touches a
  membership row, so a delete and a role change, removal or leave on the same inventory
  run one at a time.
- Renaming an inventory, inviting, accepting, declining and revoking take no inventory
  lock and no explicit lock.
- Inviting inserts a pending membership. The unique index on (`inventory_id`, `user_id`)
  refuses it when the user is already a member or invited (`409`). Two invites to the same
  user at once: the second waits on the index until the first commits, then gets `409`.
- Accepting is one conditional update: `SET status = 'active'` where the row is the
  caller's and `status = 'pending'`. If the row is already active, accepting returns it
  (`200`). If the row is gone, accepting gets `404`.
- Declining and revoking are each one conditional delete of the row where
  `status = 'pending'`. If the row is gone, the action gets `404`. If it is active, it was
  accepted in the meantime and the action gets `409`.
- An accept and a delete of the same inventory wait on the membership row, so they run one
  at a time. A delete after the accept deletes the new member. An accept after the delete
  gets `404`.
- The foreign key from memberships to the inventory is checked at commit. An invite whose
  inventory was deleted first gets `404`. An invite that commits while a delete holds the
  inventory lock waits for the delete, then gets `404`. A delete that starts after an
  invite commits deletes the new pending membership with the inventory.
- These operations first lock the inventory's row (`select_for_update`): every change to
  its listings, and every borrow request, approve, decline, cancel or mark returned
  through it. An operation that touches several inventories, such as deleting an item
  listed in several, locks them in ascending `id` order. Inventory rows are locked before
  item rows.
- After locking, the operation re-reads and re-checks the rows it depends on, including the
  acting user's own membership and role.
- Approve, decline, cancel and mark returned are each one conditional update on the item.
  It matches the `loan_status`, `borrower_id` and `loan_inventory_id` the acting user saw.
  The item owner's mark returned matches only `loan_status` and `borrower_id`. If no row
  matches, the request changed in the meantime and the action is rejected.
- The automatic cancels are conditional updates too: they match `loan_status = 'requested'`
  and the `loan_inventory_id` being left or removed.
- Deleting an item locks its inventories, then the item row, then re-checks `loan_status`.

### Inventories and roles

- Creating an inventory makes the creator its owner.
- An inventory must keep at least one owner. The last owner cannot leave, be removed, or
  take a lower role. They must make another member an owner or delete the inventory.
- Admins and owners invite users and revoke any pending invite of the inventory. Only
  owners set roles and remove members. Owners set any member's role, including another
  owner's and their own.
- An invite is a pending membership. Invites go only to users who are not members, and a
  user has at most one pending invite per inventory. Accepting makes the membership
  active with the `member` role, and accepting again succeeds while the membership is
  active. Declining or revoking deletes the pending membership, after which the user can
  be invited again. A pending invite stays valid if its sender leaves or takes the
  `member` role.
- A pending membership gives no access. Its user is treated as a non-member of the
  inventory everywhere, is not counted as an owner, and appears only in the inventory's
  pending invites.
- Only the invited user and the inventory's active admins and owners see a pending
  membership through the invite actions. Anyone else gets `404`, whether the row is
  pending, active or gone.
- Only active members of an inventory see it and the items listed in it. An item's owner always
  sees it. A borrower also sees the item they hold.
- A `member` sees only the first and last names of the inventory's admins and owners: not
  the other members, and no phone numbers. Admins and owners see every member with name,
  phone number and role. They see each pending invite of the inventory with the invitee's
  phone number only: the invitee's name and user id stay hidden until they join.
- An invitee sees their own pending invites, with the inventory's name and the inviter's
  name, without becoming a member.

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
- Admins and owners of the loan inventory mark an item returned while the item is listed
  there. The item's owner can always mark it returned, so a loan stays closable after its
  listing or loan inventory is gone.
- The borrower cannot approve their own request or mark their own loan returned.
- A pending request is cancelled when the item leaves the loan inventory, when the
  requester leaves or is removed from it, or when the item is deleted.
- An item cannot be deleted while it is `on_loan`.

### Deleting

- Deleting an inventory deletes its memberships, pending ones included, and its listings.
  It locks the inventory first, then deletes its memberships. The items stay with their
  owners. Pending requests through it are cancelled first, in the same transaction; items
  on loan through it keep their borrower, and their `loan_inventory_id` becomes null.
