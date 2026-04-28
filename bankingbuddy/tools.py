"""
Tool functions for the BankingBuddy agent — a Contoso Bank AI assistant demo.

Each tool wraps one or more operations from the fake in-memory data layer
(``bankingbuddy.fake_data``) and returns a human-readable string that the LLM
can relay to the user.
"""

from __future__ import annotations

from typing import Annotated

from agent_framework import tool
from bankingbuddy import fake_data
from pydantic import Field


@tool(approval_mode="never_require")
def get_customer_info(
    customer_id: Annotated[str, Field(description="The unique customer ID, e.g. '617823490'")],
) -> str:
    """Look up a customer's profile by their customer ID."""
    customer = fake_data.get_customer(customer_id)
    if customer is None:
        return "Customer not found."
    return (
        f"Name: {customer['name']}\n"
        f"Email: {customer['email']}\n"
        f"Phone: {customer['phone']}"
    )


@tool(approval_mode="never_require")
def get_card_status(
    card_number_last_four: Annotated[str, Field(description="Last four digits of the card number")],
    customer_id: Annotated[str, Field(description="The customer ID that owns the card")],
) -> str:
    """Get the status of a card by its last four digits and customer ID."""
    card = fake_data.find_card_by_last_four(card_number_last_four, customer_id)
    if card is None:
        return "Card not found."
    return (
        f"Card ID: {card['card_id']}\n"
        f"Card Type: {card['card_type']}\n"
        f"Status: {card['status']}\n"
        f"Expiry: {card['expiry']}\n"
        f"Daily Limit: ₹{card['daily_limit']:,}"
    )


@tool(approval_mode="never_require")
def list_customer_cards(
    customer_id: Annotated[str, Field(description="The customer ID to list cards for")],
) -> str:
    """List all cards for a customer."""
    cards = fake_data.get_cards_for_customer(customer_id)
    if not cards:
        return "No cards found for this customer."
    lines: list[str] = []
    for card in cards:
        lines.append(
            f"- {card['card_id']} | {card['card_type']} | "
            f"ending {card['last_four']} | status: {card['status']}"
        )
    return "\n".join(lines)


@tool(approval_mode="never_require")
def unblock_card(
    card_id: Annotated[str, Field(description="The card ID to unblock, e.g. 'CARD-002'")],
    reason: Annotated[str, Field(description="Reason for unblocking the card")],
) -> str:
    """Unblock a blocked card. Only works if the card is currently blocked."""
    card = fake_data.get_card(card_id)
    if card is None:
        return "Card not found."
    if card["status"] != "blocked":
        return (
            f"Cannot unblock card {card_id} — current status is '{card['status']}'. "
            f"Only cards with status 'blocked' can be unblocked."
        )
    fake_data.update_card_status(card_id, "active")
    return f"Card {card_id} has been successfully unblocked. Reason: {reason}"


@tool(approval_mode="never_require")
def order_new_card(
    customer_id: Annotated[str, Field(description="The customer ID to order a new card for")],
    card_type: Annotated[str, Field(description="Type of card to order: 'debit' or 'credit'")],
) -> str:
    """Order a new replacement card for a customer."""
    if card_type not in ("debit", "credit"):
        return f"Invalid card type '{card_type}'. Must be 'debit' or 'credit'."
    customer = fake_data.get_customer(customer_id)
    if customer is None:
        return "Customer not found."
    new_card = fake_data.create_replacement_card(customer_id, card_type)
    return (
        f"New {card_type} card ordered successfully!\n"
        f"Card ID: {new_card['card_id']}\n"
        f"Card ending: {new_card['last_four']}\n"
        f"Estimated delivery: 5-7 business days"
    )


@tool(approval_mode="never_require")
def report_lost_card(
    card_id: Annotated[str, Field(description="The card ID to report as lost")],
    last_seen_location: Annotated[str, Field(description="Where the card was last seen or used")],
) -> str:
    """Report a card as lost. The card will be immediately blocked."""
    card = fake_data.get_card(card_id)
    if card is None:
        return "Card not found."
    if card["status"] == "lost":
        return f"Card {card_id} has already been reported as lost."
    fake_data.update_card_status(card_id, "lost")
    return (
        f"Card {card_id} has been reported as lost and is now blocked.\n"
        f"Last seen location: {last_seen_location}\n"
        f"Please order a replacement card if needed."
    )


@tool(approval_mode="never_require")
def verify_customer_identity(
    customer_id: Annotated[str, Field(description="The customer ID")],
    aadhaar: Annotated[str | None, Field(description="The customer's 12-digit Aadhaar number")] = None,
    email: Annotated[str | None, Field(description="The customer's email address")] = None,
    card_number: Annotated[str | None, Field(description="The full 16-digit card number")] = None,
) -> str:
    """Verify a customer's identity using one or more credentials.

    Use this tool before performing sensitive operations (unblock card,
    report lost card, order new card). The customer should provide at
    least one of: Aadhaar number, email address, or full card number.
    """
    result = fake_data.verify_customer_identity(
        customer_id,
        aadhaar=aadhaar,
        email=email,
        card_number=card_number,
    )
    if result["verified"]:
        return (
            f"Verification successful!\n"
            f"{result['details']}\n"
            f"Customer name: {result['customer_name']}"
        )
    return f"Verification failed: {result['details']}"
