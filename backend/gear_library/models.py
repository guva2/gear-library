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
        error_messages={"unique": "A user with this phone number already exists."},
    )
    first_name = models.CharField(max_length=32)
    last_name = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(phone_number__regex=PHONE_NUMBER_PATTERN),
                name="gear_library_user_phone_number_10_digits",
            ),
        ]

    def __str__(self):
        return self.phone_number


class Inventory(models.Model):
    name = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


class Membership(models.Model):
    inventory = models.ForeignKey(
        Inventory, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=6, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values),
                name="gear_library_membership_role_valid",
            ),
            models.UniqueConstraint(
                fields=["inventory", "user"], name="gear_library_membership_one_per_user"
            ),
        ]


class InviteStatus(models.TextChoices):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"


class InventoryInvite(models.Model):
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name="invites")
    invitee = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="invites_received"
    )
    invited_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="invites_sent"
    )
    status = models.CharField(
        max_length=8, choices=InviteStatus.choices, default=InviteStatus.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=InviteStatus.values),
                name="gear_library_inventoryinvite_status_valid",
            ),
            models.UniqueConstraint(
                fields=["inventory", "invitee"],
                condition=models.Q(status=InviteStatus.PENDING),
                name="gear_library_inventoryinvite_one_pending",
            ),
        ]
