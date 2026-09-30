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


def native_ank(path):
    """Le ank.exe natif derrière le shim npm (ank.CMD -> node -> binaire) :
    ~1,5 s de gagnées par appel. Sans binaire trouvé, le chemin reste tel quel."""
    shim = Path(path)
    if shim.suffix.lower() not in (".cmd", ".ps1", ""):
        return path
    pkgs = shim.parent / "node_modules" / "@haksolot" / "ank" / "node_modules" / "@haksolot"
    for exe in sorted(pkgs.glob("ank-*/bin/ank.exe")) + sorted(pkgs.glob("ank-*/bin/ank")):
        if exe.is_file():
            return str(exe)
    return path


def make_runner(cwd):
    resolved = {}

    def run(argv):
        # sous Windows, ank est un ank.CMD (npm) que subprocess ne trouve pas seul
        if argv[0] not in resolved:
            found = shutil.which(argv[0]) or argv[0]
            resolved[argv[0]] = native_ank(found) if argv[0] == "ank" else found
        exe = resolved[argv[0]]
        proc = subprocess.run([exe] + list(argv[1:]), cwd=str(cwd), capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError("%s: %s" % (" ".join(argv[:3]), proc.stderr.decode("utf-8", "replace").strip()))
        return proc.stdout.decode("utf-8")
    return run


class StatusPoller:
    """Interroge `ank status --json` en continu, indépendamment du reste.

    Cet appel peut rester bloqué plusieurs minutes sans rapport avec la
    taille du dépôt (TASK-7177 : mesuré > 160 s, quasi aucun CPU consommé
    pendant l'attente) ; il ne doit donc jamais retarder l'affichage des
    tâches. Garde le dernier statut connu, son âge et si une collecte est en
    cours, pour que la page ne présente jamais une information périmée comme
    si elle était fraîche (ADR-ad2e)."""

    def __init__(self, run, min_pause=1.0):
        self.run = run
        self.min_pause = min_pause
        self.lock = threading.Lock()
        self.state = {"data": None, "loading": True, "collecting": True,
                      "collected_at": None, "collect_seconds": None, "error": None}

    def loop(self):
        while True:
            with self.lock:
                self.state = dict(self.state, collecting=True)
            started = time.time()
            try:
                data = ankviz.parse_status(self.run(["ank", "status", "--json"]))
                update = {"data": data, "loading": False, "collecting": False,
                          "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "collect_seconds": round(time.time() - started, 1), "error": None}
            except Exception as exc:  # l'erreur s'affiche dans la page, le serveur continue
                update = {"loading": False, "collecting": False, "error": str(exc)}
            with self.lock:
                self.state = dict(self.state, **update)
            time.sleep(self.min_pause)

    def snapshot(self):
        with self.lock:
            return dict(self.state)


class Poller:
    def __init__(self, collector, interval, status_poller):
        self.collector = collector
        self.interval = interval
        self.status_poller = status_poller
        self.lock = threading.Lock()
        self.state = {"loading": True}

    def loop(self):
        quick = True  # première passe sans critères : la page s'affiche en quelques secondes
        while True:
            started = time.time()
            status = self.status_poller.snapshot()
            default_branch = (status["data"] or {}).get("default_branch")
            try:
                state = self.collector.refresh(criteria=not quick, default_branch=default_branch)
                state["error"] = None
            except Exception as exc:  # l'erreur s'affiche dans la page, le serveur continue
                with self.lock:
                    state = dict(self.state, error=str(exc))
            state["loading"] = False
            state["collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            state["collect_seconds"] = round(time.time() - started, 1)
            state["interval"] = self.interval
            state["status"] = status["data"]
            state["status_loading"] = status["loading"]
            state["status_collecting"] = status["collecting"]
            state["status_collected_at"] = status["collected_at"]
            state["status_error"] = status["error"]
            with self.lock:
                self.state = state
            if quick:
                quick = False
                continue
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
    run = make_runner(root)
    status_poller = StatusPoller(run)
    poller = Poller(ankviz.Collector(run), args.interval, status_poller)
    threading.Thread(target=status_poller.loop, daemon=True).start()
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
