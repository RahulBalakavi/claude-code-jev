# Claude Code × Jev

Auto-mode classifies every action before Claude Code runs it: `allow`, `block`,
or `ask`. That gate fires dozens of times an hour, in the hot path, ahead of
every tool call. It is a System 1 job, a fast reflex, but it runs on a System 2
model, a frontier chat model built for reasoning.

This repository runs that gate on a System 1 model instead. Jev is a
purpose-built classifier that returns a typed decision with calibrated
confidence. It installs as a `PreToolUse` hook and reaches Jev through
OpenRouter's typed decisions endpoint.

Anthropic's own auto-mode design already leans this way: the first stage emits a
single-token decision and only calls reasoning for flagged actions. The point
here is to make that first stage an actual reflex model, and keep the reasoning
model for the flagged minority where it earns its cost.

## Reflex on a reflex model

A System 2 model reasons; it is flexible and slow. A System 1 model recognizes;
it is narrow and fast. Permission gating wants recognition. Below is what you get
when a reflex task runs on a reflex model, measured over five passes of the
18-case fixture (90 live decisions, `typesafe/jev-1.13`).

For a ~540-token classification call:

| | System 2 (chat model as classifier) | System 1 (Jev) | Win |
|---|---|---|---:|
| Latency | ~4 s (LLM-judge baseline) | 264 ms | **~93% lower** |
| Cost per call | ~$0.0022 (frontier, same context) | $0.0000227 | **~99% lower** |
| Accuracy on the typed task | reference | 80-81% match, **0 dangerous allowed** | held |

Read those honestly:

- **Latency ~93% lower** is against a published LLM-judge baseline, not a live
  measurement of Claude Code's own classifier. Against a bare single-token
  frontier call the gap is smaller, but you still skip frontier queueing and
  time-to-first-token.
- **Cost ~99% lower** (about 100×) is the durable win. A purpose-built classifier
  is not priced like a frontier model, however few tokens you make that model
  emit.
- **Accuracy is held, not traded.** A fast gate that allows an unsafe action is
  worse than a slow one. The fixture shows zero dangerous actions allowed.

## The numbers

Measured over five passes of the 18-case fixture (90 live decisions through
OpenRouter, model `typesafe/jev-1.13`).

### Latency

```
Permission-gate latency, lower is better

LLM-judge reference   ████████████████████████████████████████  4000 ms
Jev, measured mean    ███                                        264 ms
```

| | p50 | p95 | mean |
|---|---:|---:|---:|
| Jev via OpenRouter | 230.8 ms | 459.2 ms | 263.9 ms |

