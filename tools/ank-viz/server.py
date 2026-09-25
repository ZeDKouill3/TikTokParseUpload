"""Visualiseur ank : `python tools/ank-viz/server.py [--port 8765]`.

Sert une page HTML qui se rafraîchit seule. Un thread de fond interroge
`ank ... --json` et `git` ; la page ne lit que le dernier état collecté.
"""
import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ankviz  # noqa: E402

PAGE = HERE / "index.html"


def make_server(host, port, snapshot):
    """`snapshot()` rend l'état courant (dict sérialisable)."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, ctype, body):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", PAGE.read_text(encoding="utf-8"))
            elif path == "/api/state":
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(snapshot(), ensure_ascii=False))
            else:
                self._send(404, "text/plain; charset=utf-8", "introuvable")

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def make_runner(cwd):
    resolved = {}

    def run(argv):
        # sous Windows, ank est un ank.CMD (npm) que subprocess ne trouve pas seul
        exe = resolved.setdefault(argv[0], shutil.which(argv[0]) or argv[0])
        proc = subprocess.run([exe] + list(argv[1:]), cwd=str(cwd), capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError("%s: %s" % (" ".join(argv[:3]), proc.stderr.decode("utf-8", "replace").strip()))
        return proc.stdout.decode("utf-8")
    return run


class Poller:
    def __init__(self, collector, interval):
        self.collector = collector
        self.interval = interval
        self.lock = threading.Lock()
        self.state = {"loading": True}

    def loop(self):
        while True:
            started = time.time()
            try:
                state = self.collector.refresh()
                state["error"] = None
            except Exception as exc:  # l'erreur s'affiche dans la page, le serveur continue
                with self.lock:
                    state = dict(self.state, error=str(exc))
            state["loading"] = False
            state["collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            state["collect_seconds"] = round(time.time() - started, 1)
            state["interval"] = self.interval
            with self.lock:
                self.state = state
            time.sleep(self.interval)

    def snapshot(self):
        with self.lock:
            return self.state


def main():
    ap = argparse.ArgumentParser(description="Visualiseur ank local")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--interval", type=float, default=5.0, help="secondes entre deux collectes")
    ap.add_argument("--repo", default=None, help="racine du dépôt (défaut : celui du script)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    start = Path(args.repo) if args.repo else HERE
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(start),
                          capture_output=True, text=True, check=True).stdout.strip()
    poller = Poller(ankviz.Collector(make_runner(root)), args.interval)
    threading.Thread(target=poller.loop, daemon=True).start()

    httpd = make_server(args.host, args.port, poller.snapshot)
    url = "http://%s:%d/" % (args.host, httpd.server_address[1])
    print("ank-viz sur %s (dépôt %s), Ctrl+C pour arrêter" % (url, root))
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
