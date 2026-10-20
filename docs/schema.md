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
  - `admin`: also sees every member with their phone number and role, invites their own
    accepted connections, sees and revokes any pending invite, lists their own items in
    the inventory and removes them, approves and declines borrow requests made through
    the inventory, and marks those items returned.
  - `owner`: also removes members, sets any member's role, removes any item from the
    inventory, renames the inventory and deletes it.

### `Connection` (`gear_library_connection`)

Built in M5. Two users who are connected, or a request from one of them to the other. One
row per pair of users.

| Column | Type | Rules |
|---|---|---|
| `first_user_id` | → `User` | `on_delete=models.PROTECT`. The user with the lower id. |
| `second_user_id` | → `User` | `on_delete=models.PROTECT`. The user with the higher id. |
| `requested_by_id` | → `User` | `on_delete=models.PROTECT`. The user who sent the request. |
| `status` | `varchar(8)` | `pending` or `accepted`. |
| `created_at` | `timestamptz` | |

- Check: `first_user_id < second_user_id`. A pair is stored in one order only, and a user
  cannot connect to themselves.
- Check: `requested_by_id` is `first_user_id` or `second_user_id`.
- Unique on (`first_user_id`, `second_user_id`): one row per pair, pending or accepted,
  whichever user sent the request.
- There is no history. Declining, cancelling and removing delete the row, and then either
  user can send a new request.

### `Item` (`gear_library_item`)

A piece of gear. A user owns it, and it can be listed in several inventories. It is one
physical object, so its loan state is on this row, not per inventory.

| Column | Type | Rules | Built in |
|---|---|---|---|
| `owner_id` | → `User` | `on_delete=models.PROTECT`. | M7 |
| `name` | `varchar(64)` | | M7 |
| `description` | `varchar(512)` | Optional. | M7 |
| `created_at` | `timestamptz` | | M7 |
| `borrower_id` | → `User` | Nullable. `on_delete=models.PROTECT`. The requester while `requested`, the borrower while `on_loan`. | M9 |
| `loan_inventory_id` | → `Inventory` | Nullable. `on_delete=models.SET_NULL`. The inventory the borrow request was made through. | M9 |
| `loan_status` | `varchar(9)` | `available`, `requested` or `on_loan`. | M9 |

The checks below arrive with the loan columns in M9.

- Check, one of:
  - `available`, with `borrower_id` and `loan_inventory_id` both null.
  - `requested`, with `borrower_id` and `loan_inventory_id` both set.
  - `on_loan`, with `borrower_id` set. `loan_inventory_id` may be null.
- Check: `borrower_id <> owner_id`.
- There is no loan history. The row holds only the current loan state.

### `InventoryItem` (`gear_library_inventoryitem`)

Built in M7. An item listed in an inventory.

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
  foreign keys make an ORM delete fail for a user who has memberships, connections or
  items, or who is the `invited_by` of a membership.

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
- Inviting checks that the invitee is an accepted connection of the sender, then inserts a
  pending membership. The unique index on (`inventory_id`, `user_id`) refuses it when the
  user is already a member or invited (`409`). Two invites to the same user at once: the
  second waits on the index until the first commits, then gets `409`.
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
- Connection changes take no explicit lock. Requesting inserts a pending row. When the
  unique index on the pair refuses it, the request accepts the other user's pending
  request with one conditional update (`status = 'pending'` and `requested_by_id` is the
  other user), and otherwise gets `409`. Two users who request each other at once: the
  second insert waits on the index until the first commits, then accepts it.
- Accepting a request is one conditional update where `status = 'pending'`. Declining and
  cancelling are each one conditional delete where `status = 'pending'`, and removing is
  one where `status = 'accepted'`. If no row matches, a row that is gone gets `404` and a
  row in the other status gets `409`, except that accepting a row that is already
  accepted returns it.
- Listing an item locks the inventory's row (`select_for_update`), then the item's row.
  Unlisting locks the inventory's row, deletes the listing, then cancels a pending request
  made through the inventory. Borrow requests, approvals, declines and mark returned
  through an inventory lock its row first, then check that the item is listed there.
