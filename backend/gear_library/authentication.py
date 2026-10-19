from rest_framework.authentication import SessionAuthentication


class CsrfSessionAuthentication(SessionAuthentication):
    """Session authentication that also checks CSRF for anonymous callers.

    `SessionAuthentication` checks CSRF only once a session user is found, and DRF views
    are exempt from `CsrfViewMiddleware`, so without this an anonymous POST is unchecked.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            self.enforce_csrf(request)
        return result
