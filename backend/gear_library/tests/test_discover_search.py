import pytest
from rest_framework.test import APIClient
from django.db import connection

from gear_library.models import Item, Membership

from .test_discover_lending_api import get, query_count
from .test_items_api import list_in, make_inventory, make_user
from .test_loans_api import set_loan

URL = "/api/discover/"


@pytest.fixture
def people():
    """Climbing: Olive owns it, Mia is a member. Camping: Olive owns it, Mia is an admin.
    Stan has a pending invite to Climbing."""
    olive, mia, stan = (make_user(n, name) for n, name in enumerate(["Olive", "Mia", "Stan"], 1))
    climbing = make_inventory("Climbing", [(olive, "owner"), (mia, "member")])
    camping = make_inventory("Camping", [(olive, "owner"), (mia, "admin")])
    Membership.objects.create(inventory=climbing, user=stan, role="member", status="pending")
    return {"olive": olive, "mia": mia, "stan": stan, "climbing": climbing, "camping": camping}


@pytest.fixture
def gear(people):
    """Olive's items, listed in Climbing, by name."""
    described = {
        "Sleeping bag": "Down, rated to -5 C",
        "Kids sleeping bag": "",
        "Climbing harness": "Size M",
        "Hammock": "With straps",
        "Two-person tent": "Three-season",
        "Footprint": "Ground sheet for the tent",
        "Map case": "Trail maps for the state parks",
    }
    made = {}
    for name, description in described.items():
        made[name] = Item.objects.create(owner=people["olive"], name=name, description=description)
        list_in(people["climbing"], made[name])
    return made


def search(people, q):
    return [i["name"] for i in get(people["mia"], f"{URL}?q={q}")]


@pytest.mark.django_db
def test_every_connection_uses_a_word_similarity_threshold_of_one_half():
    with connection.cursor() as cursor:
        cursor.execute("SHOW pg_trgm.word_similarity_threshold")
        assert cursor.fetchone() == ("0.5",)


@pytest.mark.django_db
def test_the_search_filter_can_use_both_trigram_indexes():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")

    plan = Item.objects.matching("tent").explain()

    assert "gear_library_item_name_trgm" in plan
    assert "gear_library_item_desc_trgm" in plan


@pytest.mark.django_db
class TestSearch:
    def test_a_partial_word_matches(self, people, gear):
        assert search(people, "sleep") == ["Sleeping bag", "Kids sleeping bag"]

    @pytest.mark.parametrize(
        ("q", "name"), [("climing", "Climbing harness"), ("hamock", "Hammock")]
    )
    def test_a_dropped_letter_matches(self, people, gear, q, name):
        assert search(people, q) == [name]

    def test_swapped_letters_match_nothing(self, people, gear):
        assert search(people, "tnet") == []

    def test_a_description_match_comes_after_name_matches(self, people, gear):
        assert search(people, "tent") == ["Two-person tent", "Footprint"]

    def test_a_weak_name_match_comes_before_a_perfect_description_match(self, people, gear):
        # word_similarity("climing", "Climbing harness") is about 0.55; the description
        # "Climing tips" scores 1.0.
        list_in(
            people["climbing"],
            Item.objects.create(owner=people["olive"], name="Rope", description="Climing tips"),
        )

        assert search(people, "climing") == ["Climbing harness", "Rope"]

    def test_description_matches_are_ordered_by_description_score(self, people, gear):
        # For "stove", "Stakes" scores 0.33 on its name: below the name threshold, so only
        # the descriptions (0.83 and 1.0) order the two.
        for name, description in [("Stakes", "Gas stoves"), ("Mug", "A stove")]:
            list_in(
                people["climbing"],
                Item.objects.create(owner=people["olive"], name=name, description=description),
            )

        assert search(people, "stove") == ["Mug", "Stakes"]

    def test_a_weak_description_match_is_left_out(self, people, gear):
        # word_similarity("pad", "... parks") is 0.5: enough for a name, not a description.
        assert search(people, "pad") == []

    def test_whole_name_similarity_breaks_a_tie(self, people, gear):
        assert search(people, "sleping bag") == ["Sleeping bag", "Kids sleeping bag"]

    def test_available_items_still_come_first(self, people, gear):
        set_loan(gear["Two-person tent"], "on_loan", people["stan"], people["climbing"])

        assert search(people, "tent") == ["Footprint", "Two-person tent"]

    def test_never_returns_items_discover_leaves_out(self, people, gear):
        list_in(people["climbing"], Item.objects.create(owner=people["mia"], name="Tent pegs"))
        list_in(people["camping"], Item.objects.create(owner=people["olive"], name="Tent poles"))

        assert search(people, "tent") == ["Two-person tent", "Footprint"]
        assert get(people["stan"], f"{URL}?q=tent") == []

    @pytest.mark.parametrize(
        ("q", "names"),
        [("%25%25", []), ("_%25", []), ("%25tent_", ["Two-person tent", "Footprint"])],
    )
    def test_like_wildcards_have_no_special_meaning(self, people, gear, q, names):
        assert search(people, q) == names

    @pytest.mark.parametrize("q", ["", "t", "%20%20", "%20s%20"])
    def test_a_query_shorter_than_two_characters_returns_the_full_list(self, people, gear, q):
        assert search(people, q) == sorted(gear)

    def test_a_search_takes_as_many_queries_as_the_full_list(self, people, gear):
        assert query_count(people["mia"], f"{URL}?q=tent") == query_count(people["mia"], URL)

    @pytest.mark.parametrize("q", ["%00ab", "ab%00", "te%00nt"])
    def test_a_query_with_a_nul_character_is_rejected(self, people, gear, q):
        client = APIClient()
        client.force_authenticate(people["mia"])

        response = client.get(f"{URL}?q={q}")

        assert response.status_code == 400
        assert list(response.json()) == ["q"]
