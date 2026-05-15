# PII Shield Middleware Benchmark

Answers exactly one question:

> **How many milliseconds does the `PiiShieldChatMiddleware` add per
> agent turn?**

Measured over 1000 paired runs (default), in API mode, against a
locally docker-deployed PII Shield service.

## How it works

For each pair of runs the harness executes the same user message twice
— once through the middleware and once without — back-to-back, with the
within-pair order randomised. The middleware overhead is the difference
of the two latencies, so any LLM/network jitter cancels out.

By default the harness uses a **real LLM** (`FoundryChatClient` via
`AzureCliCredential`, the same client the BankingBuddy agent uses).
Pass `--llm fake` (or set `BENCH_LLM=fake`) to substitute an
`asyncio.sleep` for the LLM call — useful for quick iteration on the
harness itself or when you don't want to spend on LLM calls.

## Quickstart

```bash
cd benchmark/

# 1. Install benchmark deps + the parent package (for the middleware code).
pip install -e .
pip install -e ..

# 2. Configure the PII Shield endpoint, the docker image, and your Foundry
#    deployment (see .env.example for all knobs).
cp .env.example .env
$EDITOR .env

# 3. Bring up PII Shield in docker.
docker compose up -d pii-shield

# 4. (Once) generate the synthetic workload.
python -m pii_bench generate

# 5. Verify the service.
python -m pii_bench probe

# 6. Authenticate to Azure (real LLM is the default).
az login

# 7. Run the benchmark.
python -m pii_bench run                              # default: real LLM, end-to-end Δ
python -m pii_bench run --samples 50                 # quick smoke (100 LLM calls, ~2 min)
python -m pii_bench run --llm fake                   # no LLM cost, deterministic Δ
python -m pii_bench run --measure middleware-only    # cleanest signal: LLM bypassed
```

Output goes to `results/`:

```
results/
├── env.json          # full environment fingerprint
├── raw_samples.csv   # one row per measured latency (slice further if you want)
└── summary.md        # the headline number + per-arm percentiles + env
```

## What the output looks like

The terminal prints the headline at the end:

```
────────────────────────────────────────────────────────────
  PII Shield middleware overhead  (1000 paired runs)
────────────────────────────────────────────────────────────
  median       8.12 ms
  p95         11.43 ms
  p99         14.20 ms
  mean         8.65 ms
────────────────────────────────────────────────────────────
  LLM in this run: fake (asyncio.sleep 300 ms)
```

`summary.md` adds a per-arm table (no-middleware vs with-middleware
absolute latencies) and the environment fingerprint, so the run is
reproducible and comparable later.

## Useful flags

| Flag | Default | Purpose |
| --- | --- | --- |
| `--samples` | 1000 | Number of paired runs |
| `--warmup` | 50 | Discarded warm-up pairs |
| `--llm-delay-ms` | 300 | Fake LLM delay (only used with `--llm fake`) |
| `--no-unique-messages` | (off) | Allow server-side caching to take effect |
| `--llm` | `real` | LLM backend: `real` (default) or `fake`. Ignored when `--measure middleware-only`. |
| `--measure` | `end-to-end` | `end-to-end`: paired Δ includes the LLM step (real-LLM jitter inflates p95/p99). `middleware-only`: LLM is replaced with a no-op so Δ is purely middleware overhead — use this for the cleanest measurement. |
| `--concurrency` | 1 | Number of paired samples in flight at once. Within a pair the two arms still run strictly back-to-back; only across-pair execution is parallelised. Bumps wall-time speedup nearly linearly with the real LLM (where each call costs seconds), and ~3-5× under `middleware-only` before the PII Shield server saturates. |
| `--api-url` | from env | Override `PII_SHIELD_API_URL` |
| `--out-dir` | `results` | Where to write CSV + summary |

## Cost & time with the real LLM (default)

Each paired run = 2 LLM calls. At ~1.5 s per call (sequential):

| `--samples` | LLM calls | Wall time (`--concurrency 1`) | Wall time (`--concurrency 10`) |
| --- | --- | --- | --- |
| 50 (quick smoke) | 100 | ~2-3 min | ~30 s |
| 200 | 400 | ~10 min | ~1-2 min |
| 1000 (default) | 2000 | ~50-60 min | ~5-7 min |

The Δ overhead remains valid regardless of LLM latency — the LLM
contribution cancels out in the paired difference. Per-arm absolute
latencies will be ~1-2 s and dominated by the LLM, while the headline
middleware overhead is single-digit milliseconds on top.

To skip the LLM entirely (no `az login`, no cost, deterministic):

```bash
python -m pii_bench run --llm fake
```

## What this benchmark does NOT measure

* Concurrent throughput (deliberately out of scope here)
* Library mode (in-process) — only API mode
* End-to-end agent runs with multiple tool calls — only one
  `ChatMiddleware.process` invocation per measured turn

## Layout

```
benchmark/
├── README.md, pyproject.toml, .env.example, compose.yml
├── data/
│   ├── README.md                # synthetic-data conventions
│   └── messages.jsonl           # generated workload
└── pii_bench/
    ├── __main__.py              # CLI: generate | probe | run
    ├── config.py, env.py
    ├── workload.py, generate_data.py
    ├── fake_llm.py, real_llm.py, ctx_factory.py
    ├── service_probe.py         # /health probe only
    ├── harness.py               # paired single-coroutine harness
    ├── progress.py              # live console progress bar
    ├── stats.py                 # mean + p50/p95/p99
    └── report.py                # CSV + markdown writers
```
