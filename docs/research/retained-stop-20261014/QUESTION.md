# Retained Stop evidence coverage — 2026-10-14

Question: what observed low-speed coverage supports the terminal Stop of the
first language mission, and what remains unobserved for a subsequent task?

Class: Surgical / implementation, descriptive retained-data analysis. This is
neither a new physical experiment nor a new scientific PASS/FAIL or qualification.
Research Ops context: CURRENT, 38 anchors, HEAD/origin/main
`4e2a51bf143cafea5eb90e89a88e1f04c156c9c8`; local main differs (`c2fd276`).
The route flags the new script as unknown; manual scope review confirms stdlib
read-only arithmetic, separate derived output and no shared execution changes.

Decision made before numerical analysis: existing PR #38 already restores the
saved result. Packaging helps access but does not establish a stronger motion
postcondition. Stop and immediate-stop are compiler synonyms, while the retained
StopSkill terminates at the first full sliding-mean threshold crossing. The
mission needs a precise account of what that success can support before adaptive
task chaining. This is a priority inference, not a measured project-wide ranking.

Fixed inputs: run `e709447a946f45e1b91b25942319e178`, request
`5404feae6d3b449ab1e1dfbb53cdd387`, index SHA256
`c3e9a9b9726eaffd14bce07b025ea78c80cbbc5f78ab4811240d282504d99d48`,
C_exec `2faa98481e64b7a0289dff94884a8f7672902177`. Preserve all original bytes.

Bounded work: verify pinned inputs; read exact StopSkill and speed semantics;
recompute the unchanged 1-second / 0.1 m/s first-crossing criterion; report
instantaneous exceedance count, longest consecutive below-threshold sample span,
terminal-window path length and post-success observed coverage. No threshold
search, smoothing sweep, new score, future extrapolation, provider call or render.
Use sample spans (last time minus first time), not an invented continuous-time
guarantee. Stop if integrity or metric correspondence fails.

Evidence needed: reproducible stdlib command, adversarial synthetic tests, an
independent calculation from original bytes, and explicit original-success versus
unobserved-Hold distinction. Stop after these, scoped commit and bounded remote
attempt. New physics, Hold continuation, adaptive dispatch or D011 changes remain
outside this task.