The 4-second comparison point is a published [LLM-judge
evaluation](https://agent.nexus/blog/jev-the-model-that-decides), not a live
measurement of Claude Code's own classifier. Treat the 93% as a candidate against
a published reference, not a controlled replacement test.

### Cost

| Per decision | Per day (500 calls) | Per month (22 days) |
|---:|---:|---:|
| $0.0000227 | $0.011 | $0.25 |

At the fixture size, 90 decisions cost $0.0020454 total, with 48,700 input tokens
and 3,420 output tokens.

### What that adds up to, and when

These savings apply in one case: you already run a slow LLM-based permission gate
(the ~4-second baseline) and swap Jev in for it. Stock Claude Code auto-mode is
already fast and has no supported override, so adding this hook on top of it adds
a 264 ms hop rather than removing one. The numbers below describe replacing a
slow gate, not adding one.

If you are replacing a 4-second gate, at 500 guarded calls across an 8-hour day:

| | Value |
|---|---:|
| Wall-clock returned | 31.1 min/day |
| End-to-end duration | 6.1% lower |

The gate runs on OpenRouter and spends none of your Claude plan quota. Whether
that returned wall-clock becomes more work depends on your plan, which the next
section covers.

## How it works

```
user messages ─┐
tool call ─────┼──▶ PreToolUse hook ──▶ Jev decision + confidence
working dir ───┘                          ├─ allow  (auto-approve)
                                          ├─ block  (deny, keep going)
                                          └─ ask    (human review)
```

The hook sends three things and nothing else: the recent user messages from the
transcript, the requested tool name and its arguments, and the working
directory. Assistant reasoning and tool outputs are left out on purpose, so an
agent cannot talk its own permission gate into a `yes`.

A low-confidence answer becomes `ask`. So does any network or API failure. The
default confidence threshold is `0.85`. The fail-safe is always human review, so
a broken classifier slows you down rather than opening a hole.

The typed request and response contract matches the one merged into agentapp in
[PR #12981](https://github.com/A79-ai/agentapp/pull/12981).

## Install

You need Python 3.11+, an OpenRouter API key, and Claude Code with hooks.

```bash
git clone https://github.com/RahulBalakavi/claude-code-jev.git
cd claude-code-jev
uv tool install .
export OPENROUTER_API_KEY=...
```

Copy the hook group from
[`examples/claude-settings.json`](examples/claude-settings.json) into
`.claude/settings.json` for one project, or `~/.claude/settings.json` for all of
them. Keep Claude Code in its normal permission mode. An `allow` auto-approves
the call, `block` denies it, and `ask` leaves human review in place.

The example matcher covers mutating and boundary-crossing tools. Edit the tool
list to fit your threat model.

## Route Claude Code itself through OpenRouter

OpenRouter exposes an Anthropic-compatible Messages API, so Claude Code can use
it without a proxy. Bring your own key and use the launcher:

```bash
export OPENROUTER_API_KEY=...
./bin/claude-openrouter
```

It sets `ANTHROPIC_BASE_URL` to OpenRouter, uses `ANTHROPIC_AUTH_TOKEN` for
gateway auth, empties `ANTHROPIC_API_KEY` so nothing falls back to direct
Anthropic auth, passes `OPENROUTER_API_KEY` through to the hook, and points
`CLAUDE_CONFIG_DIR` at `~/.claude-openrouter` to keep this separate from an
existing Claude login. The launcher never writes the key to disk.

Inside Claude Code, `/status` should show `ANTHROPIC_AUTH_TOKEN` and
`https://openrouter.ai/api`. This routes model traffic. It does not replace
Claude Code's built-in auto-mode classifier, which has no supported override, so
keep the Jev hook as your permission gate and keep Claude Code in normal
permission mode.

## Run the benchmark

The fixture has 18 labeled tool calls: ordinary development, destructive actions,
credential exfiltration, production changes, and ambiguous authorization.

```bash
export OPENROUTER_API_KEY=...
jev-auto-mode benchmark --provider jev \
  --fixture fixtures/actions.jsonl \
  --output benchmark-results/jev.json
```

There are two comparison arms. `--provider haiku` runs the same policy through
`anthropic/claude-haiku-4.5` on OpenRouter. `--provider anthropic` (needs
`ANTHROPIC_API_KEY`) runs a Sonnet policy replica. The Sonnet arm is a replica
for A/B work, not Anthropic's production auto-mode classifier.

The fixture is synthetic and good for smoke testing. Replace it with blindly
labeled real tool calls before you claim anything about accuracy on your traffic.

## What this means for your plan

The gate is billed on OpenRouter, about $0.0000227 per decision. It runs outside
Claude, so it consumes zero Claude plan quota and never counts against a Pro or
Max weekly limit. Your plan meters Claude model usage, shared across Claude and
Claude Code. The gate does not add to or subtract from that meter.

So the value of a faster gate depends on what limits you:

- **You pay per token (API).** Time is the constraint. A faster gate returns
  wall-clock you can spend on real work. The calculator below estimates how much.
- **You max out a Max plan.** Your weekly usage cap is the constraint, not the
  clock. Saved gate seconds do not turn into more output, because you are capped
  by usage, not speed. You reach the same weekly cap with less waiting. The gate
  cost stays separate: a heavy week of, say, 2,500 guarded calls is about six
  cents on OpenRouter, none of it against your Max limit.

### Calculate the wall-clock case

Meaningful only if you are replacing an existing slow gate and time is your
constraint:

```bash
jev-auto-mode capacity \
  --baseline-ms 4000 \
  --candidate-ms 263.9 \
  --tool-calls 500 \
  --tokens-per-second 25 \
  --non-classifier-minutes 480
```

`baseline-ms` is the latency of the gate you have today, `candidate-ms` is Jev's
measured latency, `tool-calls` is guarded calls per day, `tokens-per-second` is
your effective main-model throughput, and `non-classifier-minutes` is the working
minutes in your day that are not gate time.

## Safety policy

The policy follows the public auto-mode categories. Block anything that can
destroy or exfiltrate data, weaken security or monitoring, cross a trust
boundary, or hit shared infrastructure. Allow low-risk or clearly authorized
actions. Ask when scope or ownership is unclear.

Tune the `0.85` threshold on a held-out set. Track false negatives on dangerous
actions and false positives on benign ones separately. A fast gate that lets an
unsafe action through is not an improvement.

## Data handling

The hook sends recent user messages, the tool name, the full tool arguments, and
the working directory to OpenRouter. Tool arguments can hold source code,
commands, URLs, or secrets. Do not deploy the hook where sending that data
violates your policy.

The local metrics log stores only a tool name, an action hash, and aggregate
decision telemetry. It does not store the transcript or the raw arguments.

Jev's calibrated confidence and a chat model's self-reported confidence do not
mean the same thing. Tune thresholds per provider on held-out data.

## Test

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The 264 ms and 81.1%-match figures above come from a 0.85-threshold, five-pass
live run against the OpenRouter Jev endpoint. See
[`results/openrouter-live-2026-09-18.md`](results/openrouter-live-2026-09-18.md).

## Sources

- [Anthropic: How we built Claude Code auto mode](https://www.anthropic.com/engineering/claude-code-auto-mode)
- [Anthropic: Connect Claude Code to an LLM gateway](https://code.claude.com/docs/en/llm-gateway)
- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
- [OpenRouter: Claude Code integration](https://openrouter.ai/docs/cookbook/coding-agents/claude-code-integration)
- [OpenRouter: Jev 1.13](https://openrouter.ai/typesafe/jev-1.13)
- [agentapp PR #12981: OpenRouter decisions support](https://github.com/A79-ai/agentapp/pull/12981)
- [Independent Jev guardrail evaluation](https://agent.nexus/blog/jev-the-model-that-decides)

## License

MIT
