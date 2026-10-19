"""Every change to an inventory, its memberships and its invites.

Each change runs in one transaction that first locks the inventory row, then re-reads the
acting user's membership and the rows the change depends on. Changes to one inventory
therefore run one at a time, and each sees the state the previous one committed.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .models import Inventory, InventoryInvite, InviteStatus, Membership, Role

User = get_user_model()

_RANK = {Role.MEMBER: 0, Role.ADMIN: 1, Role.OWNER: 2}

INVENTORY_NOT_FOUND = "Inventory not found."
INVITE_NOT_FOUND = "Invite not found."
MEMBER_NOT_FOUND = "This user is not a member of the inventory."
ROLE_REQUIRED = {
    Role.ADMIN: "Only admins and owners can do this.",
    Role.OWNER: "Only owners can do this.",
}
LAST_OWNER = "An inventory must keep at least one owner."
NO_SUCH_USER = "No user has this phone number."


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state."
    default_code = "conflict"


def has_role(membership, role):
    """True when `membership` has `role` or a higher one."""
    return _RANK[membership.role] >= _RANK[role]


def get_membership(user, inventory_id, role=Role.MEMBER):
    """The caller's membership, read without a lock. A non-member gets `NotFound`, and a
    member without `role` or a higher one gets `PermissionDenied`."""
    membership = (
        Membership.objects.select_related("inventory")
        .filter(inventory_id=inventory_id, user=user)
        .first()
    )
    if membership is None:
        raise NotFound(INVENTORY_NOT_FOUND)
    if not has_role(membership, role):
        raise PermissionDenied(ROLE_REQUIRED[role])
    return membership


def _lock_inventory(inventory_id):
    inventory = Inventory.objects.select_for_update().filter(pk=inventory_id).first()
    if inventory is None:
        raise NotFound(INVENTORY_NOT_FOUND)
    return inventory


def _lock_as(user, inventory_id, role):
    """Locks the inventory and returns the caller's membership, which must have `role`."""
    inventory = _lock_inventory(inventory_id)
    membership = Membership.objects.filter(inventory=inventory, user=user).first()
    if membership is None:
        raise NotFound(INVENTORY_NOT_FOUND)
    membership.inventory = inventory
    if not has_role(membership, role):
        raise PermissionDenied(ROLE_REQUIRED[role])
    return membership


def _target_membership(inventory, user_id):
    membership = Membership.objects.filter(inventory=inventory, user_id=user_id).first()
    if membership is None:
        raise NotFound(MEMBER_NOT_FOUND)
    return membership


def _refuse_losing_last_owner(membership):
    """Called before `membership` stops being an owner, with the inventory locked."""
    if membership.role != Role.OWNER:
        return
    owners = Membership.objects.filter(inventory_id=membership.inventory_id, role=Role.OWNER)
    if not owners.exclude(pk=membership.pk).exists():
        raise Conflict(LAST_OWNER)


@transaction.atomic
def create_inventory(user, name):
    inventory = Inventory.objects.create(name=name)
    Membership.objects.create(inventory=inventory, user=user, role=Role.OWNER)
    return inventory


@transaction.atomic
def rename_inventory(user, inventory_id, name):
    membership = _lock_as(user, inventory_id, Role.OWNER)
    membership.inventory.name = name
    membership.inventory.save(update_fields=["name"])
    return membership


@transaction.atomic
def delete_inventory(user, inventory_id):
    membership = _lock_as(user, inventory_id, Role.OWNER)
    membership.inventory.delete()


@transaction.atomic
def set_role(user, inventory_id, member_user_id, role):
    actor = _lock_as(user, inventory_id, Role.OWNER)
    target = _target_membership(actor.inventory, member_user_id)
    if role != Role.OWNER:
        _refuse_losing_last_owner(target)
    target.role = role
    target.save(update_fields=["role"])
    return target


@transaction.atomic
def remove_member(user, inventory_id, member_user_id):
    """Removes a member. Removing yourself is leaving, which any member may do."""
    leaving = member_user_id == user.id
    actor = _lock_as(user, inventory_id, Role.MEMBER if leaving else Role.OWNER)
    target = actor if leaving else _target_membership(actor.inventory, member_user_id)
    _refuse_losing_last_owner(target)
    target.delete()


@transaction.atomic
def invite(user, inventory_id, phone_number):
    """Invites the user with `phone_number`. The caller's role is checked before the
    number is looked up, so a plain member or outsider learns nothing. An admin or owner
    can still tell whether a number has an account: an unknown one is a `ValidationError`."""
    actor = _lock_as(user, inventory_id, Role.ADMIN)
    invitee = User.objects.filter(phone_number=phone_number).first()
    if invitee is None:
        raise ValidationError({"phone_number": [NO_SUCH_USER]})
    if Membership.objects.filter(inventory=actor.inventory, user=invitee).exists():
        raise Conflict("This user is already a member.")
    pending = InventoryInvite.objects.filter(
        inventory=actor.inventory, invitee=invitee, status=InviteStatus.PENDING
    )
    if pending.exists():
        raise Conflict("This user already has a pending invite.")
    return InventoryInvite.objects.create(
        inventory=actor.inventory, invitee=invitee, invited_by=user
    )


def _lock_invite(user, invite_id, by_invitee):
    """Locks the invite's inventory, re-reads the invite and checks it is still pending.

    The invitee and the inventory's admins and owners see the invite; anyone else gets
    `NotFound`. The action is the invitee's when `by_invitee`, otherwise an admin's or an
    owner's; a caller who sees the invite but may not act gets `PermissionDenied`.
    """
    inventory_id = (
        InventoryInvite.objects.filter(pk=invite_id)
        .values_list("inventory_id", flat=True)
        .first()
    )
    if inventory_id is None:
        raise NotFound(INVITE_NOT_FOUND)
    try:
        _lock_inventory(inventory_id)
    except NotFound:
        raise NotFound(INVITE_NOT_FOUND)
    invite = InventoryInvite.objects.filter(pk=invite_id).first()
    if invite is None:
        raise NotFound(INVITE_NOT_FOUND)

    is_invitee = invite.invitee_id == user.id
    membership = Membership.objects.filter(inventory_id=inventory_id, user=user).first()
    is_admin = membership is not None and has_role(membership, Role.ADMIN)
    if not (is_invitee or is_admin):
        raise NotFound(INVITE_NOT_FOUND)
    if not (is_invitee if by_invitee else is_admin):
        raise PermissionDenied("You cannot do this with this invite.")
    if invite.status != InviteStatus.PENDING:
        raise Conflict("This invite is no longer pending.")
    return invite


def _set_status(invite, status):
    invite.status = status
    invite.save(update_fields=["status"])


@transaction.atomic
def accept_invite(user, invite_id):
    invite = _lock_invite(user, invite_id, by_invitee=True)
    if Membership.objects.filter(inventory_id=invite.inventory_id, user=user).exists():
        raise Conflict("You are already a member.")
    _set_status(invite, InviteStatus.ACCEPTED)
    return Membership.objects.create(
        inventory_id=invite.inventory_id, user=user, role=Role.MEMBER
    )


@transaction.atomic
def decline_invite(user, invite_id):
    invite = _lock_invite(user, invite_id, by_invitee=True)
    _set_status(invite, InviteStatus.DECLINED)


@transaction.atomic
def revoke_invite(user, invite_id):
    invite = _lock_invite(user, invite_id, by_invitee=False)
    _set_status(invite, InviteStatus.REVOKED)
