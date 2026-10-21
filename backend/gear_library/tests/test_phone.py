import pytest

from gear_library.phone import follows_numbering_plan, normalize_phone_number


@pytest.mark.parametrize(
    "value",
    [
        "5552234567",
        "(555) 223-4567",
        "555-223-4567",
        "555.223.4567",
        "555 223 4567",
        " 555 223 4567 ",
        "+1 555-223-4567",
        "+1 (555) 223-4567",
        "+15552234567",
        "1 555 223 4567",
        "15552234567",
        "1-555-223-4567",
    ],
)
def test_accepts_formatted_numbers(value):
    assert normalize_phone_number(value) == "5552234567"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "555223456",  # 9 digits
        "555223456789",  # 12 digits
        "25552234567",  # 11 digits not starting with 1
        "+5552234567",  # + without the country code
        "+2 555 223 4567",
        "1+5552234567",
        "555/223/4567",
        "555_223_4567",
        "555223456a",
        "555\t123\t4567",
        "١٢٣٤٥٦٧٨٩٠",  # Arabic-Indic digits
        "５５５１２３４５６７",  # fullwidth digits
    ],
)
def test_rejects_other_input(value):
    assert normalize_phone_number(value) is None


@pytest.mark.parametrize("digits", ["5555550101", "5555550103", "2002000000", "9999999999"])
def test_numbering_plan_accepts_area_codes_and_exchanges_from_2_to_9(digits):
    assert follows_numbering_plan(digits)


@pytest.mark.parametrize(
    "digits",
    [
        "0555550101",  # area code starts with 0
        "1555550101",  # area code starts with 1
        "5550550101",  # exchange starts with 0
        "5551550101",  # exchange starts with 1
    ],
)
def test_numbering_plan_rejects_a_0_or_1_at_the_start_of_the_area_code_or_exchange(digits):
    assert not follows_numbering_plan(digits)
