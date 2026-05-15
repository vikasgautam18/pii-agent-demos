"""Build minimal real ``ChatContext`` instances for benchmarking.

We use the framework's actual ``ChatContext`` class (constructed with
``client=None``) rather than a mock, so the middleware exercises the same
attribute access paths it uses in production.
"""

from __future__ import annotations

from agent_framework import ChatContext, Message


def make_chat_context(user_text: str) -> ChatContext:
    """Build a ChatContext containing a single user message."""
    return ChatContext(
        client=None,            # type: ignore[arg-type]
        messages=[Message(role="user", contents=[user_text])],
        options=None,
    )
