"""Linux process-group watchdog, also exercised with nonphysical descendants."""
import hashlib, json, os, signal, subprocess, sys, time
from pathlib import Path

def bounded(command, root, limit_s, *, training_marker=None):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    start=time.monotonic(); interrupted=None
    with (root/"worker.stdout.raw").open("xb") as out, (root/"worker.stderr.raw").open("xb") as err:
        proc=subprocess.Popen(command,stdout=out,stderr=err,start_new_session=True)
        while proc.poll() is None:
            expired=time.monotonic()-start>=limit_s
            if training_marker and Path(training_marker).exists():
                marker=json.loads(Path(training_marker).read_text())
                expired |= time.monotonic()-marker["monotonic"] >= 595
            if expired:
                interrupted="wall_clock_watchdog"
                os.killpg(proc.pid,signal.SIGTERM)
                time.sleep(.25)
                try: os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                proc.wait(timeout=2)
                break
            time.sleep(.05)
    result={"pid":proc.pid,"native_exitcode":proc.returncode,"interrupted":interrupted,
            "elapsed_s":time.monotonic()-start,"limit_s":limit_s}
    (root/"process-receipt.json").write_text(json.dumps(result,indent=2))
    return result

if __name__=="__main__":
    root=Path(sys.argv[1]); manifest=Path(sys.argv[2]); expected_sha=sys.argv[3]
    if hashlib.sha256(manifest.read_bytes()).hexdigest()!=expected_sha:
        raise SystemExit("frozen_manifest_sha256_mismatch")
    # Exclusive campaign directory/claim prevents any rerun in this evidence location.
    root.mkdir(exist_ok=False)
    (root/"once.claim").write_text("one authorized campaign; no retry\n")
    result=bounded([sys.executable,str(Path(__file__).with_name("run.py")),str(root),str(manifest),expected_sha],
                   root,1795,training_marker=root/"training-start.json")
    raise SystemExit(0 if result["native_exitcode"]==0 and not result["interrupted"] else 1)
