# Research Console v0.1

## M2.2 adaptive mission lifecycle — development slice

```powershell
python console/server.py --data experiments/research_console/m2_adaptive_lifecycle_001 --port 8773
```

The three source-bound replays show the same failed task and physical halt,
followed by a task-scoped state assessment: matching TEST_ONLY configuration
authorization permits a separate new Oracle mission, missing authorization
refuses it with zero new dispatch, and the original normal control continues
unchanged. The original failed graph is never revived. Inspect the original
and new outcomes separately, along with assessment, request, and continuity
receipts. `ESCALATE` records dispatch refusal; it is not an ongoing physical
safety controller. See the [M2.2 report](../experiments/m2/adaptive_mission_lifecycle_001/report.md).

The one-use TEST_ONLY grant behavior is verified only through the trusted,
serialized experiment entry. Its mutable in-process registry and dispatch
flag have no validated concurrent atomicity contract. The lower-level
`MissionExecutor.run(existing_session=...)` remains independently callable;
this is not universal enforcement or a production permission guarantee.
See the [release scope clarification](../docs/m22-release-review.md).

## M2 mission feedback and post-failure halt

The current single-agent slice replays the retained M2.0 feedback comparison
and M2.1 opt-in post-failure StopSkill. It displays the actual G1 state,
trajectory, strict decision, Task Graph block, separate physical-halt request,
deceleration and final halt result. This is a read-only replay of frozen MuJoCo
evidence; the browser cannot dispatch a mission or stop a robot.

```powershell
py -3.11 console/server.py --data experiments/research_console/m2_post_failure_halt_001 --port 8765
```

Open `http://127.0.0.1:8765/`. The failed Walk uses a HIGH-risk experimental
override. The M2.1 [report](../experiments/m2/post_failure_halt_integration_001/report.md)
and [source-bound manifest](../experiments/research_console/m2_post_failure_halt_001/manifest.json)
define what the replay supports. The stop result is bounded to one tested
simulator state; it is not a hardware emergency-stop certificate.

## Residual authority mechanism replay

An earlier mechanism observer view at **http://127.0.0.1:8766/** shows residual-off, combined inward,
and forward/inward corner from the same retained 16m case. The Walk-relative
phase strip, native acquisition-state replay, world routes, reference line and
source-bound metrics show the early authority effect and its subsequent decay.
The original two-arm slice remains selectable. See the
[mechanism replay report](../experiments/research_console/residual_authority_replay_001/REPORT.md).

```powershell
.venv\Scripts\python.exe console/server.py --data experiments/research_console/residual_authority_replay_001 --port 8766
```

These three new videos are original acquisition **state playback**, with zero
physics steps. The older slice described below retains its distinct derived
visualization replay provenance. Scientific strict FAIL outcomes are unchanged.

## Original reference slice

One read-only workstation: native MuJoCo G1 replay → synchronized route and
diagnostics → the original machine evidence. The retained slice is the same
`sequence-mixed-16m` under α=0 and α=0.5, both residual off.

Open **http://127.0.0.1:8765**. If the local server is stopped, from the repository:

```powershell
.venv\Scripts\python.exe console/server.py --port 8765
```

The server itself uses only Python's standard library. It imports no simulator,
controller, evaluator or training module. It checks the published artifact and
source inventory before opening its socket. Scientific assets must be present
and match the inventory. It binds only localhost and accepts GET/HEAD.

Choose **Compare**, seek to **20s**, and inspect both headings and lateral errors.
Click the **α=0.5 / Walk 8m / local corridor** marker to see frozen nominal PASS,
strict FAIL, the original 0.372292m drift and the 0.56m / 0.28m limits. The
Inspector links directly to the original gzip result (decoded line 52), original
trace, frozen protocol and evidence manifest, plus derived poses and rendering
receipts. Play/Pause, seek, treatment selection and playback speed affect media
only. Both arms share requested simulation time, not percentage completion.

## Scientific meaning

