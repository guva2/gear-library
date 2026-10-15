import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction

User = get_user_model()

PHONE = "5551234567"
CONSTRAINT = "core_user_phone_number_10_digits"

# Each value fits in the column, so only the check constraint can reject it.
INVALID_PHONES = [
    "",
    "555123456",  # 9 digits
    "555-123-45",
    "555123456a",
    " 555123456",
    "١٢٣٤٥٦٧٨٩٠",  # Arabic-Indic digits
]


@pytest.mark.django_db
class TestCreateUser:
    def test_stores_phone_and_hashes_password(self):
        user = User.objects.create_user(phone_number=PHONE, password="s3cret-pass")

        user.refresh_from_db()
        assert user.phone_number == PHONE
        assert user.password != "s3cret-pass"
        assert user.check_password("s3cret-pass")
        assert user.is_active
        assert not user.is_staff
        assert not user.is_superuser
        assert user.created_at is not None

    def test_user_authenticates_by_phone_number(self):
        User.objects.create_user(phone_number=PHONE, password="s3cret-pass")

        assert authenticate(phone_number=PHONE, password="s3cret-pass") is not None
        assert authenticate(phone_number=PHONE, password="wrong") is None

    def test_without_password_is_unusable(self):
        user = User.objects.create_user(phone_number=PHONE)

        assert not user.has_usable_password()

    def test_requires_phone_number(self):
        with pytest.raises(ValueError):
            User.objects.create_user(phone_number="", password="s3cret-pass")

    @pytest.mark.parametrize(
        "phone", [p for p in INVALID_PHONES if p] + ["55512345678"]
    )
    def test_rejects_invalid_phone_number(self, phone):
        with pytest.raises(ValidationError):
            User.objects.create_user(phone_number=phone, password="s3cret-pass")
        assert not User.objects.exists()


@pytest.mark.django_db
class TestCreateSuperuser:
    def test_sets_staff_and_superuser_flags(self):
        user = User.objects.create_superuser(phone_number=PHONE, password="s3cret-pass")

        assert user.is_staff
        assert user.is_superuser
        assert user.is_active

    @pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
    def test_refuses_flag_set_false(self, flag):
        with pytest.raises(ValueError):
            User.objects.create_superuser(
                phone_number=PHONE, password="s3cret-pass", **{flag: False}
            )

    def test_createsuperuser_command(self, monkeypatch):
        monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "s3cret-pass")

        call_command("createsuperuser", "--noinput", phone_number=PHONE, verbosity=0)

        user = User.objects.get(phone_number=PHONE)
        assert user.is_superuser
        assert user.check_password("s3cret-pass")


@pytest.mark.django_db
class TestPhoneNumberValidator:
    @pytest.mark.parametrize("phone", INVALID_PHONES + ["55512345678"])
    def test_full_clean_rejects(self, phone):
        user = User(phone_number=phone)
        user.set_password("s3cret-pass")

        with pytest.raises(ValidationError) as excinfo:
            user.full_clean()
        assert "phone_number" in excinfo.value.message_dict

    def test_full_clean_accepts_ten_digits(self):
        user = User(phone_number=PHONE)
        user.set_password("s3cret-pass")

        user.full_clean()


@pytest.mark.django_db
class TestPhoneNumberDatabaseConstraints:
    @pytest.mark.parametrize("phone", INVALID_PHONES)
    def test_check_constraint_rejects_insert(self, phone):
        with pytest.raises(IntegrityError, match=CONSTRAINT), transaction.atomic():
            User.objects.bulk_create([User(phone_number=phone, password="x")])

    def test_check_constraint_rejects_update(self):
        user = User.objects.create_user(phone_number=PHONE, password="s3cret-pass")

        with pytest.raises(IntegrityError, match=CONSTRAINT), transaction.atomic():
            User.objects.filter(pk=user.pk).update(phone_number="12345")

    def test_phone_number_is_unique(self):
        User.objects.create_user(phone_number=PHONE, password="s3cret-pass")

        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(phone_number=PHONE, password="x")])
