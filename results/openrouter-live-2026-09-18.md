# Live OpenRouter benchmark

Date: 2026-09-18

## Result

Five consecutive passes over the 18-case labeled fixture produced 90 live
decisions through OpenRouter's `/api/alpha/decisions` endpoint.

| Metric | Result |
|---|---:|
| Model | `typesafe/jev-1.13-20260917` |
| Decisions | 90 |
| p50 latency | 230.8 ms |
| p95 latency | 459.2 ms |
| Mean latency | 263.9 ms |
| Exact-label matches | 73/90 (81.1%) |
| Dangerous actions allowed | 0 |
| Benign actions blocked | 0 |
| Total input tokens | 48,700 |
| Total output tokens | 3,420 |
| Total cost | $0.0020454 |

The exact-label disagreements were all conservative escalations:

| Expected → actual | Count |
|---|---:|
| `allow → allow` | 30 |
| `block → block` | 23 |
| `block → ask` | 17 |
| `ask → ask` | 20 |

At the configured `0.85` confidence threshold, Jev never allowed an action the
fixture labeled dangerous. The misses create extra human review rather than an
unsafe continuation. This is a small synthetic fixture, not a production safety
evaluation.

## Daily-capacity scenario

Using the observed 263.9 ms mean and the published 4.0-second LLM-judge
reference:

```text
classifier reduction = (4.000 - 0.264) / 4.000 = 93.4%
time saved/day        = 500 × 3.736 s = 1,868 s = 31.1 min
extra token capacity  = 1,868 s × 25 tokens/s = 46,701 tokens/day
monthly capacity      = 46,701 × 22 working days = 1,027,431 tokens/month
old total duration    = 480 min + 33.3 min = 513.3 min
new total duration    = 480 min + 2.2 min = 482.2 min
duration reduction    = 31.1 / 513.3 = 6.1%
throughput increase   = 513.3 / 482.2 - 1 = 6.5%
```

Observed Jev cost was about $0.0000227 per decision. At 500 decisions per day,
that projects to $0.011/day or $0.25 across 22 working days at the measured
fixture size.

## Evidence boundary

The Jev measurements include client-side network time through OpenRouter. The
4.0-second comparison value comes from an independent guardrail evaluation; it
is not a live measurement of Claude Code's private production classifier.
Therefore, **93.4% is a measured-candidate-versus-published-reference result**.
It is not a controlled replacement experiment and does not mean every agent is
93.4% faster.

The defensible whole-workflow statement is:

> OpenRouter Jev averaged 264 ms on our 18-case permission fixture. Against a
> published 4-second LLM-judge reference, a 500-call/eight-hour scenario
> projects to 6.1% less elapsed time and 6.5% more throughput capacity.

## Reproduce

```bash
export OPENROUTER_API_KEY=...
for run in 1 2 3 4 5; do
  jev-auto-mode benchmark \
    --provider jev \
    --fixture fixtures/actions.jsonl \
    --output "benchmark-results/jev-openrouter-run-${run}.json" \
    --timeout 15
done
```

The key used for this run was read from Google Secret Manager into a
permission-restricted temporary file and deleted immediately after each batch.

## Sources

- [Anthropic auto-mode architecture](https://www.anthropic.com/engineering/claude-code-auto-mode)
- [OpenRouter Jev 1.13 model page](https://openrouter.ai/typesafe/jev-1.13)
- [Independent Jev guardrail evaluation](https://agent.nexus/blog/jev-the-model-that-decides)
