"""PII Shield Middleware – the **LLM Sandwich** pattern.

The middleware sits between the user and the LLM:

1. **Anonymize** – before the LLM sees any user message, PII is detected and
   replaced with safe placeholders (fake names, hashes, etc.).
2. **LLM processes** – the model reasons over scrubbed text only.
3. **De-anonymize tool args** – when the LLM calls a tool, placeholders in
   arguments are restored to real values so the tool can query real data.
4. **Re-anonymize tool results** – tool output (which may contain new PII)
   is anonymized before the LLM sees it.
5. **De-anonymize final response** – the LLM response is post-processed to
   restore original PII so the end user sees real names, accounts, etc.

This keeps sensitive data out of model context while preserving a natural
conversation for the customer.

Supports two modes (configured via ``PII_SHIELD_MODE`` env var):

- ``library`` – imports ``pii_shield.PiiShieldEngine`` and runs NLP in-process.
  Requires the ``pii-shield`` package to be installed. Lower latency.
- ``api`` *(default)* – calls a remote PII Shield REST API
  (``/anonymize_unique`` and ``/deanonymize``). Requires ``PII_SHIELD_API_URL``
  to be set. Decouples the NLP model from this process.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import requests as http_requests

from agent_framework import (
    ChatContext,
    ChatMiddleware,
    FunctionInvocationContext,
    FunctionMiddleware,
    Message,
)

logger = logging.getLogger("bankingbuddy")

# Lazy import – only needed when PII_SHIELD_MODE=library
try:
    from pii_shield.engine import PiiShieldEngine
except ImportError:  # pragma: no cover
    PiiShieldEngine = None  # type: ignore[assignment,misc]

# Key used to pass PII state through function_invocation_kwargs
_PII_STATE_KEY = "__pii_shield_state"


@dataclass
class _PiiRunState:
    """Per-invocation shared state between ChatMiddleware and FunctionMiddleware."""

    entity_mapping: dict[str, str] = field(default_factory=dict)
    hash_mapping: dict[str, str] = field(default_factory=dict)
    encrypt_mapping: dict[str, str] = field(default_factory=dict)
    session_id: str = ""


@dataclass
class PiiMappingStore:
    """Accumulated PII mappings across all turns in a conversation.

    The Streamlit UI maintains an instance of this and passes it to the
    ChatMiddleware so that the FunctionMiddleware can de-anonymize tool
    arguments that reference placeholders from earlier turns.
    """

    entity_mapping: dict[str, str] = field(default_factory=dict)
    hash_mapping: dict[str, str] = field(default_factory=dict)
    encrypt_mapping: dict[str, str] = field(default_factory=dict)


class PiiShieldChatMiddleware(ChatMiddleware):
    """Anonymize user messages before the LLM; de-anonymize responses after.

    Parameters
    ----------
    mode : str
        ``"api"`` (default) — call PII Shield REST API.
        ``"library"`` — use the in-process ``PiiShieldEngine``.
        Falls back to ``PII_SHIELD_MODE`` env var.
    api_url : str | None
        Base URL of the PII Shield API (e.g. ``http://localhost:8000``).
        Falls back to ``PII_SHIELD_API_URL`` env var.
    api_app_id : str | None
        Optional app-id header for the PII Shield API (``X-App-Id``).
        Falls back to ``PII_SHIELD_APP_ID`` env var.
    engine : PiiShieldEngine | None
        Pre-built engine instance (library mode only).
    """

    def __init__(
        self,
        mode: str | None = None,
        api_url: str | None = None,
        api_app_id: str | None = None,
        engine: "PiiShieldEngine | None" = None,
        allow_list: list[str] | None = None,
        entity_type_allow_list: list[str] | None = None,
        mapping_store: PiiMappingStore | None = None,
    ) -> None:
        self._mode = (mode or os.getenv("PII_SHIELD_MODE", "api")).strip().lower()
        self._api_url = (api_url or os.getenv("PII_SHIELD_API_URL", "http://localhost:8000")).rstrip("/")
        self._api_app_id = api_app_id or os.getenv("PII_SHIELD_APP_ID", "")
        self._api_timeout = int(os.getenv("PII_SHIELD_API_TIMEOUT", "10"))

        # Terms and entity types to exclude from anonymization.
        self._allow_list = allow_list or []
        self._entity_type_allow_list = entity_type_allow_list or [
            "NRP",          # Nationality/Religious/Political — common false positive
        ]

        # Cross-turn mapping accumulator. If provided, the middleware seeds
        # each run's state from it and updates it after anonymization.
        self._mapping_store = mapping_store or PiiMappingStore()

        # Current run state — set during process(), read by FunctionMiddleware.
        self._current_run_state: _PiiRunState | None = None

        if self._mode == "library":
            if engine is not None:
                self._engine = engine
            else:
                if PiiShieldEngine is None:
                    raise ImportError(
                        "pii_shield is not installed. "
                        "Install it or switch to PII_SHIELD_MODE=api."
                    )
                self._engine = PiiShieldEngine()
        else:
            self._engine = None

        # Exposed for the Streamlit UI's "what the LLM sees" panel.
        self._last_anonymized_text: str = ""
        self._last_entities_found: list[str] = []
        self._last_raw_llm_response: str = ""

    # ------------------------------------------------------------------
    # Public properties for the UI
    # ------------------------------------------------------------------

    @property
    def last_anonymized_text(self) -> str:
        """The most recently anonymized user message (empty if none yet)."""
        return self._last_anonymized_text

    @property
    def last_entities_found(self) -> list[str]:
        """Entity types detected in the most recent anonymization call."""
        return list(self._last_entities_found)

    @property
    def last_raw_llm_response(self) -> str:
        """The raw LLM response before de-anonymization (empty if none yet)."""
        return self._last_raw_llm_response

    # ------------------------------------------------------------------
    # Anonymization backends
    # ------------------------------------------------------------------

    def _anonymize_library(self, text: str, state: _PiiRunState) -> tuple[str, list[str]]:
        """Anonymize using the in-process PiiShieldEngine."""
        result = self._engine.anonymize(
            text,
            allow_list=self._allow_list or None,
            entity_type_allow_list=set(self._entity_type_allow_list) or None,
        )
        state.entity_mapping.update(result.entity_mapping)
        state.hash_mapping.update(result.hash_mapping)
        state.encrypt_mapping.update(result.encrypt_mapping)
        entity_types = [e.entity_type for e in result.entities]
        return result.anonymized_text, entity_types

    def _anonymize_api(self, text: str, state: _PiiRunState) -> tuple[str, list[str]]:
        """Anonymize by calling the PII Shield REST API."""
        headers = {"Content-Type": "application/json"}
        if self._api_app_id:
            headers["X-App-Id"] = self._api_app_id

        resp = http_requests.post(
            f"{self._api_url}/anonymize_unique",
            json={
                "text": text,
                "allow_list": self._allow_list,
                "entity_type_allow_list": self._entity_type_allow_list,
            },
            headers=headers,
            timeout=self._api_timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        state.session_id = data.get("id", "")
        state.entity_mapping.update(data.get("entity_mapping", {}))
        state.hash_mapping.update(data.get("hash_mapping", {}))
        state.encrypt_mapping.update(data.get("encrypt_mapping", {}))

        entity_types = list({
            re.sub(r'[{}]', '', k).rsplit('_', 1)[0]
            for k in data.get("entity_mapping", {}).keys()
        }) if data.get("entity_mapping") else []

        return data["anonymized_text"], entity_types

    def _deanonymize_library(self, text: str, state: _PiiRunState) -> str:
        """Deanonymize using the in-process PiiShieldEngine."""
        return self._engine.deanonymize(
            text,
            entity_mapping=state.entity_mapping,
            hash_mapping=state.hash_mapping or None,
            encrypt_mapping=state.encrypt_mapping or None,
        )

    @staticmethod
    def _deanonymize_local(text: str, state: _PiiRunState) -> str:
        """Deanonymize via local string replacement using accumulated mappings."""
        result = text
        for placeholder, original in state.entity_mapping.items():
            result = result.replace(placeholder, original)
        return result

    def _deanonymize_api(self, text: str, state: _PiiRunState) -> str:
        """Deanonymize by calling the PII Shield REST API.

        Falls back to local string replacement when no API session exists
        but entity mappings are available (e.g. from a prior turn).
        """
        if not state.session_id:
            # No API session for this turn — use local replacement with
            # accumulated mappings from the mapping store.
            return self._deanonymize_local(text, state)

        headers = {"Content-Type": "application/json"}
        if self._api_app_id:
            headers["X-App-Id"] = self._api_app_id

        resp = http_requests.post(
            f"{self._api_url}/deanonymize",
            json={"id": state.session_id, "text": text},
            headers=headers,
            timeout=self._api_timeout,
        )
        resp.raise_for_status()
        return resp.json()["text"]

    # ------------------------------------------------------------------
    # Middleware entry-point
    # ------------------------------------------------------------------

    async def process(
        self,
        context: ChatContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        """Run the LLM Sandwich: anonymize → LLM → de-anonymize."""

        # Build a run state seeded with accumulated mappings from prior turns.
        # _current_run_state is reset to None by the caller (Streamlit UI)
        # before each agent.run(). Within a single agent.run(), the framework
        # may call process() multiple times (tool-calling loop) — we reuse
        # the same state so entity mappings persist.
        if self._current_run_state is None:
            run_state = _PiiRunState(
                entity_mapping=dict(self._mapping_store.entity_mapping),
                hash_mapping=dict(self._mapping_store.hash_mapping),
                encrypt_mapping=dict(self._mapping_store.encrypt_mapping),
            )
            self._current_run_state = run_state
            is_first_call = True
        else:
            run_state = self._current_run_state
            is_first_call = False

        context.function_invocation_kwargs[_PII_STATE_KEY] = run_state

        anonymize = self._anonymize_library if self._mode == "library" else self._anonymize_api
        deanonymize = self._deanonymize_library if self._mode == "library" else self._deanonymize_api

        # ── Step 1: Anonymize the last user message ──────────────────
        # Only update UI fields on the first call (when real anonymization
        # happens). Subsequent calls in the tool-calling loop should not
        # clobber the values captured from the initial anonymization.
        if is_first_call:
            self._last_anonymized_text = ""
            self._last_entities_found = []
            self._last_raw_llm_response = ""

        modified_messages: list[Message] = list(context.messages)
        for i in range(len(modified_messages) - 1, -1, -1):
            msg = modified_messages[i]
            if msg.role == "user" and msg.text:
                anon_text, entity_types = anonymize(msg.text, run_state)

                if entity_types:
                    logger.info(
                        "PII detected in user message – entities: %s",
                        entity_types,
                    )

                # Capture UI state on the first call of this agent.run().
                if is_first_call:
                    self._last_entities_found = entity_types
                    self._last_anonymized_text = anon_text

                modified_messages[i] = Message(msg.role, [anon_text])
                break

        context.messages[:] = modified_messages

        # ── Step 2: Let the LLM process the scrubbed conversation ────
        await call_next()

        # ── Step 3: De-anonymize LLM responses ──────────────────────
        has_mappings = (
            run_state.entity_mapping
            or run_state.hash_mapping
            or run_state.encrypt_mapping
            or run_state.session_id
        )

        # Capture raw LLM response for the UI — only keep the latest
        # assistant message (the final answer), not accumulated tool-loop
        # intermediates.
        if context.result and context.result.messages:
            assistant_texts = [
                msg.text for msg in context.result.messages
                if msg.role == "assistant" and msg.text
            ]
            if assistant_texts:
                self._last_raw_llm_response = assistant_texts[-1]

        if has_mappings and context.result and context.result.messages:
            for msg in context.result.messages:
                # De-anonymize each text content item in-place so the
                # framework's tool-loop message accumulation (which may
                # extend contents) is not disrupted by replacing Message
                # objects.
                for content_item in msg.contents:
                    if hasattr(content_item, 'text') and content_item.text:
                        content_item.text = self._deanonymize_local(
                            content_item.text, run_state,
                        )

        # Persist new mappings into the cross-turn store so that future
        # turns can de-anonymize placeholders created in this turn.
        self._mapping_store.entity_mapping.update(run_state.entity_mapping)
        self._mapping_store.hash_mapping.update(run_state.hash_mapping)
        self._mapping_store.encrypt_mapping.update(run_state.encrypt_mapping)


class PiiShieldFunctionMiddleware(FunctionMiddleware):
    """De-anonymize tool arguments and re-anonymize tool results.

    Works in tandem with ``PiiShieldChatMiddleware``:

    - **Before tool execution:** replaces anonymized placeholders in tool
      arguments with the original PII values so the tool can query real data.
    - **After tool execution:** re-anonymizes the tool result via PII Shield
      so the LLM never sees raw PII from tool output (e.g. email, phone
      returned by ``get_customer_info``).

    The shared ``_PiiRunState`` is received via
    ``context.kwargs[_PII_STATE_KEY]``, which the ChatMiddleware publishes
    through ``context.function_invocation_kwargs``.
    """

    def __init__(self, chat_middleware: PiiShieldChatMiddleware) -> None:
        self._chat_mw = chat_middleware

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deanonymize_value(value: str, state: _PiiRunState) -> str:
        """Replace anonymized placeholders in a single string value."""
        result = value
        for placeholder, original in state.entity_mapping.items():
            result = result.replace(placeholder, original)
        return result

    @staticmethod
    def _deanonymize_args(
        arguments: dict[str, object],
        state: _PiiRunState,
    ) -> dict[str, object]:
        """Return a copy of *arguments* with placeholders restored."""
        restored: dict[str, object] = {}
        for key, val in arguments.items():
            if isinstance(val, str):
                restored[key] = PiiShieldFunctionMiddleware._deanonymize_value(
                    val, state,
                )
            else:
                restored[key] = val
        return restored

    # ------------------------------------------------------------------
    # Middleware entry-point
    # ------------------------------------------------------------------

    async def process(
        self,
        context: FunctionInvocationContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        # Read state from the ChatMiddleware instance directly — this
        # avoids issues with dict copies in the framework's kwargs plumbing.
        state: _PiiRunState | None = getattr(
            self._chat_mw, '_current_run_state', None
        )
        if state is None:
            state = context.kwargs.get(_PII_STATE_KEY)

        if state is None or not state.entity_mapping:
            await call_next()
            return

        # ── De-anonymize tool arguments ──────────────────────────────
        args = context.arguments
        if isinstance(args, dict):
            context.arguments = self._deanonymize_args(args, state)
        else:
            # BaseModel — convert to dict, de-anonymize, reassign
            arg_dict = dict(args) if hasattr(args, "__iter__") else {}
            if arg_dict:
                context.arguments = self._deanonymize_args(arg_dict, state)

        logger.debug(
            "Tool %s: de-anonymized args before execution",
            context.function.name,
        )

        # ── Execute the tool ─────────────────────────────────────────
        await call_next()

        # ── Re-anonymize tool result ─────────────────────────────────
        if context.result:
            anonymize_fn = (
                self._chat_mw._anonymize_library
                if self._chat_mw._mode == "library"
                else self._chat_mw._anonymize_api
            )

            if isinstance(context.result, str):
                anon_result, _ = anonymize_fn(context.result, state)
                context.result = anon_result
            elif isinstance(context.result, list):
                # Result is a list of Content objects
                for item in context.result:
                    if hasattr(item, 'text') and isinstance(item.text, str):
                        anon_text, _ = anonymize_fn(item.text, state)
                        item.text = anon_text

            logger.debug(
                "Tool %s: re-anonymized result before returning to LLM",
                context.function.name,
            )
