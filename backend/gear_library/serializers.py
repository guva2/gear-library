from django.contrib.auth import get_user_model
from rest_framework import serializers

from .inventories import has_role
from .models import InventoryItem, Item, Membership, Role
from .phone import normalize_phone_number

User = get_user_model()


class PhoneNumberField(serializers.CharField):
    default_error_messages = {
        "invalid": "Enter a 10-digit US phone number.",
    }

    def to_internal_value(self, data):
        phone_number = normalize_phone_number(super().to_internal_value(data))
        if phone_number is None:
            self.fail("invalid")
        return phone_number


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "phone_number", "first_name", "last_name"]
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()
    first_name = serializers.CharField(max_length=32)
    last_name = serializers.CharField(max_length=32)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class LoginSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class InventorySerializer(serializers.Serializer):
    """An inventory as one member sees it: `role` is that member's role."""

    id = serializers.IntegerField(source="inventory.id", read_only=True)
    name = serializers.CharField(source="inventory.name", read_only=True)
    role = serializers.CharField(read_only=True)


class InventoryNameSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=32)


class PersonNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "last_name"]
        read_only_fields = fields


class MemberSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    role = serializers.CharField(read_only=True)


class RoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)


class PersonNumberSerializer(serializers.Serializer):
    phone_number = serializers.CharField(read_only=True)


class InventoryInviteSerializer(serializers.ModelSerializer):
    """A pending membership as the inventory's admins and owners see it.

    The invitee appears by phone number only: every admin and owner of the inventory sees
    the invite, not only the one connected to the invitee.
    """

    invitee = PersonNumberSerializer(source="user", read_only=True)
    invited_by = PersonNameSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "invitee", "invited_by"]
        read_only_fields = fields


class InviteSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()


class PhoneNumberSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()


class MyInviteSerializer(serializers.ModelSerializer):
    """A pending membership as its invitee sees it, before joining."""

    inventory_name = serializers.CharField(source="inventory.name", read_only=True)
    invited_by = PersonNameSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "inventory_name", "invited_by"]
        read_only_fields = fields


class _ConnectionSerializer(serializers.Serializer):
    """A connection as one of its two users sees it: `user` is the other one. Pass the
    caller as `context["user"]`."""

    person_serializer = None

    id = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    user = serializers.SerializerMethodField()

    def get_user(self, connection):
        return self.person_serializer(connection.other_user(self.context["user"])).data


class ConnectionSerializer(_ConnectionSerializer):
    """An accepted connection, with the other user's id, name and phone number."""

    person_serializer = UserSerializer


class ReceivedRequestSerializer(_ConnectionSerializer):
    """A pending request the caller received. The requester appears by name only."""

    person_serializer = PersonNameSerializer


class SentRequestSerializer(_ConnectionSerializer):
    """A pending request the caller sent. The other user appears by phone number only,
    so sending and cancelling a request does not reveal whose number it is."""

    person_serializer = PersonNumberSerializer


class ItemFieldsSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64)
    description = serializers.CharField(max_length=512, allow_blank=True, required=False)


class ListedInSerializer(serializers.Serializer):
    """An inventory an item is listed in."""

    id = serializers.IntegerField(source="inventory.id", read_only=True)
    name = serializers.CharField(source="inventory.name", read_only=True)


class InventoryRefSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class ItemSerializer(serializers.ModelSerializer):
    """An item as its owner sees it, with the inventories it is listed in and its loan."""

    inventories = ListedInSerializer(source="listings", many=True, read_only=True)
    borrower = UserSerializer(read_only=True)
    loan_inventory = InventoryRefSerializer(read_only=True)

    class Meta:
        model = Item
        fields = [
            "id",
            "name",
            "description",
            "inventories",
            "loan_status",
            "borrower",
            "loan_inventory",
        ]
        read_only_fields = fields


class ListedItemSerializer(serializers.ModelSerializer):
    """A listed item as one member of the inventory sees it. `id` is the item's id. Pass
    the caller's membership as `context["membership"]`.

    Only admins and owners see the requester or borrower, and only of a request or loan
    made through this inventory. Other members see the loan status alone, and whether the
    item is requested by or lent to them.
    """

    id = serializers.IntegerField(source="item.id", read_only=True)
    name = serializers.CharField(source="item.name", read_only=True)
    description = serializers.CharField(source="item.description", read_only=True)
    owner = PersonNameSerializer(source="item.owner", read_only=True)
    loan_status = serializers.CharField(source="item.loan_status", read_only=True)
    borrowed_by_me = serializers.SerializerMethodField()
    borrower = serializers.SerializerMethodField()

    class Meta:
        model = InventoryItem
        fields = [
            "id",
            "name",
            "description",
            "owner",
            "loan_status",
            "borrowed_by_me",
            "borrower",
        ]
        read_only_fields = fields

    def get_borrowed_by_me(self, listing):
        return listing.item.borrower_id == self.context["membership"].user_id

    def get_borrower(self, listing):
        item = listing.item
        through_here = item.loan_inventory_id == listing.inventory_id
        if not through_here or not has_role(self.context["membership"], Role.ADMIN):
            return None
        return UserSerializer(item.borrower).data


class BorrowedItemSerializer(serializers.ModelSerializer):
    """An item the caller has requested or borrowed. The owner appears by name only."""

    owner = PersonNameSerializer(read_only=True)
    loan_inventory = InventoryRefSerializer(read_only=True)

    class Meta:
        model = Item
        fields = ["id", "name", "description", "loan_status", "owner", "loan_inventory"]
        read_only_fields = fields


class ItemIdSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()


class BorrowerIdSerializer(serializers.Serializer):
    borrower_id = serializers.IntegerField()
