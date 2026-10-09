# Independent M2.5A read-only scientific audit

Candidate conclusion: `PASS_BOUNDED_POST_HALT_HOLD_IN_TWO_SEEN_SEED0_STATES_WITH_NORMAL_STOP_CONTROL`.

This independent reviewer made zero physics, policy or provider calls and did not import the acquisition runtime. `independent_recompute.py` reads the 43 original saved files without modifying them, independently derives speed from native qvel, path from native qpos, posture from quaternion, the first Stop crossing from saved speed history, and compares all parent native states against sealed M2.4 archives. `independent_audit.json` binds every raw file SHA-256 plus frozen readiness/protocol hashes. All 254 frozen source files match.

| Frozen cell | Parent / Hold native steps | Max 1s rolling speed m/s | Final speed m/s | Hold XY path m | Max instantaneous speed m/s | Result |
|---|---:|---:|---:|---:|---:|---|
| Seen failure/Halt | 7139 / 1000 | 0.099604884 | 0.086390810 | 0.135574498 | 0.144113471 | Bounded PASS |
| Turn45 failure/Halt | 8266 / 1000 | 0.099437391 | 0.090219608 | 0.136287493 | 0.145732049 | Bounded PASS |
| Normal Stop control | 5991 / 1000 | 0.078349090 | 0.077928123 | 0.141010946 | 0.142377582 | Bounded PASS |

All three cells have exactly 1000 uninterrupted Hold steps (2 simulated seconds), zero commands, preserved terminal/pre-Hold snapshots, identity/counter continuity and no extra reset or dispatch. All finite/standing/no-fall checks pass. Total is 24,396 native steps, below 30,000, and each cell is within its own step cap. All 1000 rolling means, final speed and path satisfy the frozen contract. Source parent traces match historical native prefixes exactly; original strict failures remain failures. The original Stop first-crossing steps are 671 (Seen), 658 (Turn45), and 500 (normal control). Seen and Turn45 first-crossing margins are only 0.000030418 and 0.000183943 m/s. Nonetheless the following fixed 2s meets the complete frozen hold criteria.

The instantaneous speed peaks exceed 0.1 m/s in all three cells. This is retained descriptive evidence and does not invalidate the frozen rolling-mean plus terminal-speed contract; it forbids any claim that speed stayed below 0.1 m/s at every native step. Likewise XY path is 136–141mm although net displacement is only 30–67mm: bounded hold is not immobility.

Limitations: two seen seed-0 failure states only; normal Stop is not a matched failure-state control. No independent seeds, hardware safety, production safety or longer-duration stability are established. Hidden recurrent-state bytes are unavailable; same object/no-reset witnesses do not prove hidden byte identity. Exact per-cell wall elapsed is not persisted by the frozen adapter; per-cell guards/external watchdog and complete acquisition command elapsed (root retained receipt: 32.5378347s) support compliance with 120/360s caps, not per-cell latency characterization. The frozen `audit.py` additionally audits saved physical flags, raw finite/controller values, graph/result/prefix closure and terminal witnesses; its full PASS is separate from this simpler second implementation. Both read-only paths support the bounded candidate result. No scientific promotion or merge is authorized by this audit.

Stopping reason: the one authorized fixed campaign and all three cells have complete saved evidence and the bounded question is answerable; no retry, new state or threshold change is justified.
