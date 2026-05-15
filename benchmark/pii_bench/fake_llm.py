"""Yielding "fake LLM" coroutine. Used as the ``call_next`` substitute
for the middleware so we can isolate middleware overhead from real LLM
variance.

Crucially, the sleep is **chunked** into many small ``await`` points so the
event loop has many opportunities to switch tasks. A single
``asyncio.sleep(0.3)`` in a coroutine artificially makes the rest of the
event loop look healthy even when middleware is blocking it with sync
``requests``. The chunked variant exposes that pathology under the
concurrency scenario.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

from agent_framework import ChatContext, ChatResponse, Message


_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+_\d+\}\}")


def _build_response_text(anonymized_user_text: str) -> str:
    """Echo back any placeholders the middleware injected, preserving them
    verbatim, so the deanonymize step has work to do."""
    placeholders = _PLACEHOLDER_RE.findall(anonymized_user_text)
    if not placeholders:
        return "Acknowledged. How else can I help?"
    head = "Hello " + (placeholders[0] if placeholders else "") + ","
    tail = "Your request involving " + ", ".join(placeholders[1:]) + " has been processed."
    return head + " " + tail if len(placeholders) > 1 else head + " your request has been processed."


def make_fake_llm(
    delay_ms: int = 300,
    yield_chunks: int = 30,
) -> Callable[[ChatContext], Awaitable[None]]:
    """Return a coroutine factory matching the ``call_next`` shape used by
    ``ChatMiddleware.process``.

    The factory is parameterised over the context so each invocation can
    inspect ``ctx.messages[-1]`` to mint a placeholder-preserving response.

    Args:
        delay_ms: Total simulated LLM latency in milliseconds.
        yield_chunks: Number of ``asyncio.sleep`` slices the delay is
            split into. 1 = blocking-equivalent (one big sleep);
            many = cooperative.
    """
    chunk_s = (delay_ms / 1000.0) / max(yield_chunks, 1)

    async def fake_llm(context: ChatContext) -> None:
        # 1. Sleep cooperatively.
        for _ in range(max(yield_chunks, 1)):
            await asyncio.sleep(chunk_s)

        # 2. Mint a response that preserves placeholders so the deanonymize
        #    step actually does work (otherwise we'd under-measure T3).
        last_user_text = ""
        for msg in reversed(context.messages):
            text = getattr(msg, "text", None)
            if text:
                last_user_text = text
                break

        response_text = _build_response_text(last_user_text)
        context.result = ChatResponse(
            messages=[Message(role="assistant", contents=[response_text])],
            response_id="fake-llm",
        )

    return fake_llm
