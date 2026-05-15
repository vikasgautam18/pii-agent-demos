"""Report writers — CSV (raw) and a deliberately small Markdown summary.

Headline question: how many ms does the middleware add per turn?
"""

from __future__ import annotations

import csv
import dataclasses
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from tabulate import tabulate

from .env import EnvFingerprint
from .harness import Sample
from .stats import Summary, summarise


def write_raw_samples(samples: Sequence[Sample], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "raw_samples.csv"
    field_names = [f.name for f in dataclasses.fields(Sample)]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=field_names)
        writer.writeheader()
        for s in samples:
            writer.writerow(dataclasses.asdict(s))
    return out_path


def _per_arm_table(rows: list[Summary]) -> str:
    table = [
        [r.label, r.n, f"{r.mean_ms:.2f}",
         f"{r.p50_ms:.2f}", f"{r.p95_ms:.2f}", f"{r.p99_ms:.2f}"]
        for r in rows
    ]
    return tabulate(
        table,
        headers=["Arm", "n", "mean", "p50", "p95", "p99"],
        tablefmt="github",
    )


def write_summary_md(
    out_dir: Path,
    fingerprint: EnvFingerprint,
    samples: list[Sample],
    llm_label: str,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "summary.md"

    control = [s.latency_ms for s in samples if s.arm == "control"]
    treatment = [s.latency_ms for s in samples if s.arm == "with_middleware"]

    # Pair up by (sample_idx, message_id) so the deltas are honest pairs.
    by_key: dict[tuple, dict[str, float]] = {}
    for s in samples:
        key = (s.sample_idx, s.message_id)
        by_key.setdefault(key, {})[s.arm] = s.latency_ms
    deltas = [
        arms["with_middleware"] - arms["control"]
        for arms in by_key.values()
        if "control" in arms and "with_middleware" in arms
    ]

    headline = ""
    if deltas:
        d = summarise(deltas, "Δ overhead")
        headline = (
            "## Headline\n\n"
            f"**PII Shield middleware adds, per turn, over {d.n} paired runs:**\n\n"
            f"- median  **{d.p50_ms:.2f} ms**\n"
            f"- p95     **{d.p95_ms:.2f} ms**\n"
            f"- p99     **{d.p99_ms:.2f} ms**\n"
            f"- mean    {d.mean_ms:.2f} ms\n\n"
            f"_LLM in this run: {llm_label}._\n"
        )

    per_arm: list[Summary] = []
    if control:
        per_arm.append(summarise(control, "no middleware"))
    if treatment:
        per_arm.append(summarise(treatment, "with middleware"))

    parts = [
        "# PII Shield Middleware — Latency Overhead",
        "",
        headline,
        "## Per-arm latency",
        "",
        _per_arm_table(per_arm) if per_arm else "_no samples_",
        "",
        "## Environment",
        "",
        fingerprint.as_markdown(),
        "",
        "_Raw per-sample data: `raw_samples.csv`._",
        "",
    ]
    out_path.write_text("\n".join(parts), encoding="utf-8")
    return out_path


def write_fingerprint_json(out_dir: Path, fingerprint: EnvFingerprint) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "env.json"
    out_path.write_text(json.dumps(asdict(fingerprint), indent=2),
                        encoding="utf-8")
    return out_path
