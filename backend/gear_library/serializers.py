from django.contrib.auth import get_user_model
from rest_framework import serializers

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
