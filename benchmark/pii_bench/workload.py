"""Workload loader. Reads ``messages.jsonl`` into typed records."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class WorkloadMessage:
    id: str
    scenario: str
    length_bucket: str   # "short" | "med" | "long"
    density_bucket: str  # "low" | "med" | "high"
    n_entities: int
    text: str


def load(path: Path) -> list[WorkloadMessage]:
    if not path.exists():
        raise FileNotFoundError(
            f"workload file not found: {path}. "
            "Run `python -m pii_bench generate` to create it."
        )
    out: list[WorkloadMessage] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                out.append(WorkloadMessage(
                    id=obj["id"],
                    scenario=obj["scenario"],
                    length_bucket=obj["length_bucket"],
                    density_bucket=obj["density_bucket"],
                    n_entities=int(obj["n_entities"]),
                    text=obj["text"],
                ))
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"malformed workload row at {path}:{line_no}: {exc}"
                ) from exc
    if not out:
        raise ValueError(f"workload file is empty: {path}")
    return out


def with_unique_suffix(messages: Iterable[WorkloadMessage]) -> list[WorkloadMessage]:
    """Append a UUID to each message body so server-side caches cannot hit.

    The suffix is hidden inside a marker that's unlikely to be detected as
    PII (no entity-shaped tokens). The structural buckets stay valid.
    """
    out: list[WorkloadMessage] = []
    for msg in messages:
        nonce = uuid.uuid4().hex[:12]
        new_text = f"{msg.text}\n\n[ref:{nonce}]"
        out.append(WorkloadMessage(
            id=msg.id,
            scenario=msg.scenario,
            length_bucket=msg.length_bucket,
            density_bucket=msg.density_bucket,
            n_entities=msg.n_entities,
            text=new_text,
        ))
    return out