**Every video is `derived_visualization_replay`.** The original acquisition did
not record full joint poses or video. A separately authorized offline historical
replay supplies qpos/qvel/ctrl states at 20Hz and its exact final state. All
scientific result fields and all original command trace rows were checked for
exact equality. This supports behavior matching, not a claim that unavailable
original joint states were compared. The capture-off/on paired audit additionally
checks every physics state, command, torque, actual policy observation/action,
residual observation, RNG state and recurrent tensor state. No learned actor,
reward call, optimizer update or new checkpoint is involved in this slice.

The local corridor always uses **actual node-start heading and origin**. The
correction heading is a different signal. Global diagnostics retain the original
planned heading/origin conventions, including Turn target heading. Non-Walk
correction heading is unavailable. Frozen outcomes shown at the playhead are
**completed node results**, not live threshold decisions. The UI never rescores.

Media frames use an explicit simulation-time map. The appended final exact state
does not coincide with the next uniform media timestamp; seeking and metrics
respect the map. Browser presented-frame callbacks synchronize diagnostics when
supported. Frozen event time and the nearest visual frame time remain distinct.
20Hz visual frames explain results; they are not a contact-force measurement.

## Rendering and provenance

Physics finishes before the render process is launched. The renderer loads its
own model/data and OpenGL context, restores copied states, calls `mj_forward`
and renders the actual official G1 meshes. It never calls `mj_step`. The browser
cannot request a replay, simulator step or policy execution. A slow or crashed
renderer/server/browser therefore has no execution path back into acquisition.
No future live training observer has been added or certified.

MuJoCo exposes mutable buffers; state copies and independent renderer ownership
follow its [official Python documentation](https://mujoco.readthedocs.io/en/stable/python.html).
The render-only clone changes framebuffer dimensions and camera parameters.
Physics timestep, PD, policy, gains, skill semantics and historical gates remain
unchanged. Cross-context RGB equality is not required: the offscreen gate
records it honestly, while pose/state identity is independently checked.

All visuals, state arrays, frame-time maps and source records are bound by SHA-256
in `experiments/research_console/vertical_slice_001/manifest.json`. Inspector
distinguishes original acquisition commit, evidence publication commit, actual
producer execution base commit, reproducible producer source commit and exact
producer bytes. Capture code and validation code identities remain separate for
the retained initial certificate correction. The initial false certificate is
retained: it compared wall-clock timing and a publication arm label, despite
already identical physics and commands. The comparison was corrected from saved
records without another replay.

## Offline artifact production

This is an explicit CLI workflow, not a Web feature. It writes only a new output
directory, refuses to overwrite captured runs or existing media, verifies the
historical freeze before replay, and retains a negative certificate on mismatch.
The index is a rebuildable display cache; freeze its inventory before serving.
For a new visual artifact directory (do not overwrite the published one):

```powershell
.venv\Scripts\python.exe console/prepare_encoder.py
.venv\Scripts\python.exe console/capture.py --alpha 0 --output NEW/runs/alpha0-off
.venv\Scripts\python.exe console/capture.py --alpha 0.5 --output NEW/runs/alpha05-off
.venv\Scripts\python.exe console/render.py --run NEW/runs/alpha0-off
.venv\Scripts\python.exe console/render.py --run NEW/runs/alpha05-off
.venv\Scripts\python.exe console/build_index.py --data NEW
```

The pinned encoder is downloaded to ignored `console/.tools`, never installed
into the scientific environment. G1 source assets are those already pinned by
the project. Videos and retained state arrays are committed in the new Console
experiment namespace; historical Phase3A directories are untouched.

## Validation and scope

```powershell
.venv\Scripts\python.exe -m pytest console/tests -q
node --test console/web/data.test.js
```

The independent integrity audit checks source export/raw identities, every
derived frame's arithmetic, original formal outcomes, precise event locators,
paired replay certificates, asset hashes and unchanged historical files.
Backend tests cover read-only APIs, byte-range seeking, changed-file refusal
and confined evidence access. Browser QA exercises the full robot-to-raw chain.

This version includes two deterministic arms and one fixed seen regression case.
It has no live stream, training control, learned checkpoint browser, full
dashboard, Language Safety, Jev or Multi-Swarm surface. It does not change any
research gate or start another training experiment.
