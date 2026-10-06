# Phase 2.1 — Controlled Language Compiler

Protocol: `configs/experiments/controlled_language_001.yaml`, SHA-256
`24b217f89016057871e702d76d36bd83324c69bfc9515fa8bf57c89cae6bda8b`.
Grammar: `src/g1swarm/language/grammar.lark`, SHA-256
`b1155a025e086adb5b7efc991af098987d5da831a1ca3c04e090f762c4760e8f`.
Corpus: `configs/language/controlled_language_001.yaml`, SHA-256
`dd9bf2b9abb450f3bc524e6489965ab83574d77f117e7980a61adab699bc10cb`.
Baseline provenance: Phase 2.0 at `7658b0c`, with Phase 1.3 at
`bea645f13b6af9ee27f902c310148d72fa69a204`. The final compiler campaign
used source commit `e483683a049e4be89b4ab972e5448d241fcbd573`.

## 1. Verdict

**PASS** on the frozen controlled-language corpus. The deterministic compiler
matched every expected language status and every canonical Mission IR, and the
11 representative language missions executed identically to their Oracle IR
counterparts through the unchanged Phase 2.0 runtime. This is a controlled
grammar baseline, not general natural-language understanding.

## 2. Baseline provenance

- Phase 2.0 frozen runtime branch: `phase2.0/mission-runtime`, HEAD `7658b0c`.
- Phase 2.1 branch: `phase2.1/controlled-language`.
- Parser dependency: `lark==1.3.1` from the official PyPI release, Python
  requirement `>=3.8`, validated on Python 3.11.9.
- No Phase 1.3 correction, policy, model, risk map, capability map or Phase 2.0
  runtime file was modified.

## 3. Parser technology

Lark `1.3.1` is the only new dependency. The compiler uses a LALR parser with
the contextual lexer, `propagate_positions=True`, and a typed Transformer that
returns ordered command specifications. The public interface is:

```text
LanguageCompiler.compile(text: str) -> CompilerResult
```

It returns `SUCCESS`, `AMBIGUOUS`, `UNSUPPORTED` or `MALFORMED`; it never
returns an execution mode, risk label, controller command or Lark tree.

## 4. Grammar

Supported skills and expressions:

- `stand`: 站立, 站好, 保持站立, optional explicit 秒/s duration.
- `stop`: 停止, 停下, 立即停止.
- `walk_forward`: 前进, 往前走, 向前走, 向前移动, 往前移动.
- `turn`: 左转, 向左转, 逆时针转, 右转, 向右转, 顺时针转.
- Numbers: Arabic integers/decimals and deterministic Chinese integers 0-9999.
- Units: m/M/米/cm/CM/厘米 for distance; 度/° for angle; 秒/s/S for stand.
- Connectors and punctuation: 然后, 再, 接着, 之后, 最后, 先, comma variants,
  Chinese/ASCII semicolon and period, arrow.

Unsupported by design: navigation, manipulation, grasping, search, perception,
recovery, replanning, LLM input and any skill outside the four frozen
capabilities. The grammar rejects vague quantities and missing parameters
instead of inserting defaults.

## 5. Corpus

The frozen corpus contains **189** samples:

| Source | Samples |
| --- | ---: |
| Generated | 38 |
| Hand-authored | 140 |
| Composition | 11 |

| Category | Samples |
| --- | ---: |
| Atomic valid | 38 |
| Paraphrase | 40 |
| Unit variant | 24 |
| Sequence variant | 18 |
| Composition | 11 |
| Ambiguous | 18 |
| Unsupported | 16 |
| Malformed | 18 |
| Capability unknown | 6 |
| Runtime rejected | 0 |

The generated set is bounded and deterministic with seed `20261006`; the
hand-authored set was not produced by the parser; the composition set combines
known primitives into unseen sequences. The corpus intentionally contains no
HIGH-only frozen mission because Phase 2.0 has no stable HIGH-only example.

## 6. Compiler metrics

| Metric | Result |
| --- | ---: |
| Total samples | 189 |
| Valid sample exact IR match | 1.0 |
| Schema-valid rate | 1.0 |
| Paraphrase consistency | 1.0 |
| Atomic accuracy | 1.0 |
| Composition accuracy | 1.0 |
| Number normalization accuracy | 1.0 |
| Unit normalization accuracy | 1.0 |
| Ambiguity detection recall | 1.0 |
| Ambiguity false-positive rate | 0.0 |
| Unsupported detection recall | 1.0 |
| Malformed rejection rate | 1.0 |
| False rejection rate | 0.0 |
| Hallucinated skill count | 0 |
| Mean compiler latency | 58.1 µs |
| Maximum compiler latency | 480.4 µs |

By source, generated 38/38, hand-authored 140/140 and composition 11/11
matched both the expected status and canonical IR.

## 7. Hard safety results

