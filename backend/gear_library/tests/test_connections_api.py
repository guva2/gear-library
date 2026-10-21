import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from gear_library.models import Connection, ordered_pair

User = get_user_model()

CONNECTIONS_URL = "/api/connections/"
REQUESTS_URL = "/api/connections/requests/"


def make_user(n, first_name, last_name):
    return User.objects.create_user(
        phone_number=f"555223{n:04d}", first_name=first_name, last_name=last_name
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def add(requested_by, other, status="pending"):
    first, second = ordered_pair(requested_by, other)
    return Connection.objects.create(
        first_user_id=first, second_user_id=second, requested_by=requested_by, status=status
    )


def connected(connection, user):
    return {
        "id": connection.id,
        "status": "accepted",
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number,
        },
    }


def received(connection, user):
    return {
        "id": connection.id,
        "status": "pending",
        "user": {"first_name": user.first_name, "last_name": user.last_name},
    }


def sent(connection, user):
    return {
        "id": connection.id,
        "status": "pending",
        "user": {"phone_number": user.phone_number},
    }


def action_url(connection, action):
    return f"{CONNECTIONS_URL}{connection.id}/{action}/"


@pytest.fixture
def people():
    """Ada is connected to Zoe and Bob, has a request from Cy and a request to Dee.
    Stan is connected to nobody."""
    ada, bob, cy, dee, zoe, stan = (
        make_user(n, first, last)
        for n, (first, last) in enumerate(
            [
                ("Ada", "Lovelace"),
                ("Bob", "Stone"),
                ("Cy", "Young"),
                ("Dee", "Ford"),
                ("Zoe", "Adams"),
                ("Stan", "Gray"),
            ],
            1,
        )
    )
    return {
        "ada": ada,
        "bob": bob,
        "cy": cy,
        "dee": dee,
        "zoe": zoe,
        "stan": stan,
        "with_bob": add(bob, ada, "accepted"),
        "with_zoe": add(ada, zoe, "accepted"),
        "from_cy": add(cy, ada),
        "to_dee": add(ada, dee),
    }


@pytest.mark.django_db
class TestAnonymous:
    @pytest.mark.parametrize(
        "method, url",
        [
            ("get", CONNECTIONS_URL),
            ("post", CONNECTIONS_URL),
            ("get", REQUESTS_URL),
            ("post", "/api/connections/1/accept/"),
            ("post", "/api/connections/1/decline/"),
            ("post", "/api/connections/1/cancel/"),
            ("delete", "/api/connections/1/"),
        ],
    )
    def test_is_forbidden(self, method, url):
        assert getattr(APIClient(), method)(url, {}, format="json").status_code == 403


@pytest.mark.django_db
class TestLists:
    def test_connections_show_the_other_users_name_and_number_sorted_by_name(self, people):
        response = client_for(people["ada"]).get(CONNECTIONS_URL)

        assert response.status_code == 200
        assert response.json() == [
            connected(people["with_zoe"], people["zoe"]),
            connected(people["with_bob"], people["bob"]),
        ]

    def test_a_connection_works_both_ways(self, people):
        response = client_for(people["bob"]).get(CONNECTIONS_URL)

        assert response.json() == [connected(people["with_bob"], people["ada"])]

    def test_received_requests_show_the_name_and_sent_requests_the_number(self, people):
        response = client_for(people["ada"]).get(REQUESTS_URL)

        assert response.status_code == 200
        assert response.json() == {
            "received": [received(people["from_cy"], people["cy"])],
            "sent": [sent(people["to_dee"], people["dee"])],
        }
        assert people["cy"].phone_number not in str(response.json())

    def test_a_sent_request_carries_no_name_or_user_id(self, people):
        response = client_for(people["ada"]).get(REQUESTS_URL)

        (request,) = response.json()["sent"]
        assert request["user"] == {"phone_number": people["dee"].phone_number}

    def test_the_other_side_sees_the_request_the_other_way(self, people):
        response = client_for(people["dee"]).get(REQUESTS_URL)

        assert response.json() == {
            "received": [received(people["to_dee"], people["ada"])],
            "sent": [],
        }

    def test_requests_are_oldest_first(self, people):
        later = add(people["stan"], people["ada"])

        received = client_for(people["ada"]).get(REQUESTS_URL).json()["received"]

        assert [r["id"] for r in received] == [people["from_cy"].id, later.id]

    def test_someone_else_sees_none_of_them(self, people):
        client = client_for(people["stan"])

        assert client.get(CONNECTIONS_URL).json() == []
        assert client.get(REQUESTS_URL).json() == {"received": [], "sent": []}


