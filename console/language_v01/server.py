"""Loopback-only offline contract UI. No dispatch, approval or replay endpoint."""
import argparse
import json
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from g1swarm.language_v01.service import ContractService,ContractError
from g1swarm.language_v01.action import PreparationService

WEB=Path(__file__).with_name('web')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass # Request text is only in explicit local evidence.

    def send(self,code,value,mime='application/json; charset=utf-8'):
        body=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        for key,val in {'Content-Type':mime,'Content-Length':str(len(body)),
                        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                        'Content-Security-Policy':"default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"}.items():
            self.send_header(key,val)
        self.end_headers(); self.wfile.write(body)

    def guarded(self):
        host=self.headers.get('Host','')
        expected=f'127.0.0.1:{self.server.server_port}'
        if host!=expected: raise PermissionError('LOOPBACK_HOST_REQUIRED')
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+expected: raise PermissionError('SAME_ORIGIN_REQUIRED')
        self.connection.settimeout(5)

    def do_GET(self):
        try:
            self.guarded(); path=urlsplit(self.path).path
            if path in ['/','/app.js','/style.css']:
                name='index.html' if path=='/' else path[1:]
                mime={'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8'}[name]
                self.send(200,(WEB/name).read_bytes(),mime)
            elif path.startswith('/api/requests/') and path.endswith('/preparation') and len(path.split('/'))==5:
                if self.server.preparations is None: raise KeyError('EXECUTION_IDENTITY_NOT_CONFIGURED')
                self.send(200,self.server.preparations.get(path.split('/')[3]))
            elif path.startswith('/api/requests/') and len(path.split('/'))==4:
                self.send(200,self.server.service.get(path.split('/')[-1]))
            elif path=='/api/health': self.send(200,{'mode':'OFFLINE_CONTRACT_ONLY','execution':'BLOCKED'})
            else: self.send(404,{'error':'NOT_FOUND_NO_EXECUTION_ENDPOINT'})
        except PermissionError as e: self.send(403,{'error':str(e)})
        except KeyError as e: self.send(404,{'error':str(e)})

    def do_POST(self):
        try:
            self.connection.settimeout(5)
            if self.headers.get('Transfer-Encoding'): raise ContractError('TRANSFER_ENCODING_NOT_ALLOWED')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ContractError('JSON_REQUIRED')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=4096: raise ContractError('BODY_SIZE_LIMIT')
            raw=self.rfile.read(length)
            # Drain this small bounded body before refusing origin, so Windows
            # TCP close does not turn the explicit refusal into a reset.
            self.guarded()
            document=json.loads(raw)
            if not isinstance(document,dict): raise ContractError('OBJECT_REQUIRED')
            path=urlsplit(self.path).path
            if path=='/api/requests':
                if set(document)!={'text'}: raise ContractError('ONLY_TEXT_ACCEPTED_NO_AUTHORITY_FIELDS')
                self.send(200,self.server.service.create(document['text']))
            elif path.startswith('/api/requests/') and path.endswith('/check') and len(path.split('/'))==5:
                if set(document)!={'contract_sha256'}: raise ContractError('ONLY_BINDING_HASH_ACCEPTED')
                self.send(200,self.server.service.check(path.split('/')[3],document['contract_sha256']))
            elif path.startswith('/api/requests/') and path.endswith('/prepare') and len(path.split('/'))==5:
                if set(document)!={'contract_sha256'}: raise ContractError('ONLY_BINDING_HASH_ACCEPTED_NO_AUTHORITY_FIELDS')
                if self.server.preparations is None: raise ContractError('EXECUTION_IDENTITY_NOT_CONFIGURED')
                self.send(200,self.server.preparations.prepare(path.split('/')[3],document['contract_sha256']))
            else: self.send(404,{'error':'NOT_FOUND_NO_EXECUTION_ENDPOINT'})
        except PermissionError as e: self.send(403,{'error':str(e)})
        except KeyError as e: self.send(404,{'error':str(e)})
        except (ValueError,OSError) as e: self.send(409,{'error':str(e)})

def build_server(port=8780,evidence_dir=None,readiness=None,readiness_sha256=None):
    server=HTTPServer(('127.0.0.1',port),Handler)
    server.service=ContractService(evidence_dir)
    server.preparations=PreparationService(server.service,readiness,readiness_sha256) if readiness else None
    return server

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--port',type=int,default=8780)
    p.add_argument('--evidence-dir',type=Path,required=True)
    p.add_argument('--readiness',type=Path); p.add_argument('--readiness-sha256')
    a=p.parse_args(); server=build_server(a.port,a.evidence_dir,a.readiness,a.readiness_sha256)
    print(f'Offline Language-to-G1: http://127.0.0.1:{server.server_port} | NO EXECUTION',flush=True)
    try: server.serve_forever()
    finally: server.server_close()
