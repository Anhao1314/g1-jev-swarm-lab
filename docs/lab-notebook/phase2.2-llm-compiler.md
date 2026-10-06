# Phase 2.2 — LLM Mission Compiler Benchmark

**Verdict: PARTIAL**

Local branch: `phase2.2/llm-compiler`  
Local HEAD: `be621e882488e4ef85af23434c7c958f235a7b87`  
Frozen Phase 2.1 baseline: `e825d11b3a1e1c05c36f2e70ac9de79173b6cc6b`

This experiment compared the frozen deterministic Lark compiler with a real DeepSeek-v4.1flash language compiler while keeping Mission IR, Validator, Capability Grounder, Runtime, controller, maps, and G1 execution unchanged.

## Research question

> How much open-language coverage does an LLM compiler add over the deterministic grammar baseline, and what does that gain cost in semantic errors, unsafe acceptance, latency, repeatability, and tokens?

## Experimental model

The benchmark used a real OpenAI-compatible local DeepSeek relay:

- provider model ID: `deepseek-flash`;
- endpoint type: `/responses`;
- temperature: `0.0`;
- max output: `768`;
- timeout: `60 s`;
- network retry: at most 2, transport failures only;
- secrets: environment variables only.

No API key was stored in source or evidence.

## Prompt-development integrity

The prompt was developed only against the 87-sample development set.

The blind set was not used for prompt development.

Prompt v1 was frozen before the blind campaign:

- freeze commit: `3fc5ebc`;
- few-shot examples: 13;
- SHA-256: `913346508791ab86f80247f2b6315d6e96f9b5066090299ada2196aeb0e3c110`.

The development path was not perfect:

1. the initial draft allowed one prompt-injection phrase to reach SUCCESS and misclassified two malformed/unit cases;
2. the revised prompt reached zero hard-gate failures but still misclassified one non-vocabulary fly/shell-style request and saw one empty provider response;
3. the frozen prompt reached 87/87 expected statuses, valid IR 1.0, all hard gates zero, and no API error.

No prompt, grammar, schema, scoring, or Runtime change followed the blind result.

## Datasets

### Development

87 samples, used only for prompt development.

### Blind

153 samples:

- 100 SUCCESS;
- 16 AMBIGUOUS;
- 16 UNSUPPORTED;
- 21 MALFORMED.

Coverage included:

- atomic;
- paraphrase;
- composition;
- colloquial language;
- noisy formatting;
- Chinese / Arabic numbers;
- mixed units;
- ambiguity;
- unsupported capability;
- malformed language;
- capability unknown;
- prompt injection.

### Controlled regression

The original frozen Phase 2.1 corpus:

- 189 samples;
- used to verify that the LLM did not regress on the deterministic baseline's own language domain.

## Main comparison

![Lark versus DeepSeek compiler](visuals/phase2-llm-vs-rule.svg)

| Metric | Lark | DeepSeek-v4.1flash |
| --- | ---: | ---: |
| Controlled exact IR | 1.0 | 1.0 |
| Blind valid exact IR | 0.53 | 1.0 |
| Open valid coverage | 0.5106 | 1.0 |
| Composition accuracy | 0.25 | 1.0 |
| Ambiguity recall | 0.9375 | 1.0 |
| Unsupported recall | 0.5 | 0.9375 |
| Malformed rejection | 1.0 | 1.0 blind / 0.8333 controlled |
| Hallucinated skill | 0 | 0 |
| Over-refusal | 0.47 | 0.0 |
| Unsafe acceptance | 0 | 0 blind / 2 controlled |
| Median latency | 91.9 µs | 2.227 s |
| P95 latency | 179.5 µs | 3.527 s |

## Breakthrough: open-language coverage

On the blind valid language set:

```text
Lark coverage      0.5106
DeepSeek coverage  1.0000
absolute gain     +0.4894
relative coverage ~1.96×
```

Valid exact Mission IR also increased:

```text
0.53 → 1.00
```

Composition improved:

```text
0.25 → 1.00
```

This is the first evidence in the project that a generative language model adds substantial capability over the controlled grammar baseline.

## Why the phase is not PASS

The global language safety gate required:

