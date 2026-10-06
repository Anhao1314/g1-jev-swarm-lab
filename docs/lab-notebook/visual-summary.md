# Visual Research Summary

This page is the visual entry point for the experiment record. Every chart below is reconstructed from the frozen experiment reports already recorded in this notebook. It does not replace the underlying evidence.

## Research progression

```mermaid
flowchart LR
    P0["Phase 0<br/>Research charter"] --> P1["Phase 1<br/>G1 simulation"]
    P1 --> P11["Phase 1.1<br/>Competence map"]
    P11 --> P12["Phase 1.2<br/>Failure boundary"]
    P12 --> P12B["Phase 1.2b<br/>Segmentation"]
    P12B --> AUDIT["Integrity audit<br/>Evaluator bug"]
    AUDIT --> P13["Phase 1.3<br/>Closed-loop correction"]
    P13 --> P20["Phase 2.0<br/>Mission runtime"]
    P20 --> P21["Phase 2.1<br/>Controlled language"]
    P21 --> P22["Phase 2.2<br/>LLM compiler"]

    classDef done fill:#dafbe1,stroke:#1a7f37,color:#1f2328;
    classDef audit fill:#fff8c5,stroke:#9a6700,color:#1f2328;
    classDef current fill:#ddf4ff,stroke:#0969da,color:#1f2328;

    class P0,P1,P11,P12,P12B,P13,P20,P21 done;
    class AUDIT audit;
    class P22 current;
```

The key methodological transition was:

```mermaid
flowchart TD
    A["Can the robot move?"] --> B["What can each skill do?"]
    B --> C["Where does task reliability fail?"]
    C --> D["Can composition fix it?"]
    D -->|No| E["Can feedback fix it?"]
    E -->|Yes| F["Can structured missions execute reliably?"]
    F --> G["Can bounded language compile to the same mission?"]
    G --> H["Can an LLM expand language coverage without breaking safety?"]
```

## Physical stability was not task success

![Phase 1.2 physical vs task success](visuals/phase1-physical-vs-task.svg)

**Takeaway:** Phase 1.2 produced 91/91 physically stable runs but only 54/91 task successes. This forced the project to separate robot health from task correctness.

## Segmentation was a negative result

![Phase 1.2b segmentation comparison](visuals/phase1-segmentation.svg)

**Takeaway:** splitting long walks into short ones did not reduce drift. At 4 m, direct execution passed while every segmented treatment failed after the audit correction.

## Closed-loop feedback changed the capability envelope

![Phase 1.3 closed-loop comparison](visuals/phase1-closed-loop.svg)

**Takeaway:** with the Unitree policy weights unchanged, heading or heading+lateral feedback converted 6/8/10 m failures into passes and pushed the validated reliable distance to at least 20 m within the frozen budget.

## Controlled-language benchmark coverage

![Phase 2.1 language corpus](visuals/phase2-language-corpus.svg)

**Takeaway:** Phase 2.1 tested 189 frozen samples across valid, compositional, ambiguous, unsupported, malformed and capability-unknown language. Every expected compiler result and canonical Mission IR matched.

## Integrity correction chain

```mermaid
flowchart LR
    A["Segmentation run emits<br/>final_lateral_drift_m"] --> B["Shared evaluator expects<br/>lateral_drift_m"]
    B --> C["Missing key became +∞"]
    C --> D["False EXCESSIVE_DRIFT"]
    D --> E["4 m direct incorrectly marked FAIL"]
    E --> F["Manual inconsistency check"]
    F --> G["Raw evidence recomputed"]
    G --> H["Canonical metric aliases + regression tests"]
    H --> I["Affected runs re-evaluated"]
    I --> J["Corrected conclusion:<br/>4 m direct PASS;<br/>segmentation still worse"]

    classDef bad fill:#ffebe9,stroke:#cf222e,color:#1f2328;
    classDef fix fill:#dafbe1,stroke:#1a7f37,color:#1f2328;
    class A,B,C,D,E bad;
    class F,G,H,I,J fix;
```

## Current architecture boundary

```mermaid
flowchart TD
    U["User language"] --> C["Compiler"]
    C --> IR["Mission IR 2.0"]
    IR --> V["Validator"]
    V --> G["Capability / risk grounding"]
    G --> TG["Task Graph"]
    TG --> EX["Deterministic Runtime"]
    EX --> SR["Skill Router"]
    SR --> SK["Validated G1 skills"]
    SK --> G1["Unitree G1 / MuJoCo"]
    G1 --> EV["RobotState + SkillResult + Evidence"]
    EV --> EX

    J["Future: Jev"] -. decision layer .-> G
    S["Future: Multi-Swarm"] -. reasoning layer .-> TG
```

The future Jev and multi-swarm layers are intentionally shown as dotted, because their value has not yet been experimentally established.
