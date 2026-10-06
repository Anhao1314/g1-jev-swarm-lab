"""Per-run evidence bundle writer.

Layout (all under ``artifacts/``, which is excluded from git)::

    artifacts/<experiment_id>/<run_id>/
        manifest.json
        metrics.json
        events.jsonl
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..paths import artifacts_dir
from .manifest import RunManifest, utc_timestamp


class RunRecorder:
    def __init__(
        self,
        experiment_id: str,
        run_id: str,
        *,
        root: str | Path | None = None,
        manifest: RunManifest | dict[str, Any] | None = None,
    ) -> None:
        base = Path(root) if root is not None else artifacts_dir()
        self.run_dir = base / experiment_id / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.run_dir / "manifest.json"
        self.metrics_path = self.run_dir / "metrics.json"
        self.events_path = self.run_dir / "events.jsonl"
        if manifest is not None:
            self.write_manifest(manifest)

    def write_manifest(self, manifest: RunManifest | dict[str, Any]) -> Path:
        payload = manifest.to_dict() if isinstance(manifest, RunManifest) else dict(manifest)
        self.manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self.manifest_path

    def log_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = {"time": utc_timestamp(), "event": event_type}
        if payload:
            event.update(payload)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def finish(self, result: dict[str, Any], metrics: dict[str, Any]) -> None:
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        payload["result"] = result
        payload["finished_at"] = utc_timestamp()
        self.manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.log_event("run_finished", {"result": result})
