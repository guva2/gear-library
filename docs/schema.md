# Database schema

The relational design for the whole app.

## Conventions

- Each table notes the milestone that builds it. Where a table's columns arrive in
  different milestones, its "Built in" column names the milestone for each column.
- PostgreSQL. Tables are Django models.
- Every table has Django's `id` primary key (`bigint`) and `created_at`
  (`timestamptz`, set on insert).
- US addresses and US phone numbers only.
- Text columns are `varchar(n)` with the length shown. Text columns are `NOT NULL`. An
  optional text column stores `''`, not `NULL`.
- Enumerated values are short lowercase strings. Each has a check constraint that limits
  it to the listed values, in addition to Django `choices`.
- Foreign keys are `NO ACTION DEFERRABLE INITIALLY DEFERRED` in the database. The
  `on_delete` behaviour shown for each foreign key runs only through Django ORM deletes,
  not raw SQL.
- Each format rule (phone number, ZIP code, state code) is enforced twice: by a field
  validator, and by a database check constraint that holds when validation is bypassed.

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
| `household_id` | → `Household` | Nullable. `on_delete=models.SET_NULL`. A user belongs to at most one household. | M4 |

`groups` and `user_permissions` come from `PermissionsMixin`.

### `Household` (`gear_library_household`)

Built in M4. A residence. It owns gear.

| Column | Type | Rules |
|---|---|---|
| `name` | `varchar(32)` | |
| `owner_id` | → `User` | Unique. `on_delete=models.PROTECT`. |
| `street_address` | `varchar(64)` | |
| `address_line_2` | `varchar(64)` | Optional. |
| `city` | `varchar(64)` | |
| `state` | `varchar(2)` | One of the 50 state codes or `DC`. Check constraint on the list. |
| `zip_code` | `varchar(5)` | Exactly 5 digits, check `^[0-9]{5}$`. |
| `created_at` | `timestamptz` | |

### `HouseholdInvite` (`gear_library_householdinvite`)

Built in M4.

| Column | Type | Rules |
|---|---|---|
| `household_id` | → `Household` | `on_delete=models.CASCADE`. |
| `invitee_id` | → `User` | `on_delete=models.CASCADE`. |
| `status` | `varchar(8)` | `pending`, `accepted` or `declined`. |
| `created_at` | `timestamptz` | |

- Partial unique index on (`household_id`, `invitee_id`) where `status = 'pending'`: at
  most one pending invite per household and invitee.
- There is no inviter column. Only the owner invites.

### `Item` (`gear_library_item`)

Built in M5. A piece of gear.

| Column | Type | Rules |
|---|---|---|
| `household_id` | → `Household` | `on_delete=models.CASCADE`. |
| `name` | `varchar(64)` | |
| `description` | `varchar(512)` | Optional. |
| `borrower_id` | → `User` | Nullable. `on_delete=models.PROTECT`. |
| `loan_status` | `varchar(9)` | `available`, `requested` or `on_loan`. |
| `created_at` | `timestamptz` | |

- Check: `borrower_id IS NULL` exactly when `loan_status = 'available'`.
- There is no loan history. The row holds only the current loan state.

### `Connection` (`gear_library_connection`)

Built in M6. One row per pair of connected (or requested) users. A connection works both
ways.

| Column | Type | Rules |
|---|---|---|
| `first_user_id` | → `User` | `on_delete=models.CASCADE`. |
| `second_user_id` | → `User` | `on_delete=models.CASCADE`. |
| `requested_by_id` | → `User` | `on_delete=models.CASCADE`. |
| `status` | `varchar(8)` | `pending` or `accepted`. |
| `created_at` | `timestamptz` | |

- Check: `first_user_id < second_user_id`. The pair has one ordering, so it has one row.
- Check: `requested_by_id` is `first_user_id` or `second_user_id`.
- Unique on (`first_user_id`, `second_user_id`).

## Rules the app enforces

These rules span tables, so the database cannot check them alone.

- Creating a household makes the creator its owner and a member.
- The owner is always a member. Ownership transfers only to a current member. The owner
  must delete the household or transfer ownership before leaving.
- Invites go only to users with no household. Accepting checks this again, and fails if
  the invitee has a household by then. To move, a user leaves first.
- Accepting an invite clears the invitee from every item of that household they are
  requesting or borrowing: `borrower` becomes null and `loan_status` becomes `available`.
- Deleting a household deletes its items (with any loan state on them) and its invites.
  Its members go back to having no household.
- A borrow request is one conditional update: set the borrower only if the item is
  `available`. One requester at a time. Other requests are blocked until the request is
  declined or the item is returned.
- Any member of the owning household approves, declines, or marks an item returned.
  Members cannot request their own household's items.
