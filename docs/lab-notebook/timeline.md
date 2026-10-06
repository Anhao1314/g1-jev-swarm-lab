# Research Timeline

Date range covered: **2026-10-06**

This timeline reconstructs the project's progression from a blank repository to a language-grounded Unitree G1 mission runtime.

```mermaid
flowchart LR
    P0["Phase 0<br/>Research charter"] --> P1["Phase 1<br/>Simulation baseline"]
    P1 --> P11["1.1<br/>Competence"]
    P11 --> P12["1.2<br/>Failure boundary"]
    P12 --> P12B["1.2b<br/>Segmentation"]
    P12B --> A["Audit"]
    A --> P13["1.3<br/>Closed-loop"]
    P13 --> P20["2.0<br/>Mission runtime"]
    P20 --> P21["2.1<br/>Controlled language"]
    P21 --> P22["2.2<br/>LLM compiler PARTIAL"]
    P22 --> P22B["2.2b<br/>Compiler hardening"]

    classDef done fill:#dafbe1,stroke:#1a7f37,color:#1f2328;
    classDef audit fill:#fff8c5,stroke:#9a6700,color:#1f2328;
    classDef current fill:#ddf4ff,stroke:#0969da,color:#1f2328;
    class P0,P1,P11,P12,P12B,P13,P20,P21 done;
    class A audit;
    class P22 audit;
    class P22B current;
```

For the compact chart-based view, see the [Visual Research Summary](visual-summary.md).

---

## Phase 0 — Research charter

**Goal:** prevent implementation from outrunning the research question.

The project was framed around a layered embodied architecture:

```text
Mission reasoning
→ decision
→ skill selection
→ embodied control
→ G1
→ evidence
```

The core experimental rule was established early:

> Jev, multi-swarm reasoning, and RL skills must be independently replaceable and independently measurable.

No performance claim was allowed without reproducible evidence.

**Breakthrough:** the project started with falsifiable hypotheses and an evidence contract instead of a demo-first architecture.

---

## Phase 1 — G1 simulation baseline

Local branch: `phase1/g1-simulation-baseline`  
Local HEAD: `217fc71`

**Question:** can a credible Unitree G1 model and official locomotion policy run natively in MuJoCo on the Windows + RTX 5060 Ti machine?

**Difficulty:** a naïve PD-only standing attempt fell after ~1.29 s.

**Reasoning:** do not invent a custom controller merely to force a PASS. Prefer official Unitree assets and preserve provenance.

**Solution:** use Unitree's official MuJoCo assets plus the pretrained `motion.pt` locomotion controller.

**Result:**

- official G1 MuJoCo models loaded natively on Windows;
- 1000-step headless compatibility tests passed;
- Stand / Stop / WalkForward / Turn skill contracts were established;
- Baseline-001 `Stand → Walk 2 m → Stop` passed 5/5 deterministic runs;
- mean 2 m displacement: 2.169 m;
- lateral drift: -0.365 m;
- heading error: -8.41°;
- 21 tests passed.

**Breakthrough:** the project obtained a trustworthy embodied execution baseline rather than a teleported or scripted fake.

---

## Phase 1.1 — Skill competence characterization

Local branch: `phase1.1/skill-characterization`  
Experiment-result commit: `d49961c8607fb1f02ac5a628b12012a5dc383ad4`

**Question:** what can the current G1 skill library actually do, and how does performance degrade?

**Difficulty:** Phase 1's multiple seeds produced byte-identical trajectories, so “5 runs” did not represent 5 independent physical conditions.

**Reasoning:** introduce real seeded perturbations rather than pretending deterministic repetition measures robustness.

**Solution:** characterize nominal behavior and one-factor perturbations across walk distance, turn angle, stand duration, stop velocity, yaw, joint state, friction, and push.

**Result:**

