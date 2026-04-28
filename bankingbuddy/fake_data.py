"""
Fake in-memory customer and card database for BankingBuddy — a Contoso Bank AI
assistant demo.  All data is synthetic and stored in module-level lists so it
can be mutated during a single process lifetime without any external
dependencies.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Customer:
    customer_id: str
    name: str
    email: str
    phone: str
    aadhaar: str
    pan: str


@dataclass
class Card:
    card_id: str
    customer_id: str
    card_type: str          # "debit" | "credit"
    card_number: str        # full 16-digit card number
    status: str             # "active" | "blocked" | "lost" | "expired"
    expiry: str             # MM/YY
    daily_limit: int        # in rupees

    @property
    def last_four(self) -> str:
        return self.card_number.replace(" ", "")[-4:]


# ---------------------------------------------------------------------------
# Seed data — customers
# ---------------------------------------------------------------------------

CUSTOMERS: List[Customer] = [
    Customer(
        customer_id="617823490",
        name="Rajesh Kumar",
        email="rajesh.kumar@contoso.com",
        phone="+91 9845012345",
        aadhaar="2345 6789 0123",
        pan="ABCPK1234F",
    ),
    Customer(
        customer_id="528194073",
        name="Priya Sharma",
        email="priya.sharma@contoso.com",
        phone="+91 9876543210",
        aadhaar="3456 7890 1234",
        pan="DEFPS5678G",
    ),
    Customer(
        customer_id="439065182",
        name="Amit Patel",
        email="amit.patel@contoso.com",
        phone="+91 8765432109",
        aadhaar="4567 8901 2345",
        pan="GHIAP9012H",
    ),
    Customer(
        customer_id="350976214",
        name="Sneha Reddy",
        email="sneha.reddy@contoso.com",
        phone="+91 7654321098",
        aadhaar="5678 9012 3456",
        pan="JKLSR3456J",
    ),
    Customer(
        customer_id="261847305",
        name="Vikram Singh",
        email="vikram.singh@contoso.com",
        phone="+91 6543210987",
        aadhaar="6789 0123 4567",
        pan="MNQVS7890K",
    ),
]

# ---------------------------------------------------------------------------
# Seed data — cards (2-3 per customer, mixed statuses)
# ---------------------------------------------------------------------------

CARDS: List[Card] = [
    # --- Rajesh Kumar (617823490) ---
    Card("CARD-001", "617823490", "debit",  "4111 1111 1111 1111", "active",  "09/27", 50_000),
    Card("CARD-002", "617823490", "credit", "5555 5555 5555 4444", "blocked", "03/26", 200_000),

    # --- Priya Sharma (528194073) ---
    Card("CARD-003", "528194073", "debit",  "4012 8888 8888 1881", "active",  "11/28", 40_000),
    Card("CARD-004", "528194073", "credit", "5105 1051 0510 5100", "active",  "06/27", 150_000),
    Card("CARD-005", "528194073", "debit",  "4917 4845 8989 7107", "lost",    "01/26", 40_000),

    # --- Amit Patel (439065182) ---
    Card("CARD-006", "439065182", "credit", "3530 1113 3330 0000", "active",  "12/27", 300_000),
    Card("CARD-007", "439065182", "debit",  "4000 0566 5566 5556", "blocked", "08/26", 60_000),

    # --- Sneha Reddy (350976214) ---
    Card("CARD-008", "350976214", "debit",  "6011 1111 1111 1117", "active",  "04/28", 50_000),
    Card("CARD-009", "350976214", "credit", "3566 0020 2036 0505", "expired", "02/24", 250_000),
    Card("CARD-010", "350976214", "debit",  "6011 0009 9013 9424", "active",  "10/27", 50_000),

    # --- Vikram Singh (261847305) ---
    Card("CARD-011", "261847305", "debit",  "3782 8224 6310 005",  "active",  "05/28", 75_000),
    Card("CARD-012", "261847305", "credit", "3714 4963 5398 431",  "active",  "07/27", 500_000),
    Card("CARD-013", "261847305", "debit",  "3056 9309 0259 04",   "active",  "09/26", 75_000),
]

# Auto-incrementing counter for new card IDs
_next_card_seq: int = 14

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _card_to_dict(card: Card) -> dict:
    """Convert a Card dataclass to a dict, including the derived last_four."""
    d = asdict(card)
    d["last_four"] = card.last_four
    return d


def get_customer(customer_id: str) -> Optional[dict]:
    """Return a customer dict by ID, or ``None`` if not found."""
    for c in CUSTOMERS:
        if c.customer_id == customer_id:
            return asdict(c)
    return None


def get_cards_for_customer(customer_id: str) -> list[dict]:
    """Return all cards belonging to *customer_id* (may be empty)."""
    return [_card_to_dict(card) for card in CARDS if card.customer_id == customer_id]


def get_card(card_id: str) -> Optional[dict]:
    """Return a single card dict by its card ID, or ``None``."""
    for card in CARDS:
        if card.card_id == card_id:
            return _card_to_dict(card)
    return None


def find_card_by_last_four(last_four: str, customer_id: str) -> Optional[dict]:
    """Find a card by its last four digits scoped to a customer."""
    clean = last_four.strip(".")
    for card in CARDS:
        if card.last_four == clean and card.customer_id == customer_id:
            return _card_to_dict(card)
    return None


def find_card_by_number(card_number: str, customer_id: str) -> Optional[dict]:
    """Find a card by its full card number scoped to a customer."""
    clean = card_number.replace(" ", "").replace("-", "").strip(".")
    for card in CARDS:
        if card.card_number.replace(" ", "") == clean and card.customer_id == customer_id:
            return _card_to_dict(card)
    return None


def verify_customer_identity(
    customer_id: str,
    *,
    aadhaar: str | None = None,
    email: str | None = None,
    card_number: str | None = None,
) -> dict:
    """Verify a customer's identity using one or more credentials.

    Returns a dict with ``verified`` (bool) and ``details`` (str).
    At least one of aadhaar, email, or card_number must be provided.
    """
    customer = get_customer(customer_id)
    if customer is None:
        return {"verified": False, "details": "Customer not found."}

    if not any([aadhaar, email, card_number]):
        return {"verified": False, "details": "No identity credentials provided."}

    matched: list[str] = []
    failed: list[str] = []

    if aadhaar is not None:
        clean = aadhaar.replace(" ", "").strip(".")
        if customer["aadhaar"].replace(" ", "") == clean:
            matched.append("Aadhaar")
        else:
            failed.append("Aadhaar")

    if email is not None:
        clean = email.strip().strip(".").lower()
        if customer["email"].lower() == clean:
            matched.append("Email")
        else:
            failed.append("Email")

    if card_number is not None:
        card = find_card_by_number(card_number, customer_id)
        if card is not None:
            matched.append(f"Card (ending {card['last_four']})")
        else:
            failed.append("Card number")

    if failed:
        return {
            "verified": False,
            "details": f"Verification failed for: {', '.join(failed)}.",
        }

    return {
        "verified": True,
        "details": f"Identity verified via: {', '.join(matched)}.",
        "customer_name": customer["name"],
    }


def update_card_status(card_id: str, new_status: str) -> Optional[dict]:
    """
    Update the status of an existing card (e.g. "active", "blocked", "lost").
    Returns the updated card dict, or ``None`` if the card was not found.
    """
    for card in CARDS:
        if card.card_id == card_id:
            card.status = new_status
            return _card_to_dict(card)
    return None


def create_replacement_card(customer_id: str, card_type: str) -> dict:
    """
    Create a brand-new card for *customer_id* with status ``"active"`` and
    append it to the in-memory card list.  Returns the new card as a dict.
    """
    global _next_card_seq
    new_id = f"CARD-{_next_card_seq:03d}"
    _next_card_seq += 1

    import random
    prefix = "4532" if card_type == "debit" else "5214"
    middle = f"{random.randint(1000,9999)} {random.randint(1000,9999)}"
    last = f"{random.randint(1000, 9999)}"
    card_number = f"{prefix} {middle} {last}"

    new_card = Card(
        card_id=new_id,
        customer_id=customer_id,
        card_type=card_type,
        card_number=card_number,
        status="active",
        expiry="12/29",
        daily_limit=50_000 if card_type == "debit" else 200_000,
    )
    CARDS.append(new_card)
    return _card_to_dict(new_card)