@pytest.mark.django_db
class TestRequest:
    def send(self, user, phone_number):
        return client_for(user).post(
            CONNECTIONS_URL, {"phone_number": phone_number}, format="json"
        )

    def test_sends_a_request_by_a_formatted_phone_number(self, people):
        response = self.send(people["stan"], "(555) 223-0001")

        assert response.status_code == 201
        row = Connection.objects.get(requested_by=people["stan"])
        assert response.json() == sent(row, people["ada"])
        assert response.json()["user"] == {"phone_number": people["ada"].phone_number}

    def test_a_request_to_someone_whose_request_is_pending_connects_at_once(self, people):
        response = self.send(people["ada"], people["cy"].phone_number)

        assert response.status_code == 200
        assert response.json() == connected(people["from_cy"], people["cy"])
        assert Connection.objects.get(pk=people["from_cy"].pk).status == "accepted"

    @pytest.mark.parametrize(
        "phone_number, message",
        [
            ("555", "Enter a 10-digit US phone number."),
            (
                "5551999999",
                "Enter a valid US phone number: the area code and the 3 digits after it "
                "cannot start with 0 or 1.",
            ),
            ("", "This field may not be blank."),
            ("5559999999", "No user has this phone number."),
            ("5552230001", "You cannot send a request to yourself."),
        ],
    )
    def test_rejects_an_invalid_unknown_or_own_phone_number(self, people, phone_number, message):
        response = self.send(people["ada"], phone_number)

        assert response.status_code == 400
        assert response.json() == {"phone_number": [message]}

    @pytest.mark.parametrize(
        "other, message",
        [
            ("bob", "You are already connected."),
            ("zoe", "You are already connected."),
            ("dee", "You have already sent this user a request."),
        ],
    )
    def test_an_existing_connection_or_request_conflicts(self, people, other, message):
        before = set(Connection.objects.values_list("pk", "status"))

        response = self.send(people["ada"], people[other].phone_number)

        assert response.status_code == 409
        assert response.json() == {"detail": message}
        assert set(Connection.objects.values_list("pk", "status")) == before


@pytest.mark.django_db
class TestActions:
    def post(self, user, connection, action):
        return client_for(user).post(action_url(connection, action))

    def test_accepting_returns_the_connection(self, people):
        response = self.post(people["ada"], people["from_cy"], "accept")

        assert response.status_code == 200
        assert response.json() == connected(people["from_cy"], people["cy"])
        listed = client_for(people["cy"]).get(CONNECTIONS_URL).json()
        assert connected(people["from_cy"], people["ada"]) in listed

    def test_declining_deletes_the_request(self, people):
        response = self.post(people["ada"], people["from_cy"], "decline")

        assert response.status_code == 204
        assert not Connection.objects.filter(pk=people["from_cy"].pk).exists()

    def test_cancelling_deletes_the_request(self, people):
        response = self.post(people["ada"], people["to_dee"], "cancel")

        assert response.status_code == 204
        assert not Connection.objects.filter(pk=people["to_dee"].pk).exists()

    @pytest.mark.parametrize("by", ["ada", "bob"])
    def test_either_user_removes_a_connection(self, people, by):
        response = client_for(people[by]).delete(f"{CONNECTIONS_URL}{people['with_bob'].id}/")

        assert response.status_code == 204
        assert not Connection.objects.filter(pk=people["with_bob"].pk).exists()

    @pytest.mark.parametrize(
        "by, connection, action",
        [
            ("ada", "to_dee", "accept"),
            ("ada", "to_dee", "decline"),
            ("ada", "from_cy", "cancel"),
        ],
    )
    def test_the_wrong_one_of_the_two_is_forbidden(self, people, by, connection, action):
        response = self.post(people[by], people[connection], action)

        assert response.status_code == 403
        assert Connection.objects.get(pk=people[connection].pk).status == "pending"

    @pytest.mark.parametrize("by, action", [("ada", "decline"), ("bob", "cancel")])
    def test_answering_an_accepted_connection_conflicts(self, people, by, action):
        response = self.post(people[by], people["with_bob"], action)

        assert response.status_code == 409
        assert response.json() == {"detail": "This is not a pending request."}

    def test_accepting_an_accepted_connection_returns_it(self, people):
        response = self.post(people["ada"], people["with_bob"], "accept")

        assert response.status_code == 200
        assert response.json() == connected(people["with_bob"], people["bob"])

    def test_the_requester_cannot_accept_an_accepted_connection(self, people):
        response = self.post(people["bob"], people["with_bob"], "accept")

        assert response.status_code == 403

    def test_removing_a_pending_request_conflicts(self, people):
        response = client_for(people["ada"]).delete(f"{CONNECTIONS_URL}{people['to_dee'].id}/")

        assert response.status_code == 409
        assert response.json() == {"detail": "You are not connected."}

    def test_answering_a_cancelled_request_is_not_found(self, people):
        self.post(people["ada"], people["to_dee"], "cancel")

        response = self.post(people["dee"], people["to_dee"], "accept")

        assert response.status_code == 404
        assert response.json() == {"detail": "Connection not found."}

    @pytest.mark.parametrize("connection", ["with_bob", "from_cy", "to_dee"])
    def test_anyone_else_gets_not_found(self, people, connection):
        client = client_for(people["stan"])
        target = people[connection]

        responses = [
            client.post(action_url(target, action)) for action in ["accept", "decline", "cancel"]
        ]
        responses.append(client.delete(f"{CONNECTIONS_URL}{target.id}/"))

        assert [r.status_code for r in responses] == [404] * 4
        assert Connection.objects.filter(pk=target.pk).exists()

    def test_an_unknown_connection_is_not_found(self, people):
        response = client_for(people["ada"]).delete(f"{CONNECTIONS_URL}999999/")

        assert response.status_code == 404


@pytest.mark.django_db
def test_unsafe_requests_need_the_csrf_token(people):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(people["stan"])

    response = client.post(CONNECTIONS_URL, {"phone_number": "5552230001"}, format="json")

    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    assert not Connection.objects.filter(requested_by=people["stan"]).exists()
