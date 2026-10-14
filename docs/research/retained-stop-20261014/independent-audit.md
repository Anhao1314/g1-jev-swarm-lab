# Independent retained-data audit

Verdict: the arithmetic and scope of `scripts/analyze_retained_stop.py` agree
with an independently implemented calculation from the original native post-state
records. This is not a new physical qualification or a changed historical verdict.

Auditor: separate agent `independent_stop_audit`, 2026-10-14. Main analyzer reviewed
at final SHA256 `43872f4fe4555b3467184378b0eb9879f98aa564c989b7e8292f529dcc1b4ada`.
The independent script was written and first executed before reading or running
the main analyzer; it imports only Python stdlib and reads no main-analyzer output.

Reproduction from the repository root:

```powershell
.venv/Scripts/python.exe docs/research/retained-stop-20261014/independent_audit.py
```

The fixed evidence index hash, original native/event/source bytes, source-file
hashes and C_exec Git content were checked. One initial audit assertion failed:
`robot_state.py` is archived with CRLF while its Git blob uses LF. The archive
file matches its frozen hash exactly; normalizing CRLF gives identical Git
content. Both hashes are retained in `independent-audit.json`; no source or
archive was edited. A first source lookup used the wrong archive directory and
failed; the evidence index supplied the correct `language-first-action-20261014`
locator. Neither lookup failure is a physical outcome.

Exact source interpretation at `2faa98481e64b7a0289dff94884a8f7672902177`:
`skills/basic.py` StopSkill uses the mean of the last 500 post-step speeds at
0.002 s per step, stops on its first <= 0.1 m/s mean, and checks fallen state.
`state/robot_state.py` defines speed as horizontal `hypot(vx, vy)`;
`simulation/g1_simulation.py` binds velocity to `qvel[:3]`.

| Independent observation | Result |
| --- | --- |
| Stop samples | Native steps 5346–6030; 685 samples |
| First passing mean | Stop step 685, native 6030, simulation time 12.06 s |
| First passing / previous mean | 0.09991565538953033 / 0.10003703586394586 m/s |
| Final window samples above 0.1 m/s | 249 / 500 = 49.8% |
| Final instantaneous speed | 0.10087112741017572 m/s |
| Longest <= 0.1 m/s consecutive samples across Stop | 128; native 5820–5947 |
| Span between those sample timestamps | 0.2540000000000848 s |
| Final window path between post samples | 0.09959374769968667 m |
| Observations after first passing window | 0 samples / 0 s |

All requested numerical fields agree with the main analyzer. The main analyzer's
longest-run field explicitly covers the final window; the independent search
covers all Stop samples and finds the same run. The 500-sample contract window
has 0.998 s between its first and last post timestamps. Neither that distinction
nor the 0.254 s sample span supplies a continuous-time guarantee. The path covers
499 intervals between post samples, as the main field name states.

No material defect found in the reviewed main analyzer for this pinned archive.
It preserves historical SUCCESS, makes no new Hold or generalized safety claim,
and validates the raw state against the state returned to the skill. Its strict
fixed-index profile intentionally is not a general-purpose input format.

Final read-only review included `tests/test_retained_stop_analysis.py` (12 tests).
The tests exercise mixed fast/slow mean success, later coverage, no crossing,
original summation order, gaps, nonfinite values, planar speed, duplicate/missing
records, raw/returned-state disagreement, policy/time gaps, index rejection and
forbidden imports. The duplicate `native_observation` rows are deliberately not
counted as new samples. CLI index verification precedes archive path reads;
changed bytes cannot produce `VERIFIED_RETAINED_DIAGNOSTICS`. A changed source
contract also rejects against the frozen source manifest. The independently
executed main CLI returned exit 0 and 49 verified indexed files. I reviewed the
test code rather than rerunning the primary agent's already passing test suite.

Final incremental review: the analyzer now requires every node count to be a
positive integer bounded by the remaining sample slice, avoiding Python's silent
slice truncation. Added analyzer/preparation/mission/protocol/policy SHA fields
report the local analyzer and identities from the already hash-verified retained
inputs. These changes do not alter metric calculations or historical status.
They were reviewed read-only after the earlier CLI run (earlier analyzer SHA256
`b7fec2fa95b02518f16ed76805b24594089d4d215bbf73229481d7eea5467d49`);
the primary agent reran the 12 tests and regenerated the final analysis. No
additional full-suite rerun was required for this incremental independent review.

Remaining blocker: behavior after success has no retained observations. A future
Hold continuation, chaining trial or new physical acquisition requires separate
authorization. The absence of samples establishes lack of evidence, not that
future Hold would fail. Stop here: independent arithmetic, source correspondence
and scope checks are complete; zero new native steps/policy calls/training.
