"""HTTP and provenance checks for the read-only console, without MuJoCo."""
from __future__ import annotations

import gzip
import importlib.util
import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


SPEC = importlib.util.spec_from_file_location("research_console_server", Path(__file__).parents[1] / "server.py")
assert SPEC is not None and SPEC.loader is not None
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def inventory(root: Path) -> dict[str, dict[str, object]]:
    return {p.relative_to(root).as_posix(): {"sha256": SERVER.file_hash(p), "bytes": p.stat().st_size}
            for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"}


@pytest.fixture
def artifact(tmp_path: Path):
    repo = tmp_path / "repo"
    data = repo / "derived"
    result_path = repo / "source/results.jsonl.gz"
    result_path.parent.mkdir(parents=True)
    write_json(repo / "source/protocol.json", {"threshold": 0.28})
    protocol_sha = SERVER.file_hash(repo / "source/protocol.json")
    original = {"case_id": "fixed-case", "treatment_label": "off", "status": "SUCCESS", "nodes": [{"strict_pass": False}],
                "provenance": {"protocol_sha256": protocol_sha, "code_commit": "original-commit", "base_policy_sha256": "a" * 64}}
    with gzip.open(result_path, "wt", encoding="utf-8") as stream:
        stream.write(json.dumps({"case_id": "other"}) + "\n")
        stream.write(json.dumps(original) + "\n")
    write_json(repo / "source/evidence_manifest.json", {"experiment_id": "source-experiment", "inventory": {"source/results.jsonl.gz": {"exported": {"sha256": SERVER.file_hash(result_path)}}}})
    write_json(data / "catalog.json", {"runs": [{"id": "treatment-off"}]})
    write_json(data / "runs/treatment-off/run.json", {
        "id": "treatment-off", "case_id": "fixed-case", "treatment_label": "off",
        "samples": [], "provenance": {
            "source_result_path": "source/results.jsonl.gz", "source_result_line": 2,
            "source_protocol_path": "source/protocol.json",
            "source_manifest_path": "source/evidence_manifest.json",
            "protocol_sha": protocol_sha, "source_commit": "original-commit", "policy_sha": "a" * 64,
        },
    })
    media = data / "runs/treatment-off/rollout.mp4"
    media.write_bytes(bytes(range(128)))
    write_json(data / "runs/treatment-off/capture_manifest.json", {"visual_source": "derived_visualization_replay"})
    (data / "runs/treatment-off/poses.npz").write_bytes(b"saved poses")
    write_json(data / "runs/treatment-off/render_manifest.json", {"source": "derived"})
    write_json(data / "runs/treatment-off/parity.json", {"unchanged": True})
    with gzip.open(data / "runs/treatment-off/derived_trace.jsonl.gz", "wt", encoding="utf-8") as stream:
        stream.write('{"command":0}\n')
    source_inventory = inventory(repo / "source")
    source_inventory = {f"source/{p}": record for p, record in source_inventory.items()}
    write_json(data / "manifest.json", {"files": inventory(data), "sources": source_inventory})
    return repo, data, original


@pytest.fixture
def service(artifact):
    repo, root, original = artifact
    data = SERVER.ConsoleData(root, repo_root=repo)
    http = SERVER.ConsoleHTTPServer(("127.0.0.1", 0), data)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http.server_port}", data, original
    http.shutdown()
    http.server_close()
    thread.join(2)


def fetch(url: str, **kwargs):
    try:
        return urlopen(Request(url, **kwargs), timeout=2)
    except HTTPError as error:
        return error


def test_original_evidence_preserved_and_allowlisted(service):
    url, _, original = service
    with fetch(url + "/api/evidence/treatment-off") as response:
        evidence = json.load(response)
    assert evidence["source_result"] == original
    source_link = next(link for link in evidence["raw_links"] if link["label"] == "Original machine result")
    assert source_link["locator"] == "decoded JSONL line 2"
    with fetch(url + source_link["url"]) as response:
        assert response.headers["Content-Type"] == "application/gzip"
        decoded = gzip.decompress(response.read()).decode().splitlines()
        assert json.loads(decoded[1]) == original
    with fetch(url + "/raw/treatment-off/unknown") as response:
        assert response.status == 404
    for key in ("poses", "render-manifest", "parity", "derived-trace"):
        assert any(link["url"] == f"/raw/treatment-off/{key}" for link in evidence["raw_links"])
        with fetch(url + f"/raw/treatment-off/{key}") as response:
            assert response.status == 200


