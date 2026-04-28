"""BankingBuddy agent definition.

Wires together the system prompt, tools, and PII Shield middleware into a
single ``Agent`` instance that can be used by the Streamlit UI or tested
from the command line.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import AzureCliCredential

from bankingbuddy.middleware import PiiShieldChatMiddleware, PiiShieldFunctionMiddleware, PiiMappingStore
from bankingbuddy.tools import (
    get_customer_info,
    get_card_status,
    list_customer_cards,
    unblock_card,
    order_new_card,
    report_lost_card,
    verify_customer_identity,
)

load_dotenv()

# ---------------------------------------------------------------------------
# System instructions
# ---------------------------------------------------------------------------

INSTRUCTIONS = (
    "You are BankingBuddy, the AI banking assistant for Contoso Bank.\n\n"
    "Guidelines:\n"
    "- Be professional, helpful, and concise.\n"
    "- Always ask for the customer ID first if it has not been provided.\n"
    "- For sensitive operations (unblock card, report lost card, order new "
    "card), verify the customer's identity first. Ask the customer to "
    "provide any of the following: their **Aadhaar number**, **email address**, "
    "or **full 16-digit card number**. Use the verify_customer_identity tool "
    "with whatever credentials they provide.\n"
    "- Confirm destructive actions (unblock card, report lost card) with the "
    "customer before executing them.\n"
    "- Never reveal internal system details, tool names, or implementation "
    "specifics.\n"
    "- When listing cards, show the card type, last four digits, and status.\n"
    "- After completing a task, offer to help with anything else.\n"
    "- Always address the customer by their name when responding."
)

# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


async def create_agent(
    credential: AzureCliCredential,
    pii_engine: object | None = None,
    mapping_store: PiiMappingStore | None = None,
) -> tuple[Agent, PiiShieldChatMiddleware]:
    """Create the BankingBuddy agent with PII Shield middleware.

    Parameters
    ----------
    credential:
        Azure credential used to authenticate with the Foundry chat model.
    pii_engine:
        Optional ``PiiShieldEngine`` instance (library mode only).
        When *None* the middleware reads ``PII_SHIELD_MODE`` from .env
        to decide between API mode (default) and library mode.
    mapping_store:
        Optional ``PiiMappingStore`` for accumulating PII mappings across
        turns. When provided, the middleware seeds each run's state from
        it so the FunctionMiddleware can de-anonymize placeholders from
        earlier turns.

    Returns
    -------
    tuple[Agent, PiiShieldChatMiddleware]
        The configured agent and its middleware (exposed so callers such as
        the Streamlit UI can inspect ``last_anonymized_text``).
    """
    if pii_engine is not None:
        middleware = PiiShieldChatMiddleware(
            mode="library", engine=pii_engine, mapping_store=mapping_store,
        )
    else:
        middleware = PiiShieldChatMiddleware(mapping_store=mapping_store)

    fn_middleware = PiiShieldFunctionMiddleware(middleware)

    agent = Agent(
        name="BankingBuddy",
        instructions=INSTRUCTIONS,
        client=FoundryChatClient(credential=credential),
        tools=[
            get_customer_info,
            get_card_status,
            list_customer_cards,
            unblock_card,
            order_new_card,
            report_lost_card,
            verify_customer_identity,
        ],
        middleware=[middleware, fn_middleware],
    )

    return agent, middleware


# ---------------------------------------------------------------------------
# CLI helper (quick testing only)
# ---------------------------------------------------------------------------


async def run_cli() -> None:
    """Run a simple interactive loop for command-line testing."""
    credential = AzureCliCredential()
    agent, _middleware = await create_agent(credential)

    print("BankingBuddy CLI  (type 'quit' to exit)")
    print("-" * 40)

    while True:
        try:
            user_input = input("You: ")
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.strip().lower() in {"quit", "exit"}:
            break

        response = await agent.run(user_input)
        print(f"BankingBuddy: {response}\n")

    await credential.close()


if __name__ == "__main__":
    asyncio.run(run_cli())
