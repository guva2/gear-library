from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Membership, Role
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

    The invitee appears by phone number only: a name or user id would let anyone who can
    send an invite look up who holds a number.
    """

    invitee = PersonNumberSerializer(source="user", read_only=True)
    invited_by = PersonNameSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "invitee", "invited_by"]
        read_only_fields = fields


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
