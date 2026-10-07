"""Read-only localhost transport for verified Research Console artifacts.

This process imports no simulator or training code. Offline acquisition/rendering
is a separate command, and the browser can only consume files in the verified
artifact manifest. Start with ``python console/server.py --port 8765``.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO_ROOT / "experiments/research_console/vertical_slice_001"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IntegrityError(ValueError):
    """An artifact cannot be trusted under its declared manifest."""


def confined_path(root: Path, relative: str) -> Path:
    """Resolve a manifest/static relative path, rejecting symlink escapes too."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise IntegrityError("Expected a nonempty POSIX relative artifact path")
    if Path(relative).is_absolute() or any(p in ("", ".", "..") for p in relative.split("/")):
        raise IntegrityError("Path traversal is not permitted")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise IntegrityError("Artifact escapes its allowed root")
    return target


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def decode_result(path: Path, line: int) -> dict[str, Any]:
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise IntegrityError("Source result locator requires a one-based integer line")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for index, text in enumerate(stream, 1):
            if index == line:
                result = json.loads(text)
                if not isinstance(result, dict):
                    raise IntegrityError("Source result must be an object")
                return result
    raise IntegrityError("Source result locator exceeds its file")


class ConsoleData:
    """Verified, immutable in-memory catalog and evidence access allowlist."""

    def __init__(self, data_root: Path, repo_root: Path = REPO_ROOT):
        self.data_root = data_root.resolve()
        self.repo_root = repo_root.resolve()
        self.web_root = Path(__file__).resolve().parent / "web"
        self.expected: dict[Path, tuple[str, int | None, tuple[int, int]]] = {}
        self.manifest_path = self.data_root / "manifest.json"
        manifest = load_json(self.manifest_path)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
            raise IntegrityError("Console manifest must declare files")
        if not manifest["files"]:
            raise IntegrityError("Empty artifact inventory")
        self._verify_inventory(self.data_root, manifest["files"])
        self._verify_inventory(self.repo_root, manifest.get("sources", {}))
        self.manifest_hash = file_hash(self.manifest_path)
        self.catalog = load_json(self.verified_file(self.data_root, "catalog.json"))
        entries = self.catalog.get("runs", [])
        if not isinstance(entries, list) or not entries:
            raise IntegrityError("Catalog requires at least one run")
        self.runs: dict[str, dict[str, Any]] = {}
        self.raw: dict[str, dict[str, Path]] = {}
        self.evidence: dict[str, dict[str, Any]] = {}
        for entry in entries:
            run_id = entry.get("id") if isinstance(entry, dict) else entry
            if not isinstance(run_id, str) or not IDENTIFIER.fullmatch(run_id):
                raise IntegrityError("Invalid run identifier")
            if run_id in self.runs:
                raise IntegrityError("Duplicate run identifier")
            path = self.verified_file(self.data_root, f"runs/{run_id}/run.json")
            run = load_json(path)
            if run.get("id", run_id) != run_id:
                raise IntegrityError("Catalog/run identifier mismatch")
            self.runs[run_id] = run
            self._bind_evidence(run_id, run, path)
        self.verification = {
            "status": "VERIFIED",
            "manifest_sha256": self.manifest_hash,
            "derived_files": len(manifest["files"]),
            "source_files": len(manifest.get("sources", {})),
            "read_only": True,
            "simulation_imported": False,
        }

    def _verify_inventory(self, root: Path, inventory: dict[str, Any]) -> None:
        if not isinstance(inventory, dict):
            raise IntegrityError("Malformed integrity inventory")
        for relative, record in inventory.items():
            expected = record if isinstance(record, str) else record.get("sha256")
            size = None if isinstance(record, str) else record.get("bytes")
            if not isinstance(expected, str) or not SHA256.fullmatch(expected):
                raise IntegrityError(f"Invalid digest for {relative}")
            path = confined_path(root, relative)
            if not path.is_file() or file_hash(path) != expected:
                raise IntegrityError(f"Artifact hash mismatch: {relative}")
            stat = path.stat()
            if size is not None and stat.st_size != size:
                raise IntegrityError(f"Artifact length mismatch: {relative}")
            self.expected[path] = (expected, size, (stat.st_size, stat.st_mtime_ns))

    def checked(self, path: Path) -> Path:
        """Deny changed files; never silently refresh scientific evidence."""
        path = path.resolve()
        if path not in self.expected or not path.is_file():
            raise IntegrityError("File is not in the verified artifact inventory")
        expected, size, previous = self.expected[path]
        stat = path.stat()
        current = (stat.st_size, stat.st_mtime_ns)
        if current != previous:
            if (size is not None and stat.st_size != size) or file_hash(path) != expected:
                raise IntegrityError("Verified artifact changed after server startup")
            self.expected[path] = (expected, size, current)
        return path

    def verified_file(self, root: Path, relative: str) -> Path:
        return self.checked(confined_path(root, relative))

    @staticmethod
    def _source_path(provenance: dict[str, Any], name: str) -> str | None:
        direct = provenance.get(f"source_{name}_path")
        if direct:
            return direct
        locator = provenance.get(f"source_{name}")
        if isinstance(locator, str):
            return locator
        if isinstance(locator, dict):
            return locator.get("path")
        return None

    def _bind_evidence(self, run_id: str, run: dict[str, Any], run_path: Path) -> None:
        provenance = run.get("provenance", {})
        if not isinstance(provenance, dict):
            raise IntegrityError("Run provenance must be an object")
        raw = {"derived-run": run_path}
        links = [{"label": "Derived synchronized run", "url": f"/raw/{run_id}/derived-run", "locator": "JSON"}]
        source_result = None
        source_manifest = None
        source_paths: dict[str, Path] = {}
        for name, label in (
            ("protocol", "Frozen scientific protocol"),
            ("result", "Original machine result"),
            ("trace", "Original command trace"),
            ("manifest", "Original evidence manifest"),
        ):
            relative = self._source_path(provenance, name)
            if relative is None:
                continue
            path = self.verified_file(self.repo_root, relative)
            source_paths[name] = path
            key = f"source-{name}"
            raw[key] = path
            locator = provenance.get(f"source_{name}_locator", relative)
            if name == "result":
                source_locator = provenance.get("source_result", {})
                line = provenance.get("source_result_line")
                if line is None and isinstance(source_locator, dict):
                    line = source_locator.get("line")
                source_result = decode_result(path, line)
                locator = f"decoded JSONL line {line}"
                for field in ("case_id", "treatment_label"):
                    if field in run and run[field] != source_result.get(field):
                        raise IntegrityError(f"Source result {field} does not match the run")
                acquisition = source_result.get("provenance", {})
                for identity_key, source_key in (("protocol_sha", "protocol_sha256"),
                                                 ("source_commit", "code_commit"),
                                                 ("policy_sha", "base_policy_sha256")):
                    if identity_key in provenance and provenance[identity_key] != acquisition.get(source_key):
                        raise IntegrityError(f"Source result {source_key} does not match the run")
            if name == "manifest":
                original_manifest = load_json(path)
                source_manifest = {
                    "experiment_id": original_manifest.get("experiment_id"),
                    "inventory": {k: v for k, v in original_manifest.get("inventory", {}).items()
                                  if k in [self._source_path(provenance, "result"), self._source_path(provenance, "trace")]},
                    "manifest_sha256": file_hash(path),
                }
            links.append({"label": label, "url": f"/raw/{run_id}/{key}", "locator": locator})
        if source_result is not None and "protocol" in source_paths:
            expected_protocol = source_result.get("provenance", {}).get("protocol_sha256")
            if expected_protocol is not None and file_hash(source_paths["protocol"]) != expected_protocol:
                raise IntegrityError("Frozen protocol does not match source acquisition provenance")
        if "manifest" in source_paths:
            original_manifest = load_json(source_paths["manifest"])
            if "experiment_id" in run and original_manifest.get("experiment_id") != run["experiment_id"]:
                raise IntegrityError("Original experiment identity does not match the run")
            for name in ("result", "trace"):
                if name not in source_paths:
                    continue
                relative = self._source_path(provenance, name)
                original_entry = original_manifest.get("inventory", {}).get(relative, {})
                expected_export = original_entry.get("exported", {}).get("sha256")
                if expected_export is not None and file_hash(source_paths[name]) != expected_export:
                    raise IntegrityError(f"Original evidence manifest does not bind source {name}")
        capture_relative = provenance.get("capture_manifest_path", f"runs/{run_id}/capture_manifest.json")
        capture = confined_path(self.data_root, capture_relative)
        if capture in self.expected:
            raw["capture-manifest"] = self.checked(capture)
            links.append({"label": "Derived capture manifest", "url": f"/raw/{run_id}/capture-manifest", "locator": capture_relative})
        for key, filename, label, detail in (
            ("poses", "poses.npz", "Saved replay poses", "NPZ arrays: time_s / qpos; zero-based frame=N"),
            ("render-manifest", "render_manifest.json", "Derived renderer manifest", "JSON"),
            ("parity", "parity.json", "Capture integrity certificate", "JSON"),
            ("derived-trace", "derived_trace.jsonl.gz", "Derived replay command trace", "decoded JSONL lines 1-end"),
            ("derived-result", "derived_result.json", "Derived replay result", "JSON"),
        ):
            relative = f"runs/{run_id}/{filename}"
            path = confined_path(self.data_root, relative)
            if path not in self.expected:
                continue
            raw[key] = self.checked(path)
            links.append({"label": label, "url": f"/raw/{run_id}/{key}", "locator": f"{relative} · {detail}"})
        self.raw[run_id] = raw
        self.evidence[run_id] = {
            "run_id": run_id,
            "provenance": provenance,
            "source_result": source_result,
            "source_manifest": source_manifest,
            "raw_links": links,
        }


class ConsoleHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address: tuple[str, int], data: ConsoleData):
        self.data = data
        super().__init__(address, ConsoleHandler)


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Paths are allowlisted IDs, and query strings are never logged.
        print(f"console {self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}")

    def _headers(self, status: int, content_type: str, length: int, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()

    def _json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_POST(self) -> None:
        self.close_connection = True
        self._json({"error": "Research Console is read-only"}, 405)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        try:
            # Reject unexpected web Origins/Hosts; this service is localhost-only.
            host = self.headers.get("Host", "")
            if host and not re.fullmatch(r"(?:127\.0\.0\.1|localhost)(?::\d+)?", host, re.I):
                self._json({"error": "Localhost access required"}, 403)
                return
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc.lower() != host.lower():
                self._json({"error": "Cross-origin access is disabled"}, 403)
                return
            path = unquote(urlsplit(self.path).path)
            parts = path.strip("/").split("/")
            data = self.server.data
            if path == "/api/catalog":
                self._json({**data.catalog, "integrity": data.verification})
            elif path == "/api/health":
                self._json({"status": "ok", "integrity": data.verification})
            elif len(parts) == 3 and parts[:2] in (["api", "runs"], ["api", "evidence"]):
                run_id = parts[2]
                if run_id not in data.runs:
                    self._json({"error": "Unknown run"}, 404)
                    return
                self._json(data.runs[run_id] if parts[1] == "runs" else data.evidence[run_id])
            elif len(parts) == 3 and parts[0] == "media":
                run_id, filename = parts[1:]
                if run_id not in data.runs or filename != "rollout.mp4":
                    self._json({"error": "Unknown media"}, 404)
                    return
                self._file(data.verified_file(data.data_root, f"runs/{run_id}/{filename}"), range_supported=True)
            elif len(parts) == 3 and parts[0] == "raw":
                run_id, key = parts[1:]
                target = data.raw.get(run_id, {}).get(key)
                if target is None:
                    self._json({"error": "Unknown evidence locator"}, 404)
                    return
                self._file(data.checked(target), download=target.name)
            elif path == "/" or path.startswith("/static/"):
                relative = "index.html" if path == "/" else path.removeprefix("/static/")
                target = confined_path(data.web_root, relative)
                if not target.is_file():
                    self._json({"error": "Static file not found"}, 404)
                    return
                self._file(target)
            else:
                self._json({"error": "Not found"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except IntegrityError as error:
            self._json({"error": str(error)}, 409)
        except (FileNotFoundError, OSError, ValueError):
            self._json({"error": "Artifact unavailable"}, 404)

    def _file(self, path: Path, range_supported: bool = False, download: str | None = None) -> None:
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        headers = {"Accept_Ranges": "bytes"} if range_supported else {}
        byte_range = self.headers.get("Range") if range_supported else None
        if byte_range:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range.strip())
            if match is None or not any(match.groups()):
                self._headers(416, "application/octet-stream", 0, Content_Range=f"bytes */{size}")
                return
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            else:
                start = max(0, size - int(last))
            if start > end or start >= size or (not first and int(last) == 0):
                self._headers(416, "application/octet-stream", 0, Content_Range=f"bytes */{size}")
                return
            status = 206
            headers["Content_Range"] = f"bytes {start}-{end}/{size}"
        if download:
            headers["Content_Disposition"] = f'attachment; filename="{download}"'
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".gz":
            content_type = "application/gzip"  # Keep original evidence bytes intact.
        length = max(0, end - start + 1)
        self._headers(status, content_type, length, **headers)
        if self.command == "HEAD":
            return
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = length
                while remaining:
                    chunk = stream.read(min(remaining, 128 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Seeking/closing a browser cannot affect any research execution.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    data = ConsoleData(args.data)
    server = ConsoleHTTPServer(("127.0.0.1", args.port), data)
    print(f"Research Console: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Verified {data.verification['derived_files']} derived files and {data.verification['source_files']} source files; read-only", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
