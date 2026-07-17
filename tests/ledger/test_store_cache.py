"""Regression tests for review finding #5: reset_ledger_store() must clear
the path-keyed store cache after the singleton -> dict refactor."""

from cre_mcp.ledger import store as store_mod
from cre_mcp.ledger.store import get_ledger_store, reset_ledger_store


def test_get_ledger_store_is_cached_by_path():
    reset_ledger_store()
    first = get_ledger_store()
    second = get_ledger_store()
    assert first is second


def test_reset_ledger_store_clears_the_cache():
    get_ledger_store()
    assert store_mod._STORES  # populated
    reset_ledger_store()
    assert store_mod._STORES == {}


def test_store_is_rebuilt_after_reset():
    first = get_ledger_store()
    reset_ledger_store()
    second = get_ledger_store()
    assert first is not second
