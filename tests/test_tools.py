"""Unit tests for the BankingBuddy tool functions.

The tool functions are thin wrappers around *fake_data* that return
human-readable strings.  We call the underlying callable directly
(bypassing the ``@tool`` decorator metadata) so no agent runtime is needed.

Skipped entirely when ``agent_framework`` is not installed.
"""

import copy
import importlib
import sys

import pytest

# Skip the entire module if agent_framework is not installed
# (bankingbuddy.tools imports from agent_framework at module level).
if not importlib.util.find_spec("agent_framework"):
    pytest.skip("agent_framework is not installed", allow_module_level=True)

from bankingbuddy import fake_data  # noqa: E402
from bankingbuddy.fake_data import CARDS  # noqa: E402
from bankingbuddy.tools import (  # noqa: E402
    get_customer_info,
    get_card_status,
    list_customer_cards,
    order_new_card,
    report_lost_card,
    unblock_card,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_data():
    """Restore seed data after every test so mutations don't leak."""
    original_cards = copy.deepcopy(CARDS)
    original_seq = fake_data._next_card_seq
    yield
    CARDS.clear()
    CARDS.extend(original_cards)
    fake_data._next_card_seq = original_seq


# ── Helpers ───────────────────────────────────────────────────────────────


def _call(tool_fn, **kwargs) -> str:
    """Call a tool function, unwrapping the @tool decorator if needed."""
    # If the decorator exposes the original via __wrapped__ or similar,
    # prefer that; otherwise just call directly.
    fn = getattr(tool_fn, "__wrapped__", tool_fn)
    return fn(**kwargs)


# ── get_customer_info ─────────────────────────────────────────────────────


def test_get_customer_info_found():
    result = _call(get_customer_info, customer_id="617823490")
    assert "Rajesh Kumar" in result
    assert "Email" in result or "email" in result.lower()


def test_get_customer_info_not_found():
    result = _call(get_customer_info, customer_id="C-99999")
    assert "not found" in result.lower()


# ── list_customer_cards ───────────────────────────────────────────────────


def test_list_customer_cards():
    result = _call(list_customer_cards, customer_id="617823490")
    assert "CARD-001" in result
    assert "CARD-002" in result


# ── unblock_card ──────────────────────────────────────────────────────────


def test_unblock_card_success():
    # CARD-002 starts as "blocked" in seed data
    result = _call(unblock_card, card_id="CARD-002", reason="customer request")
    assert "unblocked" in result.lower()
    # Verify the card is now active
    card = fake_data.get_card("CARD-002")
    assert card["status"] == "active"


def test_unblock_card_not_blocked():
    # CARD-001 starts as "active"
    result = _call(unblock_card, card_id="CARD-001", reason="test")
    assert "cannot unblock" in result.lower() or "status" in result.lower()


# ── report_lost_card ─────────────────────────────────────────────────────


def test_report_lost_card():
    result = _call(
        report_lost_card,
        card_id="CARD-001",
        last_seen_location="Mumbai airport",
    )
    assert "lost" in result.lower()
    assert "Mumbai airport" in result
    card = fake_data.get_card("CARD-001")
    assert card["status"] == "lost"


# ── order_new_card ────────────────────────────────────────────────────────


def test_order_new_card():
    result = _call(order_new_card, customer_id="617823490", card_type="debit")
    assert "ordered" in result.lower() or "success" in result.lower()
    assert "CARD-" in result
