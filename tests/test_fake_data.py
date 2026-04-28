"""Unit tests for the BankingBuddy fake in-memory data layer."""

import copy

import pytest

from bankingbuddy import fake_data
from bankingbuddy.fake_data import (
    CARDS,
    CUSTOMERS,
    Card,
    create_replacement_card,
    find_card_by_last_four,
    get_cards_for_customer,
    get_customer,
    update_card_status,
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


# ── Customer lookup ───────────────────────────────────────────────────────


def test_get_customer_found():
    customer = get_customer("617823490")
    assert customer is not None
    assert customer["customer_id"] == "617823490"
    assert customer["name"] == "Rajesh Kumar"
    assert "email" in customer
    assert "phone" in customer
    assert "aadhaar" in customer
    assert "pan" in customer


def test_get_customer_not_found():
    assert get_customer("C-99999") is None


# ── Card queries ──────────────────────────────────────────────────────────


def test_get_cards_for_customer():
    cards = get_cards_for_customer("617823490")
    assert isinstance(cards, list)
    assert 2 <= len(cards) <= 3
    for card in cards:
        assert card["customer_id"] == "617823490"


def test_find_card_by_last_four():
    card = find_card_by_last_four("1111", "617823490")
    assert card is not None
    assert card["card_id"] == "CARD-001"
    assert card["last_four"] == "1111"


# ── Card mutations ────────────────────────────────────────────────────────


def test_update_card_status():
    updated = update_card_status("CARD-001", "blocked")
    assert updated is not None
    assert updated["status"] == "blocked"
    # Verify the in-memory store is also updated
    assert get_cards_for_customer("617823490")[0]["status"] == "blocked"


def test_create_replacement_card():
    new_card = create_replacement_card("617823490", "debit")
    assert new_card["customer_id"] == "617823490"
    assert new_card["card_type"] == "debit"
    assert new_card["status"] == "active"
    assert len(new_card["last_four"]) == 4
    # The new card_id must not collide with any existing seed card ID
    seed_ids = {f"CARD-{i:03d}" for i in range(1, 14)}
    assert new_card["card_id"] not in seed_ids
    # The card should now appear in the customer's list
    cards = get_cards_for_customer("617823490")
    assert any(c["card_id"] == new_card["card_id"] for c in cards)
