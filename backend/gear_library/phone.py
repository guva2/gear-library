import re

_SEPARATORS = re.compile(r"[ .()\-]")
# [0-9], not \d: Python's \d matches any Unicode digit, not only ASCII 0-9.
_US_NUMBER = re.compile(r"(?:\+?1)?([0-9]{10})")


def normalize_phone_number(value):
    """Return the 10 digits of a US phone number, or None if `value` is not one.

    Accepts spaces, dots, dashes and parentheses anywhere, and an optional leading `1` or
    `+1` country code.
    """
    match = _US_NUMBER.fullmatch(_SEPARATORS.sub("", value))
    return match.group(1) if match else None
