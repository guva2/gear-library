import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE_PLAN = [("gear_library", "0008_item_search")]
BEFORE = [("gear_library", "0009_user_phone_number_numbering_plan")]
AFTER = [("gear_library", "0010_user_names_not_blank")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture(autouse=True)
def restore_latest_schema():
    """The other tests need the schema every migration builds."""
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_names_not_blank_backfills_blank_names_and_keeps_the_others():
    old_apps = migrate(BEFORE)
    User = old_apps.get_model("gear_library", "User")
    User.objects.create(phone_number="5552230001", password="x", first_name="", last_name="")
    User.objects.create(phone_number="5552230002", password="x", first_name="Ada", last_name=" ")
    User.objects.create(
        phone_number="5552230003", password="x", first_name="Grace", last_name="Hopper"
    )

    new_apps = migrate(AFTER)

    User = new_apps.get_model("gear_library", "User")
    names = dict(User.objects.values_list("phone_number", "first_name"))
    last_names = dict(User.objects.values_list("phone_number", "last_name"))
    assert names == {"5552230001": "Unknown", "5552230002": "Ada", "5552230003": "Grace"}
    assert last_names == {
        "5552230001": "Unknown",
        "5552230002": "Unknown",
        "5552230003": "Hopper",
    }


@pytest.mark.django_db(transaction=True)
def test_numbering_plan_names_every_number_that_breaks_it_and_changes_nothing():
    old_apps = migrate(BEFORE_PLAN)
    User = old_apps.get_model("gear_library", "User")
    for number in ("5552230001", "1552230002", "5551230003"):
        User.objects.create(phone_number=number, password="x", first_name="A", last_name="B")

    with pytest.raises(RuntimeError) as refused:
        migrate(BEFORE)

    message = str(refused.value)
    assert "1552230002, 5551230003" in message
    assert "5552230001" not in message
    User = MigrationExecutor(connection).loader.project_state(BEFORE_PLAN).apps.get_model(
        "gear_library", "User"
    )
    assert set(User.objects.values_list("phone_number", flat=True)) == {
        "5552230001",
        "1552230002",
        "5551230003",
    }
    User.objects.all().delete()


@pytest.mark.django_db(transaction=True)
def test_numbering_plan_migrates_when_every_number_follows_it():
    old_apps = migrate(BEFORE_PLAN)
    User = old_apps.get_model("gear_library", "User")
    User.objects.create(phone_number="5552230001", password="x", first_name="A", last_name="B")

    migrate(BEFORE)
