"""Capture an environment fingerprint stamped into every result file.

The fingerprint is what makes a benchmark run *reproducible* and
*comparable*. Without it, a results file is unreadable a month later.
"""

from __future__ import annotations

import datetime as _dt
import os
import platform
import socket
import subprocess
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EnvFingerprint:
    captured_at_utc: str
    hostname: str
    os: str
    os_release: str
    cpu_brand: str
    cpu_count_logical: int
    cpu_count_physical: int | None
    memory_total_mb: int | None
    python_version: str
    python_implementation: str
    git_commit: str | None
    git_dirty: bool
    pii_shield_api_url: str
    pii_shield_image: str | None
    benchmark_version: str

    def as_markdown(self) -> str:
        rows = []
        for key, value in asdict(self).items():
            rows.append(f"| `{key}` | {value} |")
        return "| field | value |\n|---|---|\n" + "\n".join(rows)


def _read_cpu_brand() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _read_physical_cores() -> int | None:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as fh:
            siblings = set()
            for line in fh:
                if line.startswith("core id"):
                    siblings.add(line.split(":", 1)[1].strip())
            if siblings:
                return len(siblings)
    except OSError:
        pass
    return None


def _read_memory_mb() -> int | None:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _git_commit() -> tuple[str | None, bool]:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None, False

    try:
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip())
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        dirty = False
    return sha, dirty


def capture(pii_shield_api_url: str) -> EnvFingerprint:
    from pii_bench import __version__ as bench_version

    sha, dirty = _git_commit()
    return EnvFingerprint(
        captured_at_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        hostname=socket.gethostname(),
        os=platform.system(),
        os_release=platform.release(),
        cpu_brand=_read_cpu_brand(),
        cpu_count_logical=os.cpu_count() or 0,
        cpu_count_physical=_read_physical_cores(),
        memory_total_mb=_read_memory_mb(),
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        git_commit=sha,
        git_dirty=dirty,
        pii_shield_api_url=pii_shield_api_url,
        pii_shield_image=os.getenv("PII_SHIELD_IMAGE"),
        benchmark_version=bench_version,
    )
