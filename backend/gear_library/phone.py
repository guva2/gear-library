import re

_SEPARATORS = re.compile(r"[ .()\-]")
# [0-9], not \d: Python's \d matches any Unicode digit, not only ASCII 0-9.
_US_NUMBER = re.compile(r"(?:\+?1)?([0-9]{10})")

# A stored phone number: 10 ASCII digits under the North American Numbering Plan, where
# the area code (first digit) and the exchange (fourth digit) never start with 0 or 1.
PHONE_NUMBER_PATTERN = r"^[2-9][0-9]{2}[2-9][0-9]{6}$"


def normalize_phone_number(value):
    """Return the 10 digits of a US phone number, or None if `value` is not one.

    Accepts spaces, dots, dashes and parentheses anywhere, and an optional leading `1` or
    `+1` country code. The digits may still break the numbering plan: see
    `follows_numbering_plan`.
    """
    match = _US_NUMBER.fullmatch(_SEPARATORS.sub("", value))
    return match.group(1) if match else None


def follows_numbering_plan(digits):
    """Whether 10 digits from `normalize_phone_number` match `PHONE_NUMBER_PATTERN`."""
    return re.match(PHONE_NUMBER_PATTERN, digits) is not None
