"""Real-LLM ``call_next`` implementation, using the same ``FoundryChatClient``
the BankingBuddy agent uses.

Use this when you want an end-to-end measurement that includes real LLM
latency. **Caveats** (read these before quoting numbers):

* LLM p99/p50 ratio is typically 2–3× — it will visually drown the
  millisecond-scale middleware overhead in the absolute-latency tables.
  The Δ row remains valid (paired comparison), but interpret the per-arm
  rows as "dominated by LLM, with a small constant middleware tax".
* Each measured pair = 2 LLM calls. Cost and TPM/RPM consumption scales
  linearly. Default sample count is dropped to 30 for the real LLM.
* The concurrency sweep is **disabled by default** when using the real
  LLM, because Azure / Foundry rate limits will turn the high-C buckets
  into a 429-storm rather than a measurement. Pass
  ``--allow-concurrency`` if your deployment can handle it.
* Determinism: ``temperature=0`` and a fixed ``seed`` are passed to
  reduce — but not eliminate — response-shape variance. Some token-by-
  token jitter remains.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from agent_framework import ChatContext, ChatOptions
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import AzureCliCredential


def make_real_llm(
    *,
    model: str | None = None,
    temperature: float = 0.0,
    seed: int = 42,
) -> tuple[Callable[[ChatContext], Awaitable[None]], Callable[[], Awaitable[None]]]:
    """Build a ``(call_next, aclose)`` pair backed by a real LLM.

    The returned ``call_next`` matches the shape ``ChatMiddleware.process``
    expects: it takes a ``ChatContext`` and writes the LLM result onto
    ``context.result``.

    The caller MUST ``await aclose()`` when finished to release the
    credential and HTTP transports cleanly.

    Args:
        model: Model deployment name. Falls back to
            ``$AZURE_AI_MODEL_DEPLOYMENT_NAME`` then framework default.
        temperature: Passed to every call. ``0`` for determinism.
        seed: Passed to every call when supported by the backend.
    """
    credential = AzureCliCredential()
    deployment = model or os.getenv("FOUNDRY_MODEL")
    client_kwargs: dict[str, Any] = {"credential": credential}
    if deployment:
        client_kwargs["model"] = deployment
    client = FoundryChatClient(**client_kwargs)
    options = ChatOptions(temperature=temperature, seed=seed)

    async def real_llm(context: ChatContext) -> None:
        response = await client.get_response(
            messages=context.messages,
            options=options,
        )
        context.result = response

    async def aclose() -> None:
        # Best-effort cleanup — different framework versions expose
        # different lifecycle methods on the client.
        for attr in ("aclose", "close"):
            fn = getattr(client, attr, None)
            if fn is not None:
                try:
                    result = fn()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    pass
                break
        try:
            await credential.close()
        except Exception:
            pass

    return real_llm, aclose