| Safety invariant | Count |
| --- | ---: |
| `invalid_language_reaching_robot` | 0 |
| `ambiguous_language_reaching_robot` | 0 |
| `unsupported_language_reaching_robot` | 0 |
| `hallucinated_skill_count` | 0 |

Language-invalid inputs never produce a Mission IR and therefore never reach
the runtime. The compiler input bound is 512 normalized characters; the corpus
loader also rejects utterances above 4096 characters.

## 8. Oracle equivalence

The end-to-end set has 11 language missions covering H1, H3/H5-style
composition, left/right turns, Chinese numbers, unit variants, paraphrase and
capability-unknown behavior. The measured results are:

- IR equivalence: **11/11**, exact.
- Runtime equivalence: **11/11**, including grounded execution modes, Task
  Graph order, skill order, mission result and deterministic simulation metrics.
- Representative successful missions: 10/10 compiled and Oracle executions
  succeeded with identical step counts and simulated time.
- Capability-unknown mission: `前进25米` compiled to valid IR, grounded to
  `CAPABILITY_UNKNOWN`, was rejected by Phase 2.0 and executed **0** simulation
  steps.
- No Language entry polluted runtime behavior; compiled and Oracle Mission IR
  used the same frozen Validator, Grounder, Task Graph and Skill Router.

## 9. Capability rejection

`前进25米` is intentionally not a language error:

```text
LanguageCompiler: SUCCESS, WalkForward(25m)
Mission Validator: VALID
Capability Grounder: CAPABILITY_UNKNOWN
Mission Runtime: REJECTED
Robot simulation steps: 0
```

This distinction is also covered by unit tests and by the end-to-end evidence
bundle under `artifacts/controlled_language_001/final/e2e/cl-i-003/`.

## 10. Failure analysis

There were no compiler failures against the frozen expected statuses or
expected Mission IR. Failure taxonomy is therefore represented by the
intentional rejection classes rather than unexpected mismatches:

- ambiguous language: 18 expected, 18 detected;
- missing parameter: included in the ambiguity class and detected as
  `MISSING_PARAMETER`;
- unsupported language capability: 16 expected, 16 detected;
- malformed input: 18 expected, 18 rejected;
- capability-unknown language input: 6 compile-valid samples, with runtime
  rejection verified for the representative end-to-end case.

## 11. Tests

```
361 passed, 0 failed, 8 benign torch.jit.load FutureWarnings
```

The suite covers normalization, Arabic/Chinese numbers, units, synonyms,
connectors, left/right signs, dependency order, canonical IR comparison,
ambiguity, unsupported and malformed input, input bounds, adversarial strings,
determinism, corpus validation and compiler scoring. The final end-to-end
campaign additionally ran the frozen MuJoCo runtime.

## 12. Security

Codex Security `security-diff-scan` was **not available** in this session, so
no official security PASS is claimed. Fallback static review found no
high/medium issue: only `yaml.safe_load` for corpus input, no `eval`/`exec`,
no pickle, no dynamic import, no shell construction, no language text used as a
file path, a 512-character compiler bound, a 4096-character corpus bound, and
the Phase 2.0 path-safe mission-ID check remains in force. The review is
reported as **static review clean**, not as an official scan.

## 13. Negative findings

- Unsupported capability detection uses a finite keyword lexicon. An unseen
  unsupported phrasing that avoids the lexicon fails closed as
  `MALFORMED`/`LANGUAGE_PARSE_ERROR`, not as a friendly
  `UNSUPPORTED_LANGUAGE_CAPABILITY`.
- Chinese number conversion is intentionally capped at 0-9999. Larger,
  dialectal or mixed numeral forms fail closed.
- The generated corpus is bounded by the controlled template space and is not
  a coverage proof for open language.
- No frozen HIGH-only runtime case exists; `runtime_rejected` is intentionally
  empty and the capability-unknown path carries the zero-step rejection test.
- The viewer is not part of the language benchmark and was not rerun for this
  compiler-only report.

## 14. Git

- Branch: `phase2.1/controlled-language`.
- Baseline: `7658b0c` (`phase2.0/mission-runtime`).
- Implementation commits: `ac9ab3b` (Lark/compiler), `55c1b09` (corpus/
  generator), `e483683` (pilot/frozen protocol).
- Final evidence commit: the commit containing this report and
  `execution_equivalence.json`.
- Push is unavailable from this machine because no credentials are configured:
  `git push -u origin phase2.1/controlled-language`.

## 15. Next gate

**Route A — Phase 2.2 LLM Mission Compiler** is the appropriate next gate: the
controlled compiler is deterministic, fail-closed and produces exact Oracle IR
on the frozen corpus, so it can serve as the comparison baseline. Do not start
Phase 2.2 from this report; it requires a separate approved task. **Route B —
Phase 2.1b Grammar Repair** is not indicated by the measured results, although
the lexicon-bounded unsupported path and other-negative findings remain future
coverage work.
