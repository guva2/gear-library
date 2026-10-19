import pytest

from gear_library.phone import normalize_phone_number


@pytest.mark.parametrize(
    "value",
    [
        "5551234567",
        "(555) 123-4567",
        "555-123-4567",
        "555.123.4567",
        "555 123 4567",
        " 555 123 4567 ",
        "+1 555-123-4567",
        "+1 (555) 123-4567",
        "+15551234567",
        "1 555 123 4567",
        "15551234567",
        "1-555-123-4567",
    ],
)
def test_accepts_formatted_numbers(value):
    assert normalize_phone_number(value) == "5551234567"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "555123456",  # 9 digits
        "555123456789",  # 12 digits
        "25551234567",  # 11 digits not starting with 1
        "+5551234567",  # + without the country code
        "+2 555 123 4567",
        "1+5551234567",
        "555/123/4567",
        "555_123_4567",
        "555123456a",
        "555\t123\t4567",
        "١٢٣٤٥٦٧٨٩٠",  # Arabic-Indic digits
        "５５５１２３４５６７",  # fullwidth digits
    ],
)
def test_rejects_other_input(value):
    assert normalize_phone_number(value) is None
