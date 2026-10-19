from rest_framework import status
from rest_framework.exceptions import APIException


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state."
    default_code = "conflict"


def violates(error, *constraints):
    """True when the database raised `error` for one of the constraints named."""
    diag = getattr(error.__cause__, "diag", None)
    return diag is not None and diag.constraint_name in constraints
