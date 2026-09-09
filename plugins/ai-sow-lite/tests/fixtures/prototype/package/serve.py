"""Serve only this synthetic package on loopback with an automatically chosen port."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __name__ == '__main__':
    handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).resolve().parent))
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        print(f'http://127.0.0.1:{server.server_port}/index.html', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
