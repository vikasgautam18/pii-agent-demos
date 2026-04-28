"""Streamlit chat UI for BankingBuddy — Contoso Bank AI Assistant.

Run:  streamlit run app/streamlit_chat.py
"""

from __future__ import annotations

import asyncio
import logging
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page config & custom CSS
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="BankingBuddy — Contoso Bank",
    page_icon="🏦",
    layout="wide",
)

st.markdown(
    "<style>"
    "#MainMenu {visibility: hidden;} "
    "footer {visibility: hidden;} "
    "header [data-testid='stStatusWidget'] {display: none;} "
    ".stDeployButton {display: none;}"
    "</style>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Agent initialisation (once per session)
# ---------------------------------------------------------------------------


def _init_agent() -> None:
    """Create the BankingBuddy agent and store it in session state."""
    if "agent" in st.session_state:
        return

    try:
        from azure.identity.aio import AzureCliCredential

        from bankingbuddy.agent import create_agent
        from bankingbuddy.middleware import PiiMappingStore

        credential = AzureCliCredential()
        mapping_store = PiiMappingStore()
        agent, middleware = asyncio.run(
            create_agent(credential, mapping_store=mapping_store)
        )
        st.session_state["agent"] = agent
        st.session_state["middleware"] = middleware
        st.session_state["credential"] = credential
        st.session_state["mapping_store"] = mapping_store
    except Exception as exc:  # noqa: BLE001
        logger.exception("BankingBuddy init failed")
        st.session_state["init_error"] = (
            f"{type(exc).__name__}: initialization failed. See server logs."
        )


_init_agent()

# ---------------------------------------------------------------------------
# Session-state defaults
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state["messages"] = []

# Anonymized conversation history for the LLM — the LLM never sees real PII.
# Each entry is {"role": ..., "content": ...} with placeholders instead of PII.
if "anon_history" not in st.session_state:
    st.session_state["anon_history"] = []

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("🏦 Contoso Bank")
st.sidebar.caption("BankingBuddy AI Assistant")

st.sidebar.markdown("🟢 **PII Shield Active**")

st.sidebar.divider()

# Sample prompts -----------------------------------------------------------

st.sidebar.subheader("💬 Sample prompts")

SAMPLE_PROMPTS = [
    "My card 5555 5555 5555 4444 is blocked. Customer ID: 617823490. I'm Rajesh Kumar.",
    "I lost my credit card! I'm Priya Sharma, customer ID 528194073. Card number is 5105 1051 0510 5100.",
    "I need a new debit card. My customer ID is 439065182, name is Amit Patel, email amit.patel@contoso.com",
]

for prompt in SAMPLE_PROMPTS:
    if st.sidebar.button(prompt, use_container_width=True):
        st.session_state["pending_prompt"] = prompt

st.sidebar.divider()

# Customer reference table -------------------------------------------------

st.sidebar.subheader("👤 Sample customers")
st.sidebar.table(
    {
        "ID": ["617823490", "528194073", "439065182", "350976214", "261847305"],
        "Name": [
            "Rajesh Kumar",
            "Priya Sharma",
            "Amit Patel",
            "Sneha Reddy",
            "Vikram Singh",
        ],
        "Aadhaar": [
            "2345 6789 0123",
            "3456 7890 1234",
            "4567 8901 2345",
            "5678 9012 3456",
            "6789 0123 4567",
        ],
        "Email": [
            "rajesh.kumar@contoso.com",
            "priya.sharma@contoso.com",
            "amit.patel@contoso.com",
            "sneha.reddy@contoso.com",
            "vikram.singh@contoso.com",
        ],
    }
)

st.sidebar.subheader("💳 Sample card numbers")
st.sidebar.table(
    {
        "Customer": [
            "Rajesh Kumar",
            "Priya Sharma",
            "Amit Patel",
            "Sneha Reddy",
            "Vikram Singh",
        ],
        "Card Number": [
            "5555 5555 5555 4444",
            "5105 1051 0510 5100",
            "3530 1113 3330 0000",
            "6011 1111 1111 1117",
            "3714 4963 5398 431",
        ],
    }
)

# ---------------------------------------------------------------------------
# Main chat area
# ---------------------------------------------------------------------------

st.title("🏦 BankingBuddy")
st.caption("Your AI-powered banking assistant — protected by PII Shield")

# Show initialisation error if any -----------------------------------------

if "init_error" in st.session_state:
    st.error(
        "⚠️ **Could not initialise BankingBuddy.**\n\n"
        f"`{st.session_state['init_error']}`\n\n"
        "**Setup checklist:**\n"
        "1. Run `az login` to authenticate with Azure CLI.\n"
        "2. Set `AZURE_SUBSCRIPTION_ID` and model endpoint env vars in `.env`.\n"
        "3. Install project dependencies: `pip install -e '.[dev]'`.",
    )
    st.stop()

# Render conversation history ----------------------------------------------

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            anon_text = msg.get("anon_text")
            raw_llm = msg.get("raw_llm_response")
            entities = msg.get("entities")
            if anon_text is not None:
                with st.expander("🔒 Sent to LLM (anonymized)", expanded=False):
                    st.code(anon_text, language=None)
                    if entities:
                        st.caption(f"Detected entities: {', '.join(entities)}")
                    else:
                        st.caption("No PII detected")
            if raw_llm is not None:
                with st.expander("🤖 Received from LLM (raw)", expanded=False):
                    st.code(raw_llm, language=None)

# ---------------------------------------------------------------------------
# Handle user input
# ---------------------------------------------------------------------------


def _get_user_input() -> str | None:
    """Return the next user message — from chat input or a sidebar button."""
    if "pending_prompt" in st.session_state:
        text = st.session_state.pop("pending_prompt")
        return text
    return None


def _run_agent(user_text: str) -> str:
    """Call the async agent synchronously.

    Sends the already-anonymized conversation history plus the new user
    message (which the ChatMiddleware will anonymize on the fly).
    """
    agent = st.session_state["agent"]
    middleware = st.session_state["middleware"]

    # Reset run state so the middleware knows this is a new agent.run()
    middleware._current_run_state = None

    from agent_framework import Message

    # Build messages from the anonymized history so the LLM never
    # sees de-anonymized PII from previous turns.
    messages = []
    for msg in st.session_state["anon_history"]:
        messages.append(Message(msg["role"], [msg["content"]]))
    # Only the new user message needs anonymization by the middleware
    messages.append(Message("user", [user_text]))

    result = asyncio.run(agent.run(messages))

    # The agent framework accumulates content items within a single
    # assistant message across tool-calling loop iterations. Extract
    # only the last text content — that's the final user-facing answer.
    for msg in reversed(result.messages):
        if msg.role == "assistant" and msg.contents:
            text_items = [
                c.text for c in msg.contents
                if hasattr(c, 'text') and c.text and getattr(c, 'type', None) == 'text'
            ]
            if text_items:
                return text_items[-1]
    return str(result)


# Check for pending sidebar prompt first, then chat_input
pending = _get_user_input()
chat_text = st.chat_input("Ask BankingBuddy...")

user_input = pending or chat_text

if user_input:
    # Display user message
    st.session_state["messages"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Get agent response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response = _run_agent(user_input)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Agent run failed")
                st.error("Agent error — see server logs for details.")
                response = "I'm sorry, I encountered an error. Please try again."

        st.markdown(response)

        # Always show PII shield details as collapsed expanders
        middleware = st.session_state["middleware"]
        anon_text = middleware.last_anonymized_text or user_input
        entities = middleware.last_entities_found
        raw_llm = middleware.last_raw_llm_response or response

        with st.expander("🔒 Sent to LLM (anonymized)", expanded=False):
            st.code(anon_text, language=None)
            if entities:
                st.caption(f"Detected entities: {', '.join(entities)}")
            else:
                st.caption("No PII detected")

        with st.expander("🤖 Received from LLM (raw)", expanded=False):
            st.code(raw_llm, language=None)

    # Store de-anonymized messages for the UI
    st.session_state["messages"].append({
        "role": "assistant",
        "content": response,
        "anon_text": anon_text,
        "entities": entities,
        "raw_llm_response": raw_llm,
    })

    # Store anonymized versions for future LLM calls — the LLM should
    # only ever see placeholders, never real PII from prior turns.
    st.session_state["anon_history"].append(
        {"role": "user", "content": anon_text}
    )
    st.session_state["anon_history"].append(
        {"role": "assistant", "content": raw_llm}
    )
