"""Paired-sample latency harness.

Per the rubber-duck review (issue #2), control and treatment arms are
measured *back-to-back on the same message*, with the within-pair order
randomised to defeat sequencing effects. This makes the paired Wilcoxon
signed-rank test in :mod:`pii_bench.stats` valid.
"""

from __future__ import annotations

import asyncio
import random
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agent_framework import ChatContext

from bankingbuddy.middleware import PiiMappingStore, PiiShieldChatMiddleware

from .config import BenchConfig
from .ctx_factory import make_chat_context
from .fake_llm import make_fake_llm
from .workload import WorkloadMessage


LlmFactory = Callable[[], Callable[[ChatContext], Awaitable[None]]]


@dataclass(frozen=True)
class Sample:
    arm: str           # "control" | "with_middleware"
    sample_idx: int
    message_id: str
    latency_ms: float


def _new_middleware(cfg: BenchConfig) -> PiiShieldChatMiddleware:
    """Construct a fresh middleware bound to a fresh mapping store, so
    samples don't accidentally share cross-turn state."""
    return PiiShieldChatMiddleware(
        mode="api",
        api_url=cfg.pii_shield_api_url,
        api_app_id=cfg.pii_shield_app_id or None,
        api_timeout=cfg.pii_shield_api_timeout,
        mapping_store=PiiMappingStore(),
    )


async def _measure_one(
    arm: str,
    user_text: str,
    fake_llm: Callable,
    middleware: PiiShieldChatMiddleware | None,
) -> float:
    """Measure a single turn. Returns wall-clock latency in ms."""
    ctx = make_chat_context(user_text)

    if arm == "control":
        # Baseline: just the fake LLM, no middleware in the path at all.
        t0 = time.perf_counter_ns()
        await fake_llm(ctx)
        return (time.perf_counter_ns() - t0) / 1e6

    assert middleware is not None
    middleware._current_run_state = None  # match the per-run reset done by the UI.
    t0 = time.perf_counter_ns()
    await middleware.process(ctx, lambda: fake_llm(ctx))
    return (time.perf_counter_ns() - t0) / 1e6


async def _noop_llm(_ctx: ChatContext) -> None:
    """A zero-cost LLM stand-in for middleware-only measurements.

    Used when ``cfg.measure == "middleware-only"`` to isolate the
    middleware's HTTP-bound overhead from any LLM jitter.
    """
    return None


async def _run_one_pair(
    pair_idx: int,
    msg: WorkloadMessage,
    cfg: BenchConfig,
    fake_llm: Callable,
    rng: random.Random,
    middleware_only: bool,
) -> tuple[int, dict[str, float]]:
    """Execute a single paired sample and return its two latencies.

    A fresh middleware (and therefore a fresh aiohttp session) is built
    per pair so that concurrent pairs cannot race on the middleware's
    per-run state. Within a pair the two arms run strictly back-to-back.
    """
    middleware = _new_middleware(cfg)
    try:
        arms = ["control", "with_middleware"]
        rng.shuffle(arms)
        latencies: dict[str, float] = {}
        for arm in arms:
            latency = await _measure_one(arm, msg.text, fake_llm, middleware)
            latencies[arm] = latency
        return pair_idx, latencies
    finally:
        try:
            await middleware.aclose()
        except Exception:  # pragma: no cover — best-effort cleanup
            pass


async def run_paired(
    cfg: BenchConfig,
    workload: list[WorkloadMessage],
    on_progress: Callable[[int, int, str], None] | None = None,
    llm_factory: LlmFactory | None = None,
) -> list[Sample]:
    """Paired control vs treatment, looping over the workload.

    Each pair: pick a message, run BOTH arms on it (order randomised),
    record both latencies. Iterate until ``cfg.samples`` *pairs* are
    collected, plus ``cfg.warmup`` discarded warm-up pairs.

    When ``cfg.concurrency > 1``, multiple pairs are executed
    concurrently via ``asyncio.gather``, bounded by a semaphore. The
    two arms within a single pair are still measured strictly
    back-to-back so the within-pair variance-cancellation property is
    preserved; only across-pair execution is parallelised.

    ``on_progress(done, total, phase)`` is invoked after each completed
    pair, with ``phase`` set to ``"warmup"`` or ``"measure"``.

    ``llm_factory`` returns the ``call_next`` coroutine to use for the
    LLM step. Defaults to the yielding fake LLM. When
    ``cfg.measure == "middleware-only"`` the LLM step is forced to a
    no-op regardless of ``llm_factory``.
    """
    rng = random.Random(cfg.seed)
    middleware_only = getattr(cfg, "measure", "end-to-end") == "middleware-only"

    if middleware_only:
        fake_llm = _noop_llm
    else:
        if llm_factory is None:
            llm_factory = lambda: make_fake_llm(cfg.llm_delay_ms, cfg.llm_yield_chunks)
        fake_llm = llm_factory()

    total_pairs = cfg.warmup + cfg.samples
    concurrency = max(1, getattr(cfg, "concurrency", 1))
    sem = asyncio.Semaphore(concurrency)
    results: dict[int, dict[str, float]] = {}
    failed: list[tuple[int, str]] = []
    completed = 0

    async def _bounded(pair_idx: int) -> None:
        nonlocal completed
        msg = workload[pair_idx % len(workload)]
        try:
            async with sem:
                idx, latencies = await _run_one_pair(
                    pair_idx, msg, cfg, fake_llm, rng, middleware_only,
                )
            results[idx] = latencies
        except Exception as exc:  # noqa: BLE001 — we want to keep going
            failed.append((pair_idx, f"{type(exc).__name__}: {exc}"))
        finally:
            completed += 1
            if on_progress is not None:
                phase = "warmup" if pair_idx < cfg.warmup else "measure"
                on_progress(completed, total_pairs, phase)

    await asyncio.gather(*(_bounded(i) for i in range(total_pairs)))

    if failed:
        # Drop failed pairs but tell the user how many and why. Most
        # commonly this is the PII Shield server saturating under high
        # --concurrency; the surviving samples are still valid.
        print()
        print(f"  ⚠ dropped {len(failed)} pair(s) due to errors:", file=sys.stderr)
        seen: dict[str, int] = {}
        for _, reason in failed:
            seen[reason] = seen.get(reason, 0) + 1
        for reason, count in sorted(seen.items(), key=lambda kv: -kv[1])[:5]:
            print(f"      {count:4d}× {reason}", file=sys.stderr)
        if len(failed) > cfg.samples * 0.10:
            print(
                "    >10% of pairs failed — consider lowering --concurrency "
                "or raising PII_SHIELD_API_TIMEOUT.",
                file=sys.stderr,
            )

    samples: list[Sample] = []
    for pair_idx in range(cfg.warmup, total_pairs):
        if pair_idx not in results:
            continue
        msg = workload[pair_idx % len(workload)]
        latencies = results[pair_idx]
        for arm, latency in latencies.items():
            samples.append(Sample(
                arm=arm,
                sample_idx=pair_idx - cfg.warmup,
                message_id=msg.id,
                latency_ms=latency,
            ))
    return samples