- 237/237 final runs completed successfully under the frozen envelope;
- WalkForward drift increased from -0.159 m at 0.5 m to -0.707 m at 5 m;
- heading error increased from -4.4° to -10.7°;
- Turn stayed accurate: 0.07°–1.24° absolute error;
- Stand posture stayed stable but position drift reached 0.447 m at 20 s;
- Stop required 1.08–1.53 s depending on incoming speed;
- seeded yaw/joint/friction/push produced genuinely distinct trajectories;
- 54 tests passed.

**Unexpected finding:** no tested perturbation actually crossed the failure boundary.

**Breakthrough:** generated the first machine-readable `competence_map.json`.

---

## Phase 1.2 — Failure boundary and risk mapping

Local branch: `phase1.2/failure-boundary`  
Local HEAD: `55b71b565ea3548aae29055e21f2956b9e19a9df`

**Question:** when does a physically stable robot become task-level unreliable?

**Difficulty:** prior experiments were “too safe”; physical stability did not imply mission success.

**Reasoning:** explicitly separate:

```text
physical_success
!=
task_success
```

**Solution:** freeze a warehouse-corridor task envelope and perform one-factor boundary searches.

**Result:**

- 91/91 physical success;
- only 54/91 task success;
- dominant failures were `EXCESSIVE_DRIFT` and `HEADING_ERROR`;
- push task boundary entered transition near 60 N and failure at ≥70 N, while physical fall boundary remained beyond 100 N;
- low-friction task boundary around 0.175/0.15;
- yaw task boundary around 10°–15°;
- joint perturbation boundary was not reached;
- `risk_map.json` and `capability_boundary_map.json` were produced;
- 81 tests passed.

**Breakthrough:** established that a robot can remain physically healthy while failing its task badly.

---

## Phase 1.2b — Distance refinement and segmentation

Local branch: `phase1.2b/distance-segmentation`  
Original local HEAD: `beb95a3`

**Question:** can a long risky walk be made safer by splitting it into short individually low-risk walks?

**Initial result:** segmentation appeared to fail at every tested distance.

**Difficulty:** the result contained an internal contradiction: a 4 m direct run was reported as FAIL despite metrics that appeared within the frozen nominal envelope.

This triggered an integrity audit instead of immediately moving on.

---

## Phase 1.2b Audit — Evaluator input bug

Local branch: `phase1.2b/audit`  
Corrected baseline HEAD: `a519b62`

**Root cause:** segmentation metrics used fields such as `final_lateral_drift_m`, while the shared evaluator expected canonical `lateral_drift_m`. Missing keys silently became `+inf`, causing false `EXCESSIVE_DRIFT` / `HEADING_ERROR` failures.

**Solution:**

- add canonical metric aliases;
- make the comparison builder alias-safe;
- preserve pre-audit raw evidence;
- add regression tests;
- rerun affected mission evaluations.

**Corrected result:**

- 4 m direct: PASS, drift -0.281 m;
- segmented 4 m: all variants FAIL, drift -0.393 to -0.445 m;
- 6 m / 8 m: direct and segmented all FAIL, segmentation consistently worse;
- reliable open-loop distance: 4.53125 m;
- first failure: 4.625 m;
- segmentation remained a negative result after correction;
- 97 tests passed.

**Breakthrough:** the audit improved the experiment system itself. Missing metrics were later forbidden from silently becoming infinity.

---

## Phase 1.3 — Closed-loop locomotion correction

Local branch: `phase1.3/closed-loop-correction`  
Local HEAD: `bea645f13b6af9ee27f902c310148d72fa69a204`

**Question:** is the ~4.6 m open-loop task boundary caused mainly by the absence of an outer path-feedback loop?

**Reasoning:** keep the official Unitree policy unchanged; correct only high-level yaw command using measured heading/lateral error.

Treatments:

1. open-loop;
2. heading-only;
3. heading + lateral.

**Solution:**

- introduce canonical `RunMetrics` validation;
- add an outer-loop path correction interface;
- freeze gains after a small pilot;
- keep `motion.pt`, policy weights, PD gains, action scale, and task envelope unchanged.