def test_catalog_reports_verified_sources(service):
    url, _, _ = service
    with fetch(url + "/api/catalog") as response:
        result = json.load(response)
    assert result["integrity"]["status"] == "VERIFIED"
    assert result["integrity"]["source_files"] == 3
    assert result["integrity"]["read_only"] is True


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_mutations_rejected(service, method):
    url, _, _ = service
    with fetch(url + "/api/runs/treatment-off", method=method, data=b"{\"reward\":1}") as response:
        assert response.status == 405


@pytest.mark.parametrize("range_header,expected_status,expected", [
    ("bytes=10-19", 206, bytes(range(10, 20))),
    ("bytes=125-", 206, bytes(range(125, 128))),
    ("bytes=-4", 206, bytes(range(124, 128))),
    ("bytes=0-200", 206, bytes(range(128))),
    ("bytes=129-", 416, b""),
    ("bytes=19-10", 416, b""),
    ("bytes=1-3,7-9", 416, b""),
    ("bytes=-0", 416, b""),
])
def test_media_seek_ranges(service, range_header, expected_status, expected):
    url, _, _ = service
    with fetch(url + "/media/treatment-off/rollout.mp4", headers={"Range": range_header}) as response:
        assert response.status == expected_status
        assert response.read() == expected


def test_head_media_has_no_body(service):
    url, _, _ = service
    with fetch(url + "/media/treatment-off/rollout.mp4", method="HEAD", headers={"Range": "bytes=10-19"}) as response:
        assert response.status == 206
        assert response.headers["Content-Length"] == "10"
        assert response.read() == b""


@pytest.mark.parametrize("path", ["/static/../server.py", "/static/%2e%2e/server.py", "/raw/treatment-off/../../source/protocol.json", "/media/treatment-off/../../source/protocol.json"])
def test_traversal_is_denied(service, path):
    url, _, _ = service
    with fetch(url + path) as response:
        assert response.status in (404, 409)


def test_foreign_origin_and_host_denied(service):
    url, _, _ = service
    with fetch(url + "/api/catalog", headers={"Origin": "https://example.com"}) as response:
        assert response.status == 403
    with fetch(url + "/api/catalog", headers={"Host": "example.com"}) as response:
        assert response.status == 403


def test_hash_mismatch_blocks_startup(artifact):
    repo, data, _ = artifact
    (repo / "source/protocol.json").write_text('{"threshold":0.56}', encoding="utf-8")
    with pytest.raises(SERVER.IntegrityError, match="hash mismatch"):
        SERVER.ConsoleData(data, repo_root=repo)


def test_changed_media_not_served(service):
    url, data, _ = service
    (data.data_root / "runs/treatment-off/rollout.mp4").write_bytes(b"changed")
    with fetch(url + "/media/treatment-off/rollout.mp4") as response:
        assert response.status == 409


def test_result_locator_cannot_point_to_another_case(artifact):
    repo, data, _ = artifact
    path = data / "runs/treatment-off/run.json"
    run = SERVER.load_json(path)
    run["provenance"]["source_result_line"] = 1
    write_json(path, run)
    manifest = SERVER.load_json(data / "manifest.json")
    manifest["files"] = inventory(data)
    write_json(data / "manifest.json", manifest)
    with pytest.raises(SERVER.IntegrityError, match="case_id"):
        SERVER.ConsoleData(data, repo_root=repo)


@pytest.mark.parametrize("identity", ["protocol_sha", "source_commit", "policy_sha"])
def test_provenance_identity_mismatch_blocks_startup(artifact, identity):
    repo, data, _ = artifact
    path = data / "runs/treatment-off/run.json"
    run = SERVER.load_json(path)
    run["provenance"][identity] = "wrong"
    write_json(path, run)
    manifest = SERVER.load_json(data / "manifest.json")
    manifest["files"] = inventory(data)
    write_json(data / "manifest.json", manifest)
    with pytest.raises(SERVER.IntegrityError, match="does not match the run"):
        SERVER.ConsoleData(data, repo_root=repo)


def test_source_protocol_digest_bound_to_acquisition_even_with_new_manifest(artifact):
    repo, data, _ = artifact
    path = repo / "source/protocol.json"
    write_json(path, {"threshold": 0.56})
    manifest = SERVER.load_json(data / "manifest.json")
    manifest["sources"]["source/protocol.json"] = {"sha256": SERVER.file_hash(path), "bytes": path.stat().st_size}
    write_json(data / "manifest.json", manifest)
    with pytest.raises(SERVER.IntegrityError, match="Frozen protocol"):
        SERVER.ConsoleData(data, repo_root=repo)


def test_symlink_escape_is_denied(tmp_path: Path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "secret.json"
    outside.write_text("secret", encoding="utf-8")
    link = root / "escape.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Windows account cannot create symlinks")
    with pytest.raises(SERVER.IntegrityError, match="escapes"):
        SERVER.confined_path(root, "escape.json")
