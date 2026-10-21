import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction

User = get_user_model()

PHONE = "5552234567"
CONSTRAINT = "gear_library_user_phone_number_valid"
NAMES = {"first_name": "Ada", "last_name": "Lovelace"}

# Each value fits in the column, so only the check constraint can reject it.
INVALID_PHONES = [
    "",
    "555223456",  # 9 digits
    "555-223-45",
    "555223456a",
    " 555223456",
    "١٢٣٤٥٦٧٨٩٠",  # Arabic-Indic digits
    "0552234567",  # area code starts with 0
    "1552234567",  # area code starts with 1
    "5550234567",  # exchange starts with 0
    "5551234567",  # exchange starts with 1
]


@pytest.mark.django_db
class TestCreateUser:
    def test_stores_phone_and_hashes_password(self):
        user = User.objects.create_user(phone_number=PHONE, password="s3cret-pass", **NAMES)

        user.refresh_from_db()
        assert user.phone_number == PHONE
        assert user.password != "s3cret-pass"
        assert user.check_password("s3cret-pass")
        assert user.is_active
        assert not user.is_staff
        assert not user.is_superuser
        assert user.created_at is not None

    def test_user_authenticates_by_phone_number(self):
        User.objects.create_user(phone_number=PHONE, password="s3cret-pass", **NAMES)

        assert authenticate(phone_number=PHONE, password="s3cret-pass") is not None
        assert authenticate(phone_number=PHONE, password="wrong") is None

    def test_without_password_is_unusable(self):
        user = User.objects.create_user(phone_number=PHONE, **NAMES)

        assert not user.has_usable_password()

    def test_requires_phone_number(self):
        with pytest.raises(ValueError):
            User.objects.create_user(phone_number="", password="s3cret-pass", **NAMES)

    @pytest.mark.parametrize(
        "phone", [p for p in INVALID_PHONES if p] + ["55522345678"]
    )
    def test_rejects_invalid_phone_number(self, phone):
        with pytest.raises(ValidationError):
            User.objects.create_user(phone_number=phone, password="s3cret-pass", **NAMES)
        assert not User.objects.exists()


@pytest.mark.django_db
class TestCreateSuperuser:
    def test_sets_staff_and_superuser_flags(self):
        user = User.objects.create_superuser(phone_number=PHONE, password="s3cret-pass", **NAMES)

        assert user.is_staff
        assert user.is_superuser
        assert user.is_active

    @pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
    def test_refuses_flag_set_false(self, flag):
        with pytest.raises(ValueError):
            User.objects.create_superuser(
                phone_number=PHONE, password="s3cret-pass", **NAMES, **{flag: False}
            )

    def test_createsuperuser_command(self, monkeypatch):
        monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "s3cret-pass")

        call_command(
            "createsuperuser", "--noinput", phone_number=PHONE, **NAMES, verbosity=0
        )

        user = User.objects.get(phone_number=PHONE)
        assert user.is_superuser
        assert user.check_password("s3cret-pass")


@pytest.mark.django_db
class TestPhoneNumberValidator:
    @pytest.mark.parametrize("phone", INVALID_PHONES + ["55522345678"])
    def test_full_clean_rejects(self, phone):
        user = User(phone_number=phone, **NAMES)
        user.set_password("s3cret-pass")

        with pytest.raises(ValidationError) as excinfo:
            user.full_clean()
        assert "phone_number" in excinfo.value.message_dict

    def test_full_clean_accepts_ten_digits(self):
        user = User(phone_number=PHONE, **NAMES)
        user.set_password("s3cret-pass")

        user.full_clean()


@pytest.mark.django_db
class TestPhoneNumberDatabaseConstraints:
    @pytest.mark.parametrize("phone", INVALID_PHONES)
    def test_check_constraint_rejects_insert(self, phone):
        with pytest.raises(IntegrityError, match=CONSTRAINT), transaction.atomic():
            User.objects.bulk_create([User(phone_number=phone, password="x", **NAMES)])

    def test_check_constraint_rejects_update(self):
        user = User.objects.create_user(phone_number=PHONE, password="s3cret-pass", **NAMES)

        with pytest.raises(IntegrityError, match=CONSTRAINT), transaction.atomic():
            User.objects.filter(pk=user.pk).update(phone_number="12345")

    def test_phone_number_is_unique(self):
        User.objects.create_user(phone_number=PHONE, password="s3cret-pass", **NAMES)

        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(phone_number=PHONE, password="x", **NAMES)])


@pytest.mark.django_db
class TestNames:
    def test_create_user_stores_names(self):
        user = User.objects.create_user(
            phone_number=PHONE, password="s3cret-pass", first_name="Ada", last_name="Lovelace"
        )

        user.refresh_from_db()
        assert (user.first_name, user.last_name) == ("Ada", "Lovelace")

    @pytest.mark.parametrize("field", ["first_name", "last_name"])
    @pytest.mark.parametrize("value", ["", "   ", "\u00a0\u3000", "x" * 33])
    def test_full_clean_rejects_blank_or_long_name(self, field, value):
        user = User(phone_number=PHONE, first_name="Ada", last_name="Lovelace")
        setattr(user, field, value)
        user.set_password("s3cret-pass")

        with pytest.raises(ValidationError) as excinfo:
            user.full_clean()
        assert field in excinfo.value.message_dict

    def test_full_clean_accepts_32_character_names(self):
        user = User(phone_number=PHONE, first_name="x" * 32, last_name="y" * 32)
        user.set_password("s3cret-pass")

        user.full_clean()

    @pytest.mark.parametrize("field", ["first_name", "last_name"])
    @pytest.mark.parametrize("value", ["", " ", "\t\u3000"])
    def test_check_constraint_rejects_a_blank_name(self, field, value):
        user = User(phone_number=PHONE, password="x", first_name="Ada", last_name="Lovelace")
        setattr(user, field, value)

        with pytest.raises(IntegrityError, match=f"gear_library_user_{field}_not_blank"):
            with transaction.atomic():
                User.objects.bulk_create([user])

    def test_check_constraint_rejects_blanking_a_name(self):
        user = User.objects.create_user(phone_number=PHONE, password="x", **NAMES)

        with pytest.raises(IntegrityError, match="gear_library_user_last_name_not_blank"):
            with transaction.atomic():
                User.objects.filter(pk=user.pk).update(last_name="")

    def test_check_constraint_accepts_a_name_with_spaces_around_it(self):
        User.objects.bulk_create(
            [User(phone_number=PHONE, password="x", first_name=" Ada ", last_name="Lovelace")]
        )
