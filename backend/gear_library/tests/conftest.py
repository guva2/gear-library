import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Throttle counts live in the cache, so each test starts with none."""
    cache.clear()
