"""Every borrow request and loan change a user makes.

A request is made through an inventory, its loan inventory. Requesting, approving,
declining and marking returned through an inventory lock the inventory row through
`inventories.lock_as`, which re-reads the caller's membership, and then check that the item
is listed there. Each change is then one conditional update of the item row that matches
the state the caller saw: its loan status, its borrower and the inventory. When no row
matches, the item changed in the meantime and the change gets `Conflict`.

Cancelling and the item owner's mark returned take no inventory lock. Each is one
conditional update of the item row, on its borrower or on its owner. Cancelling re-checks
no membership or listing: "Borrowing" in `docs/schema.md` says when a pending request
ends. The owner closes a loan whatever became of its listing and loan inventory.
"""

from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from .errors import Conflict
from .inventories import lock_as
from .items import ITEM_NOT_FOUND, LISTING_NOT_FOUND
from .models import InventoryItem, Item, LoanStatus, Role

OWN_ITEM = "You cannot borrow your own item."
NOT_AVAILABLE = "This item has already been requested or is on loan."
OWN_REQUEST = "You cannot approve or decline your own request."
OWN_LOAN = "You cannot mark your own loan returned."
LOAN_CHANGED = "This request or loan changed. Try again."
REQUEST_NOT_FOUND = "Request not found."
NOT_PENDING = "This request was approved, so it cannot be cancelled."


def _listed_item(user_id, inventory_id, item_id, role):
    """Locks the inventory, checks the caller's `role` there and returns the item listed
    there."""
    lock_as(user_id, inventory_id, role)
    listing = (
        InventoryItem.objects.select_related("item")
        .filter(inventory_id=inventory_id, item_id=item_id)
        .first()
    )
    if listing is None:
        raise NotFound(LISTING_NOT_FOUND)
    return listing.item


@transaction.atomic
def request_item(user, inventory_id, item_id):
    """Requests the item `item_id` through the inventory, where the caller is a member."""
    item = _listed_item(user.id, inventory_id, item_id, Role.MEMBER)
    if item.owner_id == user.id:
        raise PermissionDenied(OWN_ITEM)
    available = Item.objects.filter(pk=item.pk, loan_status=LoanStatus.AVAILABLE)
    if not available.update(
        loan_status=LoanStatus.REQUESTED, borrower=user, loan_inventory_id=inventory_id
    ):
        raise Conflict(NOT_AVAILABLE)


def _through(inventory_id, item_id, status, borrower_id):
    return Item.objects.filter(
        pk=item_id, loan_status=status, borrower_id=borrower_id, loan_inventory_id=inventory_id
    )


# `borrower_id` below is the requester or borrower the caller saw. An admin or owner of the
# inventory acts, and never on their own request or loan.


@transaction.atomic
def approve(user, inventory_id, item_id, borrower_id):
    _listed_item(user.id, inventory_id, item_id, Role.ADMIN)
    if borrower_id == user.id:
        raise PermissionDenied(OWN_REQUEST)
    pending = _through(inventory_id, item_id, LoanStatus.REQUESTED, borrower_id)
    if not pending.update(loan_status=LoanStatus.ON_LOAN):
        raise Conflict(LOAN_CHANGED)


@transaction.atomic
def decline(user, inventory_id, item_id, borrower_id):
    _listed_item(user.id, inventory_id, item_id, Role.ADMIN)
    if borrower_id == user.id:
        raise PermissionDenied(OWN_REQUEST)
    if not _through(inventory_id, item_id, LoanStatus.REQUESTED, borrower_id).end_loan():
        raise Conflict(LOAN_CHANGED)


@transaction.atomic
def mark_returned(user, inventory_id, item_id, borrower_id):
    """Ends a loan made through the inventory, while the item is listed there."""
    _listed_item(user.id, inventory_id, item_id, Role.ADMIN)
    if borrower_id == user.id:
        raise PermissionDenied(OWN_LOAN)
    if not _through(inventory_id, item_id, LoanStatus.ON_LOAN, borrower_id).end_loan():
        raise Conflict(LOAN_CHANGED)


def cancel(user, item_id):
    """Cancels the caller's pending request for the item `item_id`."""
    mine = Item.objects.filter(pk=item_id, borrower=user)
    if mine.filter(loan_status=LoanStatus.REQUESTED).end_loan():
        return
    if mine.exists():
        raise Conflict(NOT_PENDING)
    raise NotFound(REQUEST_NOT_FOUND)


def owner_mark_returned(user, item_id, borrower_id):
    """Ends the loan of the caller's item `item_id` to `borrower_id`."""
    mine = Item.objects.filter(pk=item_id, owner=user)
    if mine.filter(loan_status=LoanStatus.ON_LOAN, borrower_id=borrower_id).end_loan():
        return
    if mine.exists():
        raise Conflict(LOAN_CHANGED)
    raise NotFound(ITEM_NOT_FOUND)
