"""Offline paired mechanism diagnostics; original scores are never rewritten."""
import gzip
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "experiments/phase3a/residual_authority_feasibility_001/evidence/runs"

def read(path):
    return json.loads(path.read_text())

def rows(path):
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return [json.loads(line) for line in raw.splitlines()]

def projection(state, origin, heading):
    dx, dy = [state["base_position"][i]-origin[i] for i in (0, 1)]
    return math.cos(heading)*dx+math.sin(heading)*dy, -math.sin(heading)*dx+math.cos(heading)*dy

def sample(row):
    ref = row["walking_reference"]
    state = row["state_before_command"]
    local = projection(state, ref["measurement_origin"], ref["measurement_heading_rad"])
    selected = projection(state, ref["control_origin"], ref["control_heading_rad"])
    return {"elapsed_s":row["elapsed_s"], "simulation_time_s":row["time_s"],
            "local_forward_m":local[0], "local_lateral_m":local[1],
            "reference_lateral_m":selected[1], "action":row["action"],
            "correction_yaw_radps":row["deterministic_command"][2],
            "applied_yaw_radps":row["applied_command"][2],
            "authority_active":row["active"],
            "observation_active":row.get("observation_active", row["active"]),
            "height_m":row["height_m"], "tilt_deg":row["tilt_deg"]}

def load_arm(directory, label):
    trace = directory / "trace.jsonl.gz"
    if not trace.exists(): trace=directory/"trace.jsonl"
    selected = [(i+1, r) for i,r in enumerate(rows(trace)) if r["node_index"] == 1]
    return {"label":label, "record":read(directory/"result.json"),
            "samples":[dict(sample(r),source_line=i) for i,r in selected],
            "source_trace":trace.relative_to(ROOT).as_posix(),
            "source_trace_sha256":hashlib.sha256(trace.read_bytes()).hexdigest()}

def compare(arm, baseline):
    paired=[]
    for point in arm["samples"]:
        other=min(baseline["samples"],key=lambda q:abs(q["elapsed_s"]-point["elapsed_s"]))
        if abs(other["elapsed_s"]-point["elapsed_s"]) > .001: continue
        paired.append(dict(point, delta_local_vs_off_m=point["local_lateral_m"]-other["local_lateral_m"],
                           baseline_source_line=other["source_line"]))
    end=arm["record"]["nodes"][1]; base_end=baseline["record"]["nodes"][1]
    duration=end["end_state"]["simulation_time"]-end["start_state"]["simulation_time"]
    window=arm["record"].get("authority_window_s",2.0)
    at_cutoff=min(paired,key=lambda q:abs(q["elapsed_s"]-window))
    end_delta=end["lateral_drift_m"]-base_end["lateral_drift_m"]
    after=[p for p in paired if p["elapsed_s"]>=window-1e-8]
    saturation=sum(abs(p["applied_yaw_radps"])>=.6-1e-10 for p in paired)
    return {"label":arm["label"],"window_s":window,"walk_duration_s":duration,
            "post_authority_duration_s":max(0,duration-window),
            "formal_local_endpoint_m":end["lateral_drift_m"],
            "formal_endpoint_delta_vs_off_m":end_delta,
            "strict_limit_m":end["envelope"]["strict_envelope"]["limits"]["lateral_drift_max_m"],
            "strict_gap_m":abs(end["lateral_drift_m"])-end["envelope"]["strict_envelope"]["limits"]["lateral_drift_max_m"],
            "first_walk_strict":end["strict_success"],
            "cutoff_sample":at_cutoff,
            "endpoint_to_cutoff_effect_ratio":end_delta/at_cutoff["delta_local_vs_off_m"] if at_cutoff["delta_local_vs_off_m"] else None,
            "post_cutoff_peak_abs_effect_m":max(abs(p["delta_local_vs_off_m"]) for p in after) if after else None,
            "yaw_clip_10hz_samples":saturation,"compared_10hz_samples":len(paired),
            "checkpoints":[min(paired,key=lambda p:abs(p["elapsed_s"]-t)) for t in [2,4,6,8,10,12,14,15,16]],
            "time_series":paired,"source_trace":arm["source_trace"],"source_trace_sha256":arm["source_trace_sha256"],
            "endpoint_comparison":"Each arm original formal endpoint; time series compares equal elapsed times only;20/10Hz samples do not certify continuous safety."}

def main():
    baseline=load_arm(OLD/"01--off--primary","off")
    historical=load_arm(OLD/"05--combined_inward--primary","combined2 historical")
    output=ROOT/"artifacts/residual_authority_window_001"
    dirs=[p.parent for p in (output/"runs").glob("*/result.json")]
    arms=[load_arm(p,p.name) for p in sorted(dirs)]
    result={"baseline_run_id":baseline["record"]["run_id"],
            "historical":compare(historical,baseline),"new":[compare(a,baseline) for a in arms],
            "interpretation_limit":"Single seen case and fixed saturated profile. Duration increases exposure and reduces washout; no independent identification of those components, no generalization or impossibility proof."}
    destination=HERE/"mechanism_analysis.json"
    with destination.open("x",encoding="utf-8",newline="\n") as f: json.dump(result,f,indent=2,allow_nan=False);f.write("\n")
    print(json.dumps({"historical":{k:v for k,v in result["historical"].items() if k not in ("time_series","checkpoints")},"new":[{k:v for k,v in a.items() if k not in ("time_series","checkpoints")} for a in result["new"]},indent=2))

if __name__ == "__main__":main()
