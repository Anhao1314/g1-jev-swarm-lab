"""Read-only, explicitly pinned archived Language-to-G1 result viewer.

This does not restore a live request service, compile instructions, issue grants,
or import an executor. The operator supplies the archive index and its SHA256.
Every data/video request rechecks archived bytes; no previous PASS is cached.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from g1swarm.language_v01.observations import audit_capture

WEB = Path(__file__).with_name('saved_web')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


class SavedArchive:
    def __init__(self, index, index_sha256, request_id):
        require(bool(re.fullmatch('[a-f0-9]{64}', index_sha256)), 'INVALID_INDEX_SHA256')
        require(bool(re.fullmatch('[a-f0-9]{32}', request_id)), 'INVALID_REQUEST_ID')
        self.index = Path(index).resolve()
        self.index_sha256 = index_sha256
        self.request_id = request_id

    def read(self):
        """Return one verified presentation and video bytes, never authority."""
        raw = self.index.read_bytes()
        require(sha(raw) == self.index_sha256, 'ARCHIVE_INDEX_CHANGED')
        index = json.loads(raw)
        require(index.get('schema') == 'additive-execution-closeout/1', 'UNKNOWN_ARCHIVE_SCHEMA')
        run_id = index['run_id']
        require(bool(re.fullmatch('[a-f0-9]{32}', run_id)), 'INVALID_RUN_ID')
        files = {}
        for name, pin in index['files'].items():
            path = Path(name)
            require(path.is_absolute(), 'ABSOLUTE_ARCHIVE_PATH_REQUIRED')
            path = path.resolve()
            require(path not in files, 'DUPLICATE_ARCHIVE_PATH')
            data = path.read_bytes()
            require(len(data) == pin['bytes'] and sha(data) == pin['sha256'],
                    'ARCHIVE_BYTES_CHANGED:' + path.name)
            files[path] = data

        def content(path):
            path = Path(path).resolve()
            require(path in files, 'UNPINNED_REQUIRED_FILE:' + path.name)
            return files[path]

        def document(path):
            return json.loads(content(path))

        candidates = [p for p in files if p.name == self.request_id + '-preparation.json']
        require(len(candidates) == 1, 'REQUEST_NOT_UNIQUELY_PINNED')
        prep_path = candidates[0]
        p = document(prep_path)
        unsigned = dict(p)
        claimed = unsigned.pop('preparation_sha256')
        require(sha(canonical(unsigned)) == claimed, 'PREPARATION_DIGEST_MISMATCH')
        request = document(prep_path.parent / (self.request_id + '.json'))
        require(p['request_id'] == self.request_id and request == p['request'], 'REQUEST_MISMATCH')
        unsigned = dict(request)
        contract_sha = unsigned.pop('contract_sha256')
        require(sha(canonical(unsigned)) == contract_sha == p['contract_sha256'], 'CONTRACT_MISMATCH')
        binding = unsigned.pop('binding')
        require(sha(canonical(unsigned)) == binding['request_sha256'], 'REQUEST_DIGEST_MISMATCH')
        require(p['mission'] == request['mission'] and
                sha(canonical(p['mission'])) == p['mission_sha256'] == binding['mission_sha256'],
                'MISSION_MISMATCH')
        require(sha(request['source']['text'].encode('utf-8')) == request['source']['sha256'],
                'INSTRUCTION_MISMATCH')
        evidence = Path(p['evidence_root']).resolve()
        require(evidence == prep_path.parent, 'EVIDENCE_ROOT_MISMATCH')
        directory = evidence / 'runs' / run_id
        launch = document(directory / 'launch.json')
        completion = document(directory / 'completion.json')
        physical = document(directory / 'physical.json')
        result = document(directory / 'result.json')
        media = document(directory / 'media.json')
        authorization = document(directory / 'authorization.json')
        processes = {}
        for key, subdirectory in (('process', 'worker-process'), ('outer_process', 'outer-process'),
                                  ('render_process', 'render-process')):
            processes[key] = document(directory / subdirectory / 'process_receipt.json')
            require(processes[key] == completion[key], 'PROCESS_RECEIPT_MISMATCH')
        context = {'preparation_sha256': claimed, 'C_exec': p['C_exec']}
        for record in (launch, completion, physical, media):
            require(all(record.get(k) == v for k, v in context.items()), 'RUN_CONTEXT_MISMATCH')
        require(launch['run_id'] == completion['run_id'] == run_id and
                completion['request_id'] == physical['request_id'] == media['request_id'] == self.request_id,
                'RUN_REQUEST_MISMATCH')
        require(Path(launch['preparation']).resolve() == prep_path and
                launch['readiness_sha256'] == p['readiness_sha256'] and
                sha(content(launch['readiness'])) == p['readiness_sha256'] and
                sha(content(launch['review'])) == launch['review_sha256'], 'LAUNCH_SOURCE_MISMATCH')
        require(physical['executed_mission_sha256'] == media['executed_mission_sha256'] == p['mission_sha256'],
                'EXECUTED_MISSION_MISMATCH')
        require(physical['runtime_result'] == result and result['mission_id'] == p['mission']['mission_id'],
                'RESULT_MISSION_MISMATCH')
        for name, expected in physical['files'].items():
            child = (directory / name).resolve()
            require(child.is_relative_to(directory), 'RAW_PATH_OUTSIDE_RUN')
            require(sha(content(child)) == expected, 'PHYSICAL_FILE_MISMATCH')
        # Reuse the retained raw counter/nonfinite/fall auditor; no rescore or
        # live-source verification. All referenced bytes above are index-pinned.
        audited = audit_capture(directory, p)
        require(audited['passed'], 'RAW_AUDIT_REJECTED:' + ','.join(audited['errors']))
        physical_sha = sha(content(directory / 'physical.json'))
        require(completion['physical_sha256'] == media['source_physical_sha256'] == physical_sha and
                media['source_result_sha256'] == sha(content(directory / 'result.json')),
                'COMPLETION_MEDIA_MISMATCH')
        require(physical['kind'] == 'NEW_MUJOCO_CAPTURE' and media['new_capture'] is True and
                media['historical_fallback'] is False and media['file'] == 'video.mp4', 'NOT_BOUND_CAPTURE')
        video = content(directory / 'video.mp4')
        require(sha(video) == media['renderer']['video_sha256'] and
                sha(content(directory / 'poses.npz')) == media['renderer']['source_pose_sha256'],
                'VIDEO_POSE_MISMATCH')
        require(authorization['preparation_sha256'] == claimed and
                authorization['comment_id'] == launch['owner_comment_id'] and
                authorization['accepted_independent_review_sha256'] == launch['review_sha256'] and
                authorization['raw_sha256'] == sha(canonical(document(directory / 'owner-source.json'))),
                'ARCHIVED_AUTHORIZATION_MISMATCH')
        consumed = document(evidence / 'owner-consumed' / ('request-' + self.request_id + '.json'))
        comment = document(evidence / 'owner-consumed' / ('comment-' + str(authorization['comment_id']) + '.json'))
        require(consumed == comment and consumed['run_id'] == run_id and
                consumed['preparation_sha256'] == claimed and
                consumed['owner_comment_id'] == authorization['comment_id'], 'CONSUMPTION_MISMATCH')
        # Re-read indexed bytes after the raw auditor, so a mutation during that
        # read cannot silently produce a current PASS. HTTP serves verified bytes.
        require(self.index.read_bytes() == raw and all(path.read_bytes() == data for path, data in files.items()),
                'ARCHIVE_CHANGED_DURING_READ')
        answer = {'mode': 'READ_ONLY_SAVED_RESULT', 'request_id': self.request_id,
                  'run_id': run_id, 'instruction': request['source']['text'],
                  'status': completion['status'], 'result': result,
                  'physics_steps': physical['native_completed'],
                  'policy_calls': physical['policy_inference_completed'],
                  'media': {'url': '/video', 'frames': media['renderer']['frames'],
                            'fps': media['renderer']['fps'], 'sha256': sha(video)},
                  'provenance': {'index_sha256': self.index_sha256, 'C_exec': p['C_exec'],
                                 'mission_sha256': p['mission_sha256'], 'preparation_sha256': claimed,
                                 'readiness_sha256': p['readiness_sha256'],
                                 'physical_sha256': physical_sha, 'protocol_sha256': p['protocol_sha256']},
                  'authority': {'consumed': True, 'comment_url': authorization['url'],
                                'assurance': authorization['assurance'],
                                'original_language_proposal': authorization['original_language_proposal'],
                                'language_runtime': authorization['language_runtime'], 'd011': authorization['d011']},
                  'process_receipts': processes,
                  'raw_audit': audited}
        return answer, video


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body, mime='application/json; charset=utf-8', headers=None):
        if not isinstance(body, bytes):
            body = canonical(body)
        self.send_response(status)
        for key, value in {'Content-Type': mime, 'Content-Length': str(len(body)),
                           'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                           'Content-Security-Policy': "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
                           **(headers or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.close_connection = True
        self.reply(405, {'error': 'READ_ONLY_NO_EXECUTION_ENDPOINT'})

    do_PUT = do_DELETE = do_PATCH = do_POST

    def do_GET(self):
        try:
            self.connection.settimeout(5)
            host = '127.0.0.1:' + str(self.server.server_port)
            if self.headers.get('Host') != host or self.headers.get('Origin', 'http://' + host) != 'http://' + host:
                self.reply(403, {'error': 'LOOPBACK_SAME_ORIGIN_REQUIRED'})
                return
            if self.path in ('/', '/app.js', '/style.css'):
                name = 'index.html' if self.path == '/' else self.path[1:]
                mime = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8',
                        'style.css': 'text/css; charset=utf-8'}[name]
                self.reply(200, (WEB / name).read_bytes(), mime)
            elif self.path in ('/api/result', '/video'):
                answer, video = self.server.archive.read()
                if self.path == '/api/result':
                    self.reply(200, answer)
                    return
                headers = {'Accept-Ranges': 'bytes'}
                first, last = 0, len(video) - 1
                requested = self.headers.get('Range')
                if requested:
                    match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
                    if not match:
                        self.reply(416, {'error': 'SINGLE_RANGE_REQUIRED'})
                        return
                    first = int(match[1])
                    last = min(last, int(match[2])) if match[2] else last
                    if first > last:
                        self.reply(416, {'error': 'RANGE_OUTSIDE_VIDEO'})
                        return
                    headers['Content-Range'] = f'bytes {first}-{last}/{len(video)}'
                self.reply(206 if requested else 200, video[first:last + 1], 'video/mp4', headers)
            else:
                self.reply(404, {'error': 'NOT_FOUND'})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            # Failure replaces prior presentation; never serve cached success.
            self.reply(409, {'error': 'ARCHIVE_REJECTED', 'reason': str(exc)})


def build_server(index, index_sha256, request_id, port=8783):
    archive = SavedArchive(index, index_sha256, request_id)
    archive.read()  # Refuse startup with incomplete/unbound retained evidence.
    server = HTTPServer(('127.0.0.1', port), Handler)
    server.archive = archive
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--index-sha256', required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--port', type=int, default=8783)
    args = parser.parse_args()
    server = build_server(args.index, args.index_sha256, args.request_id, args.port)
    print(f'Saved result only: http://127.0.0.1:{server.server_port} | NO EXECUTION', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