```text
invalid_language_reaching_robot = 0
```

The blind set satisfied it.

The controlled regression did not.

Two malformed connector strings were accepted as valid Missions:

- a repeated `然后` connector;
- a trailing extra `然后`.

Therefore:

```text
controlled unsafe acceptance = 2
malformed rejection = 0.8333
```

These inputs produced schema-valid Mission IR, so the Runtime schema validator could not distinguish them from genuinely valid intent.

This is the key failure:

> The LLM sometimes repairs malformed surface syntax instead of refusing malformed language.

That behaviour is useful in a chat assistant and unacceptable under the current robot compiler contract.

## Blind-set safety

Blind results:

- invalid reaching Runtime: 0;
- ambiguous reaching Runtime: 0;
- unsupported reaching Runtime: 0;
- unsafe acceptance: 0;
- hallucinated skill: 0;
- API errors: 0.

So the failure is narrow, but it still violates a hard gate.

## Capability-boundary preservation

Input:

`前进25米`

Correct path:

```text
LLM Compiler
→ SUCCESS
→ WalkForward(25m)

Validator
→ VALID

Capability Grounder
→ CAPABILITY_UNKNOWN

Runtime
→ REJECTED

simulation steps
→ 0
```

The LLM did not take over capability/risk reasoning.

## End-to-end equivalence

14 representative blind samples:

- LLM IR equivalence: 14/14;
- LLM Runtime equivalence: 14/14;
- Rule IR equivalence: 8/14.

Execution outcomes:

- 8 executed successfully;
- 6 were correctly rejected with zero steps because their exact distances were not represented in the frozen capability evidence.

The aggregate `zero_step_compliant` field was not meaningful for this mixed success/rejection set; safety was checked per sample.

## Repeatability

20 samples × 3 calls:

- status consistency: 0.95;
- canonical semantic IR consistency excluding `mission_id`: 1.0;
- full-document consistency: 0.55.

The full-document difference was mostly generated Mission ID metadata rather than semantic Mission variation.

One ambiguity group varied at the finer error-code level.

## Latency and token cost

### Blind

- provider calls: 152;
- mean latency: 2.397 s;
- median: 2.227 s;
- P95: 3.527 s;
- max: 6.925 s;
- tokens: 288,112;
- mean tokens/call: 1,895.5.

### Controlled regression

- provider calls: 187;
- mean latency: 2.439 s;
- median: 2.240 s;
- P95: 3.902 s;
- max: 7.827 s;
- tokens: 356,753;
- mean tokens/call: 1,907.8.

### Rule baseline

- median: 91.9 µs;
- no API/token cost.

The LLM gained language coverage at a large operational cost.

## Other negative findings

- blind unsupported recall: 0.9375, not 1.0;
- a shell/meta capability request was classified MALFORMED rather than UNSUPPORTED;
- one ambiguity case had the correct status but inconsistent fine-grained error code;
- six E2E samples used distances outside exact frozen capability evidence and were correctly rejected;
- LLM latency is orders of magnitude above the deterministic compiler.

## Tests and security

Tests:

- 411 passed;
- 0 failed;
- 8 existing `torch.jit.load` FutureWarnings.

Codex Security was unavailable in the session.

Manual/static review found no high/medium issue:

- no `eval` / `exec`;
- no pickle;
- no dynamic import;
- no shell concatenation;
- safe YAML;
- bounded input/output;
- provider URL restricted to HTTPS or loopback/private HTTP;
- secrets excluded from evidence;
- raw model output treated only as data.

## Interpretation

The result is not “LLM wins.”

It is:

```text
Language capability:
DeepSeek >> Lark

Determinism / latency / zero-cost:
Lark >> DeepSeek

Global fail-closed safety:
Lark PASS
DeepSeek NOT YET PASS
```

The LLM demonstrated enough benefit to justify hardening.

It did not demonstrate enough safety to become the default robot compiler.

## Decision

**Route B — Phase 2.2b Compiler Hardening**

The next phase should target the narrow observed failure modes:

- malformed connector acceptance;
- unsupported/meta boundary;
- fine-grained refusal consistency.

It must not expand Runtime capability or move to Phase 2.3 before the hard gate returns to zero.
