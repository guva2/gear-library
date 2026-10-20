"""Every borrow request and loan change a user makes.

A request or loan is made through an inventory, its loan inventory. Borrowing, approving,
declining and marking returned through an inventory take the item's listing there, read
with the inventory row locked by `inventories.lock_inventory`. Each change is then one
conditional update of the item row that matches the state the caller saw: its loan status,
its borrower and the inventory. When no row matches, the item changed in the meantime and
the change gets `Conflict`.

Cancelling, the item owner's use and the item owner's mark returned take no inventory
lock. Each is one conditional update of the item row, on its borrower or on its owner, and
holds no other lock while it waits on that row. Cancelling re-checks no membership or
listing: "Borrowing" in `docs/schema.md` says when a pending request ends. The owner closes
a loan whatever became of its listing and loan inventory.
"""

from rest_framework.exceptions import NotFound, PermissionDenied

from .errors import Conflict
from .inventories import has_role
from .items import ITEM_NOT_FOUND
from .models import Item, LoanStatus, Role

OWN_ITEM = "You cannot borrow your own item."
NOT_AVAILABLE = "This item has already been requested or is on loan."
OWN_REQUEST = "You cannot approve or decline your own request."
LOAN_CHANGED = "This request or loan changed. Try again."
REQUEST_NOT_FOUND = "Request not found."
NOT_PENDING = "This request was approved, so it cannot be cancelled."


def _available(**lookup):
    return Item.objects.filter(loan_status=LoanStatus.AVAILABLE, **lookup)


def borrow(actor, listing):
    """Borrows the listed item through the listing's inventory. `actor`, the caller's
    membership there, makes a request as a `member` and takes the item on loan at once as
    an admin or owner."""
    if listing.item.owner_id == actor.user_id:
        raise PermissionDenied(OWN_ITEM)
    status = LoanStatus.ON_LOAN if has_role(actor, Role.ADMIN) else LoanStatus.REQUESTED
    if not _available(pk=listing.item_id).update(
        loan_status=status, borrower_id=actor.user_id, loan_inventory_id=listing.inventory_id
    ):
        raise Conflict(NOT_AVAILABLE)


def _through(listing, status, borrower_id):
    return Item.objects.filter(
        pk=listing.item_id,
        loan_status=status,
        borrower_id=borrower_id,
        loan_inventory_id=listing.inventory_id,
    )


# `borrower_id` below is the requester or borrower the caller saw. An admin or owner of the
# listing's inventory acts.


def approve(user, listing, borrower_id):
    if borrower_id == user.id:
        raise PermissionDenied(OWN_REQUEST)
    pending = _through(listing, LoanStatus.REQUESTED, borrower_id)
    if not pending.update(loan_status=LoanStatus.ON_LOAN):
        raise Conflict(LOAN_CHANGED)


def decline(user, listing, borrower_id):
    if borrower_id == user.id:
        raise PermissionDenied(OWN_REQUEST)
    if not _through(listing, LoanStatus.REQUESTED, borrower_id).end_loan():
        raise Conflict(LOAN_CHANGED)


def mark_returned(user, listing, borrower_id):
    """Ends a loan made through the listing's inventory, the caller's own included."""
    if not _through(listing, LoanStatus.ON_LOAN, borrower_id).end_loan():
        raise Conflict(LOAN_CHANGED)


def cancel(user, item_id):
    """Cancels the caller's pending request for the item `item_id`."""
    mine = Item.objects.filter(pk=item_id, borrower=user)
    if mine.filter(loan_status=LoanStatus.REQUESTED).end_loan():
        return
    if mine.exists():
        raise Conflict(NOT_PENDING)
    raise NotFound(REQUEST_NOT_FOUND)


def use(user, item_id):
    """Puts the caller's item `item_id` on loan to the caller, with no loan inventory."""
    mine = _available(pk=item_id, owner=user)
    if mine.update(loan_status=LoanStatus.ON_LOAN, borrower=user, loan_inventory=None):
        return
    if Item.objects.filter(pk=item_id, owner=user).exists():
        raise Conflict(NOT_AVAILABLE)
    raise NotFound(ITEM_NOT_FOUND)


def owner_mark_returned(user, item_id, borrower_id):
    """Ends the loan of the caller's item `item_id` to `borrower_id`."""
    mine = Item.objects.filter(pk=item_id, owner=user)
    if mine.filter(loan_status=LoanStatus.ON_LOAN, borrower_id=borrower_id).end_loan():
        return
    if mine.exists():
        raise Conflict(LOAN_CHANGED)
    raise NotFound(ITEM_NOT_FOUND)
