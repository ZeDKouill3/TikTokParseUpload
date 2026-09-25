"""Le serveur sert la page et l'état JSON."""
import json
import threading
import urllib.request

import server


def serve(snapshot):
    httpd = server.make_server("127.0.0.1", 0, snapshot)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read().decode("utf-8")


def test_root_serves_a_self_refreshing_html_page():
    httpd, base = serve(lambda: {"ok": True})
    try:
        code, ctype, body = get(base + "/")
    finally:
        httpd.shutdown()
    assert code == 200
    assert ctype.startswith("text/html")
    assert "/api/state" in body
    assert "setInterval" in body or "setTimeout" in body


def test_api_state_returns_the_latest_snapshot_as_json():
    snaps = iter([{"n": 1}, {"n": 2}])
    httpd, base = serve(lambda: next(snaps))
    try:
        a = json.loads(get(base + "/api/state")[2])
        b = json.loads(get(base + "/api/state")[2])
    finally:
        httpd.shutdown()
    assert (a["n"], b["n"]) == (1, 2)


def test_unknown_path_is_404():
    httpd, base = serve(lambda: {})
    try:
        try:
            urllib.request.urlopen(base + "/nope", timeout=5)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
    finally:
        httpd.shutdown()
    assert code == 404


def test_npm_shim_is_bypassed_for_the_native_binary(tmp_path):
    shim = tmp_path / "ank.CMD"
    shim.write_text("@echo off")
    native = tmp_path / "node_modules" / "@haksolot" / "ank" / "node_modules" / "@haksolot" / "ank-win32-x64" / "bin" / "ank.exe"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"")
    assert server.native_ank(str(shim)) == str(native)


def test_without_native_binary_the_shim_is_kept(tmp_path):
    shim = tmp_path / "ank.CMD"
    shim.write_text("@echo off")
    assert server.native_ank(str(shim)) == str(shim)
    assert server.native_ank("/usr/local/bin/ank") == "/usr/local/bin/ank"
