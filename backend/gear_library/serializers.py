from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import InventoryInvite, Role
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


class InventoryInviteSerializer(serializers.ModelSerializer):
    """A pending invite as the inventory's admins and owners see it."""

    invitee = UserSerializer(read_only=True)
    invited_by = PersonNameSerializer(read_only=True)

    class Meta:
        model = InventoryInvite
        fields = ["id", "invitee", "invited_by"]
        read_only_fields = fields


class NewInviteSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()


class MyInviteSerializer(serializers.ModelSerializer):
    """A pending invite as its invitee sees it, before joining."""

    inventory_name = serializers.CharField(source="inventory.name", read_only=True)
    invited_by = PersonNameSerializer(read_only=True)

    class Meta:
        model = InventoryInvite
        fields = ["id", "inventory_name", "invited_by"]
        read_only_fields = fields