- After locking, the operation re-reads and re-checks the rows it depends on, including the
  acting user's own membership and role.
- Requesting is one conditional update on the item where `loan_status = 'available'`.
  Approve, decline and mark returned through an inventory are each one conditional update
  that matches the `loan_status`, `borrower_id` and `loan_inventory_id` the acting user
  saw. If no row matches, the request or loan changed in the meantime and the action gets
  `409`.
- Cancelling and the item owner's mark returned take no inventory lock. Each is one
  conditional update on the item: cancelling matches `loan_status = 'requested'` and the
  caller as `borrower_id`, and the owner's mark returned matches `loan_status = 'on_loan'`
  and the `borrower_id` the owner saw. A pending request ends when its requester leaves
  the loan inventory or the item leaves it, so a cancel needs no membership or listing
  check. A cancel and an approval of the same request wait on the item row, and the second
  one gets `409`.
- The automatic cancels are conditional updates too: they match `loan_status = 'requested'`
  and the `loan_inventory_id` being left or removed. Each runs under that inventory's lock.
- Deleting an item reads the inventories it is listed in, locks them (`select_for_update`)
  in ascending `id` order, then locks the item row. It then re-reads the item's listings.
  A listing added in between is in an inventory it has not locked, and taking that lock
  after the item row would reverse the lock order, so the delete rolls back and starts
  again. An item `on_loan` gets `409`. Otherwise the delete removes the listings and the
  row. A listing that waits on the delete's item lock finds the item gone (`400` on
  `item_id`).

### Inventories and roles

- Creating an inventory makes the creator its owner.
- An inventory must keep at least one owner. The last owner cannot leave, be removed, or
  take a lower role. They must make another member an owner or delete the inventory.
- Admins and owners invite their own accepted connections and revoke any pending invite
  of the inventory. Only owners set roles and remove members. Owners set any member's
  role, including another owner's and their own.
- An invite is a pending membership. Invites go only to users who are not members, and a
  user has at most one pending invite per inventory. Accepting makes the membership
  active with the `member` role, and accepting again succeeds while the membership is
  active. Declining or revoking deletes the pending membership, after which the user can
  be invited again. A pending invite stays valid if its sender leaves or takes the
  `member` role.
- The connection is checked only when the invite is sent. Removing the connection later
  leaves the pending invite, or the membership it became, as it is.
- A pending membership gives no access. Its user is treated as a non-member of the
  inventory everywhere, is not counted as an owner, and appears only in the inventory's
  pending invites.
- Only the invited user and the inventory's active admins and owners see a pending
  membership through the invite actions. Anyone else gets `404`, whether the row is
  pending, active or gone.
- Only active members of an inventory see it and the items listed in it, with each item's
  name, description and its owner's first and last name. An item's owner always sees it.
  A borrower also sees the item they hold.
- A `member` sees only the first and last names of the inventory's admins and owners: not
  the other members, and no phone numbers. Admins and owners see every member with name,
  phone number and role. They see each pending invite of the inventory with the invitee's
  phone number only: the invitee's name and user id stay hidden until they join.
- An invitee sees their own pending invites, with the inventory's name and the inviter's
  name, without becoming a member.

### Connections

- A user sends a request by the other user's phone number, never to their own.
- A request to a user whose own request to you is pending accepts that request: the two
  are connected at once.
- The requester cancels a pending request, and the other user accepts or declines it.
  Either user removes an accepted connection.
- Only the two users of a connection see it. Anyone else gets `404`, whether it is
  pending, accepted or gone.
- Connected users see each other's id, first and last name, and phone number. A received
  pending request shows the requester's first and last name only. A sent pending request
  shows the other user's phone number only, so cancelling a request does not reveal a name.
- Accepting an accepted connection returns it, like accepting an invite.

### Listings

- Only admins and owners list items, and only their own items.
- An admin removes only their own items. An owner removes any item.
- A listing is removed when its item's owner leaves, is removed, or takes the `member`
  role in that inventory.
- Removing a listing does not end a loan. It cancels a pending request made through that
  inventory.

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
