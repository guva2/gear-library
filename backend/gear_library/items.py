"""Every change to an item and its listings.

Only an item's owner creates, edits and deletes it. Editing is one conditional update on
the item's id and owner. An item that is gone or not the caller's gets `NotFound`.

`remove_listing` runs two statements and expects to run inside the caller's transaction.

Listing and removing a listing run with the inventory row locked by
`inventories.lock_inventory`. Listing then locks the item row, and removing a listing
cancels a pending request made through the inventory. Inventory rows are locked before
item rows.

Deleting locks the inventories the item is listed in, in ascending `id` order, then the
item row. It re-reads the listings under those locks: a listing added after the first read
is in an inventory not locked yet, and locking it while holding the item row would invert
the order, so the delete is refused (`Conflict`). An item on loan is not deleted
(`Conflict`). Django's cascade deletes the listings and the row.

An item that is not the caller's is a `ValidationError` on `item_id` with one message,
whether it is missing or someone else's, so the caller learns nothing about other users'
items. The unique index on (inventory, item) refuses a second listing with `Conflict`.
"""

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, ValidationError

from .errors import Conflict, violates
from .models import ONE_LISTING_PER_ITEM, Inventory, InventoryItem, Item, LoanStatus

ITEM_NOT_FOUND = "Item not found."
NOT_YOUR_ITEM = "You can list only your own items."
ALREADY_LISTED = "This item is already listed in this inventory."
LISTING_NOT_FOUND = "This item is not listed in this inventory."
OWN_ITEMS_ONLY = "Only owners can remove other people's items."
ON_LOAN = "This item is on loan. It can be deleted once it is returned."
ITEM_CHANGED = "This item changed. Try again."


def create_item(user, fields):
    """`fields` are the item's `name` and, optionally, `description`."""
    return Item.objects.create(owner=user, **fields)


def update_item(user, item_id, fields):
    """Changes the caller's item `item_id`. `fields` may be empty."""
    mine = Item.objects.filter(pk=item_id, owner=user)
    if not (mine.update(**fields) if fields else mine.exists()):
        raise NotFound(ITEM_NOT_FOUND)


def _inventories_of(item):
    listed = InventoryItem.objects.filter(item_id=item.pk).values_list("inventory_id", flat=True)
    return set(listed)


@transaction.atomic
def delete_item(user, item_id):
    item = Item.objects.filter(pk=item_id, owner=user).first()
    if item is None:
        raise NotFound(ITEM_NOT_FOUND)
    locked = _inventories_of(item)
    list(Inventory.objects.select_for_update().filter(pk__in=locked).order_by("id"))
    item = Item.objects.select_for_update().filter(pk=item_id, owner=user).first()
    if item is None:
        raise NotFound(ITEM_NOT_FOUND)
    if item.loan_status == LoanStatus.ON_LOAN:
        raise Conflict(ON_LOAN)
    # The item was listed after the first read, in an inventory not locked here. Only the
    # owner lists their item, so this needs the owner to list and delete the same item at
    # once; it is not expected in practice.
    if not _inventories_of(item) <= locked:
        raise Conflict(ITEM_CHANGED)
    item.delete()


def add_listing(actor, item_id):
    """Lists the item `item_id` in the actor's inventory. `actor`, the caller's membership,
    must be an admin or owner."""
    item = Item.objects.select_for_update().filter(pk=item_id, owner_id=actor.user_id).first()
    if item is None:
        raise ValidationError({"item_id": [NOT_YOUR_ITEM]})
    try:
        with transaction.atomic():
            return InventoryItem.objects.create(inventory=actor.inventory, item=item)
    except IntegrityError as error:
        if violates(error, ONE_LISTING_PER_ITEM):
            raise Conflict(ALREADY_LISTED)
        raise


def remove_listing(listing):
    """Removes the listing and cancels a pending request made through its inventory."""
    listing.delete()
    Item.objects.filter(pk=listing.item_id).cancel_requests_through(listing.inventory_id)
