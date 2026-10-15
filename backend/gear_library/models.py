from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models

# [0-9], not \d: Python's \d matches any Unicode digit, not only ASCII 0-9.
PHONE_NUMBER_PATTERN = r"^[0-9]{10}$"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError("A phone number is required.")
        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        return self.create_user(phone_number, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    phone_number = models.CharField(
        max_length=10,
        unique=True,
        validators=[
            RegexValidator(
                PHONE_NUMBER_PATTERN,
                message="Enter a US phone number as exactly 10 digits.",
            )
        ],
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(phone_number__regex=PHONE_NUMBER_PATTERN),
                name="gear_library_user_phone_number_10_digits",
            ),
        ]

    def __str__(self):
        return self.phone_number
