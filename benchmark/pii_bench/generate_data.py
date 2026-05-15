"""Synthetic banking-chat data generator.

* Deterministic — fully driven by ``--seed``.
* No real PII — uses UIDAI-reserved Aadhaar prefixes, public test card
  numbers, and ``@example.com`` email addresses. See ``data/README.md``.
* Three length buckets (short / med / long) and three density buckets
  (low / med / high entity counts) to expose the cost model rather than
  hide it inside an aggregated mean.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

# --- Pools (no real PII; deliberately synthetic) ---------------------------

NAMES: tuple[str, ...] = (
    "Rajesh Kumar", "Priya Sharma", "Amit Patel", "Sneha Iyer", "Vikram Reddy",
    "Anjali Menon", "Karthik Rao", "Divya Nair", "Rohan Joshi", "Meera Gupta",
    "John Smith", "Emily Brown", "Liam Wilson", "Olivia Garcia", "Noah Johnson",
    "Ava Martinez", "Lucas Davis", "Sophia Hernandez", "Mason Lopez", "Isabella Lee",
)

# Public test card numbers; never linked to a real account.
TEST_CARDS: tuple[str, ...] = (
    "4111 1111 1111 1111",  # Visa test
    "5555 5555 5555 4444",  # Mastercard test
    "3782 822463 10005",    # Amex test
    "6011 1111 1111 1117",  # Discover test
    "5105 1051 0510 5100",  # Mastercard test (alt)
)

EMAIL_DOMAINS: tuple[str, ...] = ("example.com", "contoso.com", "example.org")

# --- Templates -------------------------------------------------------------

# Each template lists the entity placeholders it consumes; counts feed
# the density bucket calculation.
@dataclass(frozen=True)
class Template:
    scenario: str
    text: str
    entity_keys: tuple[str, ...]


TEMPLATES_SHORT: tuple[Template, ...] = (
    Template("unblock_card",
             "My card {CARD} is blocked. Customer ID: {CID}. I'm {NAME}.",
             ("CARD", "CID", "NAME")),
    Template("report_lost",
             "I lost my card. Name: {NAME}. Customer ID {CID}. Card number {CARD}.",
             ("NAME", "CID", "CARD")),
    Template("order_new",
             "Need a new debit card. Customer ID {CID}, name {NAME}, email {EMAIL}.",
             ("CID", "NAME", "EMAIL")),
)

# Medium templates also include Aadhaar / PAN / phone for higher density.
TEMPLATES_MED: tuple[Template, ...] = (
    Template(
        "unblock_card",
        "Hi BankingBuddy, this is {NAME} (customer {CID}). My credit card "
        "{CARD} got blocked yesterday after a few declined transactions. "
        "Could you reactivate it? You can verify me on Aadhaar {AADHAAR} "
        "or my registered email {EMAIL}.",
        ("NAME", "CID", "CARD", "AADHAAR", "EMAIL"),
    ),
    Template(
        "report_lost",
        "I'm {NAME}, customer {CID}. I think I left my wallet in a cab last "
        "night and my card {CARD} is missing. Please mark it lost and order "
        "a replacement to my email on file ({EMAIL}). My phone is {PHONE} "
        "if you need to call. PAN: {PAN}.",
        ("NAME", "CID", "CARD", "EMAIL", "PHONE", "PAN"),
    ),
    Template(
        "order_new",
        "Hello, this is {NAME} (CID {CID}). I'd like to order a new debit "
        "card. Existing card on file is {CARD}, email {EMAIL}, phone "
        "{PHONE}. Verify with Aadhaar {AADHAAR} if needed.",
        ("NAME", "CID", "CARD", "EMAIL", "PHONE", "AADHAAR"),
    ),
)

# Long templates simulate copy-pasted complaint emails forwarded into chat:
# multiple paragraphs, repeated PII, plus filler.
TEMPLATES_LONG: tuple[Template, ...] = (
    Template(
        "report_lost",
        "Subject: Lost card — urgent\n\n"
        "Hi team,\n\n"
        "I'm writing to report that my card {CARD} (registered to {NAME}, "
        "customer ID {CID}) has been lost since last evening. I last used it "
        "at a restaurant and only realised it was missing this morning when "
        "I tried to pay for breakfast.\n\n"
        "For verification, my Aadhaar is {AADHAAR}, my PAN is {PAN}, and my "
        "registered email and phone are {EMAIL} and {PHONE} respectively. "
        "Please mark the card as lost immediately and dispatch a replacement "
        "to the address you have on file.\n\n"
        "I have already temporarily blocked outgoing payments via the mobile "
        "app but I want to make sure no further transactions go through. "
        "Customer ID for cross-reference: {CID}. Card last four: {CARD}. "
        "Name on card: {NAME}.\n\n"
        "Please confirm receipt and the replacement card timeline. "
        "Thanks, {NAME}.",
        ("CARD", "NAME", "CID", "AADHAAR", "PAN", "EMAIL", "PHONE",
         "CID", "CARD", "NAME", "NAME"),
    ),
)


# --- Random fake-PII generators -------------------------------------------

def _aadhaar(rng: random.Random) -> str:
    """Return an UIDAI-reserved (invalid) Aadhaar-shaped 12-digit string.
    Real Aadhaar numbers cannot start with 0 or 1 per UIDAI spec, so all
    fakes here begin with 0."""
    parts = [
        f"0{rng.randint(0, 9)}{rng.randint(0, 9)}{rng.randint(0, 9)}",
        f"{rng.randint(1000, 9999)}",
        f"{rng.randint(1000, 9999)}",
    ]
    return " ".join(parts)


def _pan(rng: random.Random) -> str:
    """Return a PAN-shaped string with the documented test fourth letter
    'D' (Association of Persons placeholder)."""
    head = "".join(rng.choices("ABCDEFGHJKLMNPQRSTUVWXYZ", k=3))
    return f"{head}D{rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}{rng.randint(1000, 9999)}{rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}"


def _phone(rng: random.Random) -> str:
    """Indian-format test phone number (Indian +91 99999 prefix is reserved
    for testing in carrier docs)."""
    return f"+91 99999 9{rng.randint(1000, 9999)}"


def _email(rng: random.Random, name: str) -> str:
    handle = name.lower().replace(" ", ".")
    return f"{handle}@{rng.choice(EMAIL_DOMAINS)}"


def _customer_id(rng: random.Random) -> str:
    return f"{rng.randint(100_000_000, 999_999_999)}"


def _fill(rng: random.Random, template: Template) -> tuple[str, int]:
    """Substitute placeholders with synthetic values; return (text, n_entities).

    n_entities counts *substitution sites*, which is what the regex/NER
    pipeline will attempt to detect. Repeated entities across the template
    are counted separately because the middleware re-detects them.
    """
    name = rng.choice(NAMES)
    values = {
        "NAME": name,
        "CARD": rng.choice(TEST_CARDS),
        "CID": _customer_id(rng),
        "AADHAAR": _aadhaar(rng),
        "PAN": _pan(rng),
        "EMAIL": _email(rng, name),
        "PHONE": _phone(rng),
    }
    # Use sequential .replace so repeated keys still substitute.
    text = template.text
    for key in values:
        text = text.replace("{" + key + "}", values[key])
    return text, len(template.entity_keys)


def _density_bucket(n_entities: int) -> str:
    if n_entities <= 3:
        return "low"
    if n_entities <= 6:
        return "med"
    return "high"


def generate(
    out_path: Path,
    seed: int = 42,
    short_count: int = 30,
    med_count: int = 20,
    long_count: int = 10,
) -> int:
    """Write ``messages.jsonl`` deterministically. Returns the number of
    records written."""
    rng = random.Random(seed)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    plan: tuple[tuple[str, int, tuple[Template, ...]], ...] = (
        ("short", short_count, TEMPLATES_SHORT),
        ("med", med_count, TEMPLATES_MED),
        ("long", long_count, TEMPLATES_LONG),
    )
    for length_bucket, count, templates in plan:
        for _ in range(count):
            template = rng.choice(templates)
            text, n_entities = _fill(rng, template)
            records.append({
                "scenario": template.scenario,
                "length_bucket": length_bucket,
                "density_bucket": _density_bucket(n_entities),
                "n_entities": n_entities,
                "text": text,
            })

    # Stable IDs assigned in deterministic insertion order.
    with out_path.open("w", encoding="utf-8") as fh:
        for idx, record in enumerate(records, start=1):
            record = {"id": f"msg-{idx:04d}", **record}
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    return len(records)
