"""Every change to an item and its listings.

Only an item's owner creates, edits and deletes it. Editing is one conditional update on
the item's id and owner. Deleting locks the item row, then Django's cascade deletes its
listings and the row. An item that is gone or not the caller's gets `NotFound`.

Listing and removing a listing lock the inventory row through `inventories.lock_as`, which
re-reads the caller's membership, so they run one at a time with every other change that
takes that lock. Listing then locks the item row: it either commits before a delete of the
item reads its listings, or finds the item gone. Inventory rows are locked before item
rows.

An item that is not the caller's is a `ValidationError` on `item_id` with one message,
whether it is missing or someone else's, so the caller learns nothing about other users'
items. The unique index on (inventory, item) refuses a second listing with `Conflict`.
"""

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .errors import Conflict, violates
from .inventories import lock_as
from .models import ONE_LISTING_PER_ITEM, InventoryItem, Item, Role

ITEM_NOT_FOUND = "Item not found."
NOT_YOUR_ITEM = "You can list only your own items."
ALREADY_LISTED = "This item is already listed in this inventory."
LISTING_NOT_FOUND = "This item is not listed in this inventory."
OWN_ITEMS_ONLY = "Only owners can remove other people's items."


def create_item(user, fields):
    """`fields` are the item's `name` and, optionally, `description`."""
    return Item.objects.create(owner=user, **fields)


def update_item(user, item_id, fields):
    """Changes the caller's item `item_id`. `fields` may be empty."""
    mine = Item.objects.filter(pk=item_id, owner=user)
    if not (mine.update(**fields) if fields else mine.exists()):
        raise NotFound(ITEM_NOT_FOUND)


@transaction.atomic
def delete_item(user, item_id):
    item = Item.objects.select_for_update().filter(pk=item_id, owner=user).first()
    if item is None:
        raise NotFound(ITEM_NOT_FOUND)
    item.delete()


@transaction.atomic
def list_item(actor, item_id):
    """Lists the item `item_id` in the actor's inventory. `actor` must be an admin or
    owner, and is checked again with the inventory locked."""
    actor = lock_as(actor.user_id, actor.inventory_id, Role.ADMIN)
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


def _listing(inventory_id, item_id):
    listing = (
        InventoryItem.objects.select_related("item")
        .filter(inventory_id=inventory_id, item_id=item_id)
        .first()
    )
    if listing is None:
        raise NotFound(LISTING_NOT_FOUND)
    return listing


@transaction.atomic
def unlist_item(user, inventory_id, item_id):
    """Removes the item `item_id` from the inventory. An owner removes any item, and an
    admin only their own."""
    actor = lock_as(user.id, inventory_id, Role.ADMIN)
    listing = _listing(inventory_id, item_id)
    if actor.role != Role.OWNER and listing.item.owner_id != user.id:
        raise PermissionDenied(OWN_ITEMS_ONLY)
    # Deleting the item takes no inventory lock, so it may have removed the listing.
    if not InventoryItem.objects.filter(pk=listing.pk).delete()[0]:
        raise NotFound(LISTING_NOT_FOUND)
