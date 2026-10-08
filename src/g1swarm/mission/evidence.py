"""Per-mission evidence bundle (Phase 2.0)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..evidence import utc_timestamp


class MissionRecorder:
    """Writes mission_manifest.json / task_graph.json / events.jsonl / summary."""

    def __init__(self, root: str | Path, mission_id: str) -> None:
        self.dir = Path(root) / mission_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.dir / "mission_manifest.json"
        self.task_graph_path = self.dir / "task_graph.json"
        self.events_path = self.dir / "events.jsonl"
        self.summary_path = self.dir / "mission_summary.json"
        # Each mission run owns a fresh event log: re-running a template must
        # not append to (and mix with) the previous run's events.
        self.events_path.write_text("", encoding="utf-8")

    def log_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = {"time": utc_timestamp(), "event": event_type}
        if payload:
            event.update(payload)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def write_manifest(self, payload: dict[str, Any]) -> Path:
        self.manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.manifest_path

    def write_task_graph(self, payload: dict[str, Any]) -> Path:
        self.task_graph_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.task_graph_path

    def write_summary(self, payload: dict[str, Any]) -> Path:
        self.summary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.summary_path
