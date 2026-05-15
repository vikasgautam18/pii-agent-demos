"""Centralised, env-driven configuration. No values are hardcoded — every
knob can be overridden via environment variables (loaded from a local
``.env`` if present) or via the CLI flags exposed in :mod:`pii_bench.__main__`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw is not None else default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_list_int(name: str, default: list[int]) -> list[int]:
    raw = _env(name)
    if raw is None:
        return list(default)
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class BenchConfig:
    """Resolved benchmark configuration."""

    # PII Shield endpoint
    pii_shield_api_url: str
    pii_shield_app_id: str
    pii_shield_api_timeout: int

    # Workload
    data_file: Path
    out_dir: Path
    samples: int
    warmup: int
    unique_messages: bool

    # Fake LLM
    llm_delay_ms: int
    llm_yield_chunks: int

    # Reproducibility
    seed: int

    # Measurement mode: "end-to-end" (default — paired Δ includes LLM step)
    # or "middleware-only" (LLM is replaced with a no-op so Δ is pure
    # middleware overhead, free of LLM jitter).
    measure: str = "end-to-end"

    # How many paired samples to execute concurrently. Within each pair
    # the two arms still run strictly back-to-back (preserving the
    # within-pair pairing); only across-pair execution is parallelised.
    # Useful with the real LLM, where each call takes seconds.
    concurrency: int = 1

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "BenchConfig":
        """Load configuration. Reads ``.env`` next to the benchmark folder
        if no explicit ``env_file`` is provided."""
        if env_file is not None:
            load_dotenv(env_file, override=False)
        else:
            for parent in [Path.cwd(), *Path.cwd().parents]:
                candidate = parent / ".env"
                if candidate.is_file():
                    load_dotenv(candidate, override=False)
                    break

        return cls(
            pii_shield_api_url=_env("PII_SHIELD_API_URL", "http://localhost:8000"),
            pii_shield_app_id=_env("PII_SHIELD_APP_ID", "") or "",
            pii_shield_api_timeout=_env_int("PII_SHIELD_API_TIMEOUT", 120),
            data_file=Path(_env("BENCH_DATA_FILE", "data/messages.jsonl")),
            out_dir=Path(_env("BENCH_OUT_DIR", "results")),
            samples=_env_int("BENCH_SAMPLES", 1000),
            warmup=_env_int("BENCH_WARMUP", 50),
            unique_messages=_env_bool("BENCH_UNIQUE_MESSAGES", True),
            llm_delay_ms=_env_int("BENCH_LLM_DELAY_MS", 300),
            llm_yield_chunks=_env_int("BENCH_LLM_YIELD_CHUNKS", 1),
            seed=_env_int("BENCH_SEED", 42),
            measure=_env("BENCH_MEASURE", "end-to-end"),
            concurrency=_env_int("BENCH_CONCURRENCY", 1),
        )

    def merge_overrides(self, **kwargs: object) -> "BenchConfig":
        """Return a new config with the given fields overridden (CLI flags)."""
        current = self.__dict__.copy()
        for key, value in kwargs.items():
            if value is None:
                continue
            if key not in current:
                raise KeyError(f"unknown config field: {key}")
            current[key] = value
        return BenchConfig(**current)
