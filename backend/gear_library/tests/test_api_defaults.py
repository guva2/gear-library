import base64

import pytest
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from gear_library.models import User


class DefaultsView(APIView):
    def get(self, request):
        return Response({"ok": True})


def test_anonymous_request_is_refused():
    request = APIRequestFactory().get("/")

    response = DefaultsView.as_view()(request)

    assert response.status_code == 403


@pytest.mark.django_db
def test_basic_auth_credentials_do_not_authenticate():
    User.objects.create_user(phone_number="5551234567", password="s3cret-pass")
    credentials = base64.b64encode(b"5551234567:s3cret-pass").decode()
    request = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Basic {credentials}")

    response = DefaultsView.as_view()(request)

    assert response.status_code == 403
