"""Unit tests for the BankingBuddy PII middleware.

Only structural aspects are tested here.  Full PII detection / de-anonymization
tests require a running ``pii_shield`` installation and are skipped when the
package is unavailable.
"""

import importlib
import sys

import pytest

# ---------------------------------------------------------------------------
# Detect whether required packages are available
# ---------------------------------------------------------------------------

_pii_shield_available = importlib.util.find_spec("pii_shield") is not None
_agent_framework_available = importlib.util.find_spec("agent_framework") is not None

skip_without_pii_shield = pytest.mark.skipif(
    not _pii_shield_available,
    reason="pii_shield is not installed",
)

skip_without_agent_framework = pytest.mark.skipif(
    not _agent_framework_available,
    reason="agent_framework is not installed",
)


# ── Structural tests ────────────────────────────────────────────────────


@skip_without_agent_framework
def test_middleware_class_exists():
    from bankingbuddy.middleware import PiiShieldChatMiddleware, PiiShieldFunctionMiddleware

    assert PiiShieldChatMiddleware is not None
    assert PiiShieldFunctionMiddleware is not None


@skip_without_agent_framework
def test_middleware_has_properties():
    """Verify that the public property descriptors are defined on the class."""
    from bankingbuddy.middleware import PiiShieldChatMiddleware

    assert hasattr(PiiShieldChatMiddleware, "last_anonymized_text")
    assert hasattr(PiiShieldChatMiddleware, "last_entities_found")
    assert hasattr(PiiShieldChatMiddleware, "last_raw_llm_response")

    # They should be declared as @property descriptors on the class
    assert isinstance(
        PiiShieldChatMiddleware.__dict__["last_anonymized_text"], property
    )
    assert isinstance(
        PiiShieldChatMiddleware.__dict__["last_entities_found"], property
    )
    assert isinstance(
        PiiShieldChatMiddleware.__dict__["last_raw_llm_response"], property
    )


@skip_without_agent_framework
def test_function_middleware_deanonymize_args():
    """Verify FunctionMiddleware can de-anonymize tool arguments."""
    from bankingbuddy.middleware import (
        PiiShieldChatMiddleware,
        PiiShieldFunctionMiddleware,
        _PiiRunState,
    )

    chat_mw = PiiShieldChatMiddleware()
    fn_mw = PiiShieldFunctionMiddleware(chat_mw)

    state = _PiiRunState(
        entity_mapping={"PERSON_1": "Rajesh Kumar", "CUSTOMER_ID_1": "617823490"},
    )
    args = {"customer_id": "CUSTOMER_ID_1", "name": "PERSON_1"}
    restored = fn_mw._deanonymize_args(args, state)

    assert restored["customer_id"] == "617823490"
    assert restored["name"] == "Rajesh Kumar"


# ── Tests that require pii_shield ────────────────────────────────────────


@skip_without_agent_framework
@skip_without_pii_shield
def test_middleware_instantiation():
    """Instantiate the middleware with the default engine (requires pii_shield)."""
    from bankingbuddy.middleware import PiiShieldChatMiddleware

    mw = PiiShieldChatMiddleware()
    assert mw.last_anonymized_text == ""
    assert mw.last_entities_found == []
    assert mw.last_raw_llm_response == ""
