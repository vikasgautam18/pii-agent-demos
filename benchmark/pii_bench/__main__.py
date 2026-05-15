"""CLI entry point — ``python -m pii_bench [generate|probe|run]``.

The benchmark answers exactly one question: how many milliseconds does the
``PiiShieldChatMiddleware`` add per agent turn, in API mode, against a
docker-deployed PII Shield service. Everything in this module supports
that one question and nothing else.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .config import BenchConfig
from .env import capture as capture_env
from .generate_data import generate
from .harness import run_paired
from .progress import Progress
from .report import write_fingerprint_json, write_raw_samples, write_summary_md
from .service_probe import healthcheck
from .workload import load as load_workload, with_unique_suffix


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def _cmd_generate(args: argparse.Namespace) -> int:
    out = Path(args.out)
    n = generate(
        out_path=out,
        seed=args.seed,
        short_count=args.short,
        med_count=args.med,
        long_count=args.long,
    )
    print(f"wrote {n} synthetic messages to {out}")
    return 0


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def _cmd_probe(args: argparse.Namespace) -> int:
    cfg = BenchConfig.from_env().merge_overrides(pii_shield_api_url=args.api_url)
    print(f"probing PII Shield at {cfg.pii_shield_api_url} ...")
    result = healthcheck(cfg.pii_shield_api_url, timeout=args.timeout)
    if result.ok:
        print(f"  ✓ {result.detail}  ({result.latency_ms:.1f} ms)")
        return 0
    print(f"  ✗ {result.detail}")
    print()
    print("Hint: bring the service up via:")
    print("   docker compose -f benchmark/compose.yml up -d pii-shield")
    return 1


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def _cmd_run(args: argparse.Namespace) -> int:
    cfg = BenchConfig.from_env().merge_overrides(
        pii_shield_api_url=args.api_url,
        samples=args.samples,
        warmup=args.warmup,
        llm_delay_ms=args.llm_delay_ms,
        unique_messages=args.unique_messages,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        data_file=Path(args.data_file) if args.data_file else None,
        measure=args.measure,
        concurrency=args.concurrency,
    )

    middleware_only = cfg.measure == "middleware-only"
    use_real_llm = (
        not middleware_only
        and (args.llm or os.getenv("BENCH_LLM", "real")).lower() == "real"
    )

    probe = healthcheck(cfg.pii_shield_api_url, timeout=cfg.pii_shield_api_timeout)
    if not probe.ok:
        print(f"PII Shield unreachable at {cfg.pii_shield_api_url}: {probe.detail}",
              file=sys.stderr)
        print("Bring it up with:  docker compose -f benchmark/compose.yml up -d",
              file=sys.stderr)
        return 2

    workload = load_workload(cfg.data_file)
    if cfg.unique_messages:
        workload = with_unique_suffix(workload)

    if middleware_only:
        llm_label = "no-op (middleware-only mode — LLM bypassed)"
    elif use_real_llm:
        llm_label = "FoundryChatClient (temperature=0)"
    else:
        llm_label = f"fake (asyncio.sleep {cfg.llm_delay_ms} ms)"

    print(f"workload     : {len(workload)} messages from {cfg.data_file}")
    print(f"paired runs  : {cfg.samples} (+ {cfg.warmup} warmup)")
    print(f"concurrency  : {cfg.concurrency} pair(s) in flight")
    print(f"LLM          : {llm_label}")
    print()

    fingerprint = capture_env(cfg.pii_shield_api_url)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_fingerprint_json(cfg.out_dir, fingerprint)

    llm_factory = None
    aclose_real = None
    if use_real_llm:
        from .real_llm import make_real_llm
        real_call_next, aclose_real = make_real_llm(seed=cfg.seed)
        llm_factory = lambda: real_call_next

    try:
        paired_total = cfg.warmup + cfg.samples
        pr = Progress("paired", total=paired_total)

        def _on_progress(done: int, total: int, phase: str) -> None:
            pr.current = done - 1
            pr.tick(suffix=f"({phase})")

        samples = asyncio.run(
            run_paired(cfg, workload, on_progress=_on_progress,
                       llm_factory=llm_factory)
        )
        pr.done(note=f"{len(samples)} samples")
    finally:
        if aclose_real is not None:
            asyncio.run(aclose_real())

    write_raw_samples(samples, cfg.out_dir)
    summary_path = write_summary_md(cfg.out_dir, fingerprint, samples, llm_label)

    # Echo the headline straight to the terminal so the user doesn't need
    # to open the markdown to see the answer.
    _print_headline(samples, llm_label)
    print(f"\nfull report → {summary_path}")
    return 0


def _print_headline(samples, llm_label: str) -> None:
    from .stats import summarise
    by_key: dict = {}
    for s in samples:
        by_key.setdefault((s.sample_idx, s.message_id), {})[s.arm] = s.latency_ms
    deltas = [
        a["with_middleware"] - a["control"]
        for a in by_key.values()
        if "control" in a and "with_middleware" in a
    ]
    if not deltas:
        return
    d = summarise(deltas, "Δ")
    print()
    print("─" * 60)
    print(f"  PII Shield middleware overhead  ({d.n} paired runs)")
    print("─" * 60)
    print(f"  median    {d.p50_ms:7.2f} ms")
    print(f"  p95       {d.p95_ms:7.2f} ms")
    print(f"  p99       {d.p99_ms:7.2f} ms")
    print(f"  mean      {d.mean_ms:7.2f} ms")
    print("─" * 60)
    print(f"  LLM in this run: {llm_label}")


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pii_bench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate", help="generate synthetic workload")
    p_gen.add_argument("--out", default="data/messages.jsonl")
    p_gen.add_argument("--seed", type=int, default=42)
    p_gen.add_argument("--short", type=int, default=30)
    p_gen.add_argument("--med", type=int, default=20)
    p_gen.add_argument("--long", type=int, default=10)
    p_gen.set_defaults(func=_cmd_generate)

    p_probe = sub.add_parser("probe", help="health-check the PII Shield API")
    p_probe.add_argument("--api-url", default=None)
    p_probe.add_argument("--timeout", type=int, default=5)
    p_probe.set_defaults(func=_cmd_probe)

    p_run = sub.add_parser("run", help="measure middleware overhead")
    p_run.add_argument("--api-url", default=None)
    p_run.add_argument("--samples", type=int, default=None,
                       help="paired runs (default 1000)")
    p_run.add_argument("--warmup", type=int, default=None,
                       help="discarded warmup pairs (default 50)")
    p_run.add_argument("--llm-delay-ms", type=int, default=None,
                       help="fake LLM delay (default 300 ms)")
    p_run.add_argument("--data-file", default=None)
    p_run.add_argument("--out-dir", default=None)
    p_run.add_argument("--unique-messages", dest="unique_messages",
                       action="store_true", default=None)
    p_run.add_argument("--no-unique-messages", dest="unique_messages",
                       action="store_false")
    p_run.add_argument("--llm", choices=["fake", "real"], default=None,
                       help="LLM backend (default: real). Ignored when "
                            "--measure=middleware-only.")
    p_run.add_argument("--measure", choices=["end-to-end", "middleware-only"],
                       default=None,
                       help="end-to-end (default): paired Δ includes the LLM "
                            "step (real-LLM jitter inflates p95/p99). "
                            "middleware-only: LLM is replaced with a no-op so "
                            "Δ is purely middleware overhead — use this for "
                            "the cleanest overhead measurement.")
    p_run.add_argument("--concurrency", type=int, default=None,
                       help="Number of paired samples to run concurrently "
                            "(default 1). Within each pair the two arms still "
                            "run strictly back-to-back; only across-pair "
                            "execution is parallelised. Useful for cutting "
                            "wall time with the real LLM.")
    p_run.set_defaults(func=_cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
