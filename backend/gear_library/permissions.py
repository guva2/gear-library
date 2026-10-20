"""Who may call a view, decided from the URL, the caller and the object the URL names.
The checks only read."""

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission

from . import connections, inventories, items
from .models import Membership, MembershipStatus, Role


class IsAnonymous(BasePermission):
    message = "You are already logged in."

    def has_permission(self, request, view):
        return not request.user.is_authenticated


class InventoryRole(BasePermission):
    """The caller is an active member of the view's inventory, `view.inventory_id()`, with
    the role `view.required_role(request)` or a higher one.

    A non-member gets `NotFound` and a member without the role is refused. On success the
    caller's membership, with its inventory, is `request.membership`.
    """

    def has_permission(self, request, view):
        membership = (
            Membership.objects.active()
            .select_related("inventory")
            .filter(inventory_id=view.inventory_id(), user=request.user)
            .first()
        )
        if membership is None:
            raise NotFound(inventories.INVENTORY_NOT_FOUND)
        role = view.required_role(request)
        if not inventories.has_role(membership, role):
            self.message = inventories.ROLE_REQUIRED[role]
            return False
        request.membership = membership
        return True


class OwnItemOrOwner(BasePermission):
    """An owner of the inventory acts on any listing, anyone else only on their own items'.
    Needs `InventoryRole` first."""

    message = items.OWN_ITEMS_ONLY

    def has_object_permission(self, request, view, listing):
        return request.membership.role == Role.OWNER or listing.item.owner_id == request.user.id


ANSWER_INVITE = "You cannot do this with this invite."


class IsInvitee(BasePermission):
    message = ANSWER_INVITE

    def has_object_permission(self, request, view, invite):
        return invite.user_id == request.user.id


class IsInviteInventoryAdmin(BasePermission):
    """The caller is an active admin or owner of the invite's inventory. Needs the invite
    from `InviteViewSet.get_queryset`, which holds another user's membership only for such
    a caller."""

    message = ANSWER_INVITE

    def has_object_permission(self, request, view, invite):
        if invite.user_id != request.user.id:
            return True
        return invite.status == MembershipStatus.ACTIVE and inventories.has_role(
            invite, Role.ADMIN
        )


class ReceivedRequest(BasePermission):
    message = connections.RECEIVER_ONLY

    def has_object_permission(self, request, view, connection):
        return connection.requested_by_id != request.user.id


class SentRequest(BasePermission):
    message = connections.REQUESTER_ONLY

    def has_object_permission(self, request, view, connection):
        return connection.requested_by_id == request.user.id