**Result:**

- 6/8/10 m open-loop FAIL → corrected PASS;
- drift reduced 87–100%;
- heading error reduced 93–98%;
- zero saturation;
- zero measured oscillation;
- no completion-time regression;
- corrected reliable distance ≥20 m within the frozen budget;
- friction 0.175: open-loop -4.426 m / -71.38° FAIL, heading+lateral -0.009 m / -0.42° PASS;
- 115 tests passed.

**Breakthrough:** a tiny outer-loop correction, not a new RL policy, expanded the validated task envelope from ~4.6 m to at least 20 m.

---

## Phase 2.0 — Oracle structured mission runtime

Local branch: `phase2.0/mission-runtime`  
Local HEAD: `7658b0c`

**Question:** assuming user intent is already perfectly structured, can a deterministic runtime validate, capability-ground, execute, and record multi-step missions?

**Solution:**

- Mission IR 2.0;
- Mission Validator;
- Capability Grounder;
- deterministic Task Graph;
- Mission Executor;
- transition evidence;
- fail-closed negative missions.

**Result:**

- 20/20 valid missions succeeded across H1/H3/H5/H8;
- 15/15 negative missions rejected before any simulation step;
- 85 skill invocations;
- 65 transitions;
- 236,698 simulation steps;
- no observed horizon degradation in the frozen 20-template corpus;
- 185 tests passed.

**Breakthrough:** G1 became a mission runtime rather than a collection of callable skills.

---

## Phase 2.1 — Controlled language compiler

Local branch: `phase2.1/controlled-language`  
Local HEAD: `e825d11b3a1e1c05c36f2e70ac9de79173b6cc6b`

**Question:** can controlled Chinese commands be deterministically compiled into the same Mission IR without allowing ambiguous or unsupported language into the robot layer?

**Solution:** use `lark==1.3.1` as a deterministic grammar parser and preserve the Phase 2.0 runtime unchanged.

**Result:**

- 189/189 frozen samples matched expected compiler status and canonical Mission IR;
- paraphrase consistency 100%;
- ambiguity recall 100%;
- unsupported recall 100%;
- hallucinated skill count 0;
- invalid/ambiguous/unsupported language reaching robot: 0;
- 11/11 Oracle runtime equivalence;
- average compiler latency ~58 µs;
- 361 tests passed.

**Limitations:** controlled grammar is bounded; unsupported detection depends partly on a finite keyword lexicon; open-language coverage is intentionally not claimed.

**Breakthrough:** established a strong, deterministic language baseline against which an LLM compiler can be fairly compared.

---

## Phase 2.2 — LLM Mission Compiler

Local branch: `phase2.2/llm-compiler`  
Local HEAD: `be621e882488e4ef85af23434c7c958f235a7b87`

**Question:** how much open-language coverage does an LLM add over the deterministic grammar baseline, and what does that gain cost?

**Result:** PARTIAL.

- blind valid exact IR: 0.53 → 1.0;
- open-language coverage: 0.5106 → 1.0;
- composition accuracy: 0.25 → 1.0;
- blind unsafe acceptance: 0;
- controlled malformed unsafe acceptance: 2;
- median latency: 91.9 µs → 2.227 s.

**Difficulty:** the LLM interpreted two malformed connector inputs as recoverable intent instead of rejecting malformed language.

**Breakthrough:** generative compilation provided a real coverage gain while preserving capability grounding.

**Failure:** global fail-closed language safety was not met.

**Decision:** do not advance to long-horizon language. Enter Phase 2.2b hardening.

See [Phase 2.2 LLM Mission Compiler](phase2.2-llm-compiler.md).

---

## Current frontier — Phase 2.2b

> Can the LLM compiler retain its open-language coverage gain while restoring `invalid_language_reaching_robot = 0` across both blind and controlled regression sets?
