# PR #10 offline reproduction

Use a clean checkout of the PR HEAD, the pinned Python environment (including NumPy), and a separate empty restoration directory. No policy, simulator or provider is executed. Run from the checkout root:

```powershell
& $Python experiments/m2/cross_state_reliability_analysis_001/archive_evidence.py --restore-to $RestoreRoot
& $Python experiments/m2/cross_state_reliability_analysis_001/audit.py --verify --raw-root $RestoreRoot
```

`$RestoreRoot` contains restored `experiments/...` paths, not the `artifacts` directory itself. The auditor resolves acquisition files and sealed raw inventory there; frozen protocol, readiness manifest, historical M2.3b comparators and original audit.json remain in the clean checkout. The separate root is accepted only in read-only verification mode. Restoration refuses existing targets.

Expected: 178 member hashes and lengths and eight archive hashes match; audit reports 94 checks, integrity PASS, INCONCLUSIVE and 64,787 native steps. Verification compares the original audit result, preserves its source identity and does not overwrite audit.json/md. Original raw data, archives, audit results and historical evidence remain unchanged.

The original report's outside-repo restore procedure requires the explicit `--raw-root` argument above. Research Ops retains its reviewed M2.3b selection; CURRENT 38/38 anchors is not automatic acceptance of M2.4. Reproduction authorizes no acquisition or result promotion.
