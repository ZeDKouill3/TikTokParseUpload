"""Tests de clipper.accounts et des routes /api/accounts* (SPEC-6fa4, R1-R7).

Aucun test ne touche le vrai coffre : un backend keyring en memoire est
branche (accounts.use_backend). Aucun reseau.
"""

from __future__ import annotations

import json
import logging
import re
import string
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from keyring.backends import fail as keyring_fail
from keyring.backends import null as keyring_null
from keyring.errors import PasswordDeleteError

from clipper import accounts
from clipper.config import Config
from clipper.web import create_app

STATIC = Path(__file__).resolve().parent.parent / "clipper" / "web" / "static"
PWD = "Sup3r-Secret-Exemple!"
LOCAL = "http://127.0.0.1:8000"


class MemoryKeyring:
    """Duck-typing volontaire : un sous-classe de KeyringBackend s'enregistrerait dans keyring
    (ChainerBackend) et polluerait le vrai coffre vu par les autres tests du processus."""

    priority = 1

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def get_password(self, service, username):
        return self.store.get((service, username))

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise PasswordDeleteError("absent")
        del self.store[(service, username)]


class PlaintextKeyring(MemoryKeyring):
    pass


class LeakyKeyring(MemoryKeyring):
    """Backend dont les erreurs recopient le mot de passe : il ne doit jamais ressortir."""

    def set_password(self, service, username, password):
        raise RuntimeError(f"echec avec {password}")


@pytest.fixture
def vault():
    backend = MemoryKeyring()
    accounts.use_backend(backend)
    yield backend
    accounts.use_backend(None)


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return Config(mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")


def local_client(config) -> TestClient:
    return TestClient(create_app(config=config), base_url=LOCAL, client=("127.0.0.1", 50000))


NEW = {"label": "Compte exemple", "platform": "TikTok", "username": "exemple@example.com",
       "notes": "ma_chaine", "password": PWD}


# --------------------------------------------------------------------------
# R1 / R2 : stockage, coffre
# --------------------------------------------------------------------------


def test_add_stores_password_in_the_vault_and_never_in_the_file(config, vault):
    account = accounts.add_account(config, NEW)

    assert vault.store == {("clipper-accounts", account["id"]): PWD}
    raw = Path("state/accounts.json").read_text(encoding="utf-8")
    assert PWD not in raw
    on_disk = json.loads(raw)["accounts"][0]
    assert on_disk["label"] == "Compte exemple" and on_disk["has_password"] is True
    assert "password" not in on_disk
    assert "password" not in account and account["has_password"] is True


def test_accounts_section_is_a_valid_config_table():
    assert accounts.CONFIG_DEFAULTS["password_length"] == 20
    assert "state_file" in accounts.CONFIG_DEFAULTS


def test_write_is_atomic_and_leaves_no_temp_file(config, vault):
    accounts.add_account(config, NEW)
    accounts.add_account(config, {"label": "Autre"})
    assert [p.name for p in Path("state").iterdir()] == ["accounts.json"]
    assert len(accounts.list_accounts(config)) == 2


def test_write_failure_keeps_the_previous_file_and_cleans_up(config, vault, monkeypatch):
    accounts.add_account(config, {"label": "Premier"})
    before = Path("state/accounts.json").read_bytes()

    def boom(src, dst):
        raise OSError("disque plein")

    real_replace = accounts.os.replace
    monkeypatch.setattr(accounts.os, "replace", boom)
    with pytest.raises(accounts.AccountsError):
        accounts.add_account(config, NEW)
    monkeypatch.setattr(accounts.os, "replace", real_replace)

    assert Path("state/accounts.json").read_bytes() == before
    assert [p.name for p in Path("state").iterdir()] == ["accounts.json"]
    assert vault.store == {}  # pas de secret orphelin dans le coffre


def test_update_changes_fields_and_password(config, vault):
    account = accounts.add_account(config, NEW)
    updated = accounts.update_account(config, account["id"], {"label": "Renommé", "password": "Autre-mdp-12345"})

    assert updated["label"] == "Renommé" and updated["username"] == "exemple@example.com"
    assert vault.store[("clipper-accounts", account["id"])] == "Autre-mdp-12345"
    assert "Autre-mdp-12345" not in Path("state/accounts.json").read_text(encoding="utf-8")


def test_update_without_password_keeps_it_and_empty_password_removes_it(config, vault):
    account = accounts.add_account(config, NEW)
    accounts.update_account(config, account["id"], {"notes": "x"})
    assert vault.store[("clipper-accounts", account["id"])] == PWD

    cleared = accounts.update_account(config, account["id"], {"password": ""})
    assert cleared["has_password"] is False and vault.store == {}


def test_delete_removes_the_account_and_its_vault_entry(config, vault):
    account = accounts.add_account(config, NEW)
    keep = accounts.add_account(config, {"label": "Reste"})

    accounts.delete_account(config, account["id"])

    assert vault.store == {}
    assert [a["id"] for a in accounts.list_accounts(config)] == [keep["id"]]


def test_unknown_account_is_an_explicit_error(config, vault):
    with pytest.raises(accounts.AccountNotFound, match="introuvable"):
        accounts.update_account(config, "nope", {"label": "x"})
    with pytest.raises(accounts.AccountNotFound):
        accounts.delete_account(config, "nope")
    with pytest.raises(accounts.AccountNotFound):
        accounts.get_password(config, "nope")


@pytest.mark.parametrize("backend", [keyring_fail.Keyring(), keyring_null.Keyring(), PlaintextKeyring()],
                         ids=["fail", "null", "plaintext"])
def test_unsafe_vault_refuses_writing_a_password_without_fallback(config, backend):
    accounts.use_backend(backend)
    try:
        with pytest.raises(accounts.VaultUnavailable, match="coffre"):
            accounts.add_account(config, NEW)
    finally:
        accounts.use_backend(None)
    assert not Path("state/accounts.json").exists()  # rien d'ecrit nulle part
    assert getattr(backend, "store", {}) == {}


def test_unsafe_vault_still_allows_accounts_without_password(config):
    accounts.use_backend(keyring_fail.Keyring())
    try:
        account = accounts.add_account(config, {"label": "Sans mot de passe"})
        with pytest.raises(accounts.VaultUnavailable):
            accounts.update_account(config, account["id"], {"password": PWD})
    finally:
        accounts.use_backend(None)


def test_default_backend_is_the_os_one_and_fail_is_refused(config):
    # Sans coffre sur Linux (CI, cloud) : keyring.get_keyring() est le backend fail, refus explicite.
    accounts.use_backend(None)
    import keyring

    if not isinstance(keyring.get_keyring(), keyring_fail.Keyring):
        pytest.skip("un vrai coffre est present : on n'y touche pas dans les tests")
    with pytest.raises(accounts.VaultUnavailable):
        accounts.add_account(config, NEW)


def test_get_password_returns_it_and_flags_a_lost_vault_entry(config, vault):
    account = accounts.add_account(config, NEW)
    assert accounts.get_password(config, account["id"]) == PWD
    vault.store.clear()
    with pytest.raises(accounts.AccountsError, match="ne contient plus"):
        accounts.get_password(config, account["id"])
    nopass = accounts.add_account(config, {"label": "Sans"})
    with pytest.raises(accounts.AccountNotFound, match="aucun mot de passe"):
        accounts.get_password(config, nopass["id"])


def test_validation_errors_are_explicit_and_never_echo_the_password(config, vault):
    for bad, match in [({}, "libellé"), ({"label": 3}, "chaîne"), ({"label": "x", "zzz": 1}, "zzz"),
                       ({"label": "x", "password": 12}, "password"),
                       ({"label": "x", "password": "p" * 600}, "512")]:
        with pytest.raises(accounts.AccountsError, match=match) as err:
            accounts.add_account(config, bad)
        assert "ppp" not in str(err.value)
    with pytest.raises(accounts.AccountsError, match="objet"):
        accounts.add_account(config, ["x"])


def test_corrupt_accounts_file_is_an_explicit_error(config, vault):
    Path("state").mkdir()
    Path("state/accounts.json").write_text("{pas du json", encoding="utf-8")
    with pytest.raises(accounts.AccountsError, match="illisible"):
        accounts.list_accounts(config)


# --------------------------------------------------------------------------
# R4 : jamais le mot de passe hors de la route dediee
# --------------------------------------------------------------------------


def test_list_has_no_password_only_has_password(config, vault):
    accounts.add_account(config, NEW)
    listed = accounts.list_accounts(config)
    assert PWD not in json.dumps(listed)
    assert listed[0]["has_password"] is True and "password" not in listed[0]


def test_vault_errors_and_logs_never_contain_the_password(config, caplog):
    caplog.set_level(logging.DEBUG)
    accounts.use_backend(LeakyKeyring())
    try:
        with pytest.raises(accounts.AccountsError) as err:
            accounts.add_account(config, NEW)
    finally:
        accounts.use_backend(None)
    assert PWD not in str(err.value) and PWD not in repr(err.value)
    assert PWD not in caplog.text
    import traceback

    assert PWD not in "".join(traceback.format_exception(err.value))


def test_http_flow_never_leaks_the_password_except_on_the_dedicated_route(config, vault, caplog):
    caplog.set_level(logging.DEBUG)
    c = local_client(config)

    created = c.post("/api/accounts", json=NEW)
    assert created.status_code == 201 and PWD not in created.text
    account_id = created.json()["id"]

    listed = c.get("/api/accounts")
    assert listed.status_code == 200 and PWD not in listed.text
    assert listed.json()[0]["has_password"] is True

    shown = c.get(f"/api/accounts/{account_id}/password")
    assert shown.status_code == 200 and shown.json() == {"password": PWD}
    assert shown.headers["cache-control"] == "no-store"

    bad = c.put(f"/api/accounts/{account_id}", json={"label": 12, "password": PWD})
    assert bad.status_code == 422 and PWD not in bad.text
    bad2 = c.post("/api/accounts", content=f'{{"password": "{PWD}", ', headers={"content-type": "application/json"})
    assert bad2.status_code == 422 and PWD not in bad2.text
    assert PWD not in caplog.text


def test_leaky_vault_over_http_returns_a_clean_error(config):
    accounts.use_backend(LeakyKeyring())
    try:
        resp = local_client(config).post("/api/accounts", json=NEW)
    finally:
        accounts.use_backend(None)
    assert resp.status_code == 422 and PWD not in resp.text


def test_unsafe_vault_over_http_is_503_in_french(config):
    accounts.use_backend(keyring_fail.Keyring())
    try:
        resp = local_client(config).post("/api/accounts", json=NEW)
    finally:
        accounts.use_backend(None)
    assert resp.status_code == 503 and "coffre" in resp.json()["detail"]
    assert PWD not in resp.text


def test_crud_over_http(config, vault):
    c = local_client(config)
    account_id = c.post("/api/accounts", json=NEW).json()["id"]
    changed = c.put(f"/api/accounts/{account_id}", json={"label": "Nouveau"})
    assert changed.status_code == 200 and changed.json()["label"] == "Nouveau"
    assert c.put("/api/accounts/inconnu", json={"label": "x"}).status_code == 404
    assert c.request("DELETE", f"/api/accounts/{account_id}", json={}).status_code == 204
    assert c.get("/api/accounts").json() == [] and vault.store == {}
    assert c.get(f"/api/accounts/{account_id}/password").status_code == 404


# --------------------------------------------------------------------------
# R3 : PC seulement
# --------------------------------------------------------------------------

ROUTES = [
    ("get", "/api/accounts"), ("post", "/api/accounts"), ("post", "/api/accounts/generate"),
    ("put", "/api/accounts/abc"), ("delete", "/api/accounts/abc"), ("get", "/api/accounts/abc/password"),
]


def _call(c, method, path, **kw):
    if method == "get":
        return c.get(path, **kw)
    kw.setdefault("json", {})
    return c.request(method.upper(), path, **kw)


@pytest.mark.parametrize("method,path", ROUTES)
def test_remote_client_address_is_refused_even_with_a_valid_token(tmp_path, monkeypatch, vault, method, path):
    monkeypatch.chdir(tmp_path)
    cfg = Config(mode="review", workspace_dir=tmp_path / "w", output_dir=tmp_path / "o",
                 _sections={"web": {"host": "0.0.0.0", "token": "jeton-exemple"}})
    c = TestClient(create_app(config=cfg), base_url=LOCAL, client=("192.168.1.20", 50000))
    resp = _call(c, method, path, headers={"x-clipper-token": "jeton-exemple"})
    assert resp.status_code == 403
    assert "PC" in resp.json()["detail"] and "bouclage" in resp.json()["detail"]


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8000", "127.0.0.1.evil.com", "127.0.0.1:80:80", ""])
def test_foreign_host_header_is_refused_even_from_loopback(config, vault, method, path, host):
    c = TestClient(create_app(config=config), client=("127.0.0.1", 50000))
    resp = _call(c, method, path, headers={"host": host})
    assert resp.status_code == 403
    assert "Host" in resp.json()["detail"]


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "localhost:8123", "127.0.0.1:8000"])
def test_loopback_host_headers_are_accepted(config, vault, host):
    c = TestClient(create_app(config=config), client=("127.0.0.1", 50000))
    assert c.get("/api/accounts", headers={"host": host}).status_code == 200


def test_ipv6_loopback_client_is_accepted_and_missing_client_refused(config, vault):
    c6 = TestClient(create_app(config=config), base_url=LOCAL, client=("::1", 50000))
    assert c6.get("/api/accounts").status_code == 200
    other = TestClient(create_app(config=config), base_url=LOCAL, client=("not-an-ip", 1))
    assert other.get("/api/accounts").status_code == 403


def test_other_routes_are_not_affected_by_the_local_only_rule(config):
    c = TestClient(create_app(config=config), client=("192.168.1.20", 50000))
    assert c.get("/api/queue").status_code == 200


# --------------------------------------------------------------------------
# R4 : CORS, ecritures JSON seulement
# --------------------------------------------------------------------------


def test_no_cors_headers_and_preflight_is_refused(config, vault):
    c = local_client(config)
    resp = c.get("/api/accounts", headers={"origin": "https://evil.example.com"})
    assert not [h for h in resp.headers if h.lower().startswith("access-control-")]
    pre = c.options("/api/accounts", headers={"origin": "https://evil.example.com",
                                              "access-control-request-method": "POST",
                                              "access-control-request-headers": "content-type"})
    assert pre.status_code >= 400
    assert not [h for h in pre.headers if h.lower().startswith("access-control-")]


@pytest.mark.parametrize("method,path", [("post", "/api/accounts"), ("put", "/api/accounts/abc"),
                                         ("delete", "/api/accounts/abc"), ("post", "/api/accounts/generate")])
def test_writes_without_a_json_body_are_refused(config, vault, method, path):
    c = local_client(config)
    for kwargs in ({}, {"content": "label=x", "headers": {"content-type": "application/x-www-form-urlencoded"}},
                   {"content": '{"label": "x"}', "headers": {"content-type": "text/plain"}}):
        resp = c.request(method.upper(), path, **kwargs)
        assert resp.status_code == 415
        assert "JSON" in resp.json()["detail"]
    assert c.get("/api/accounts").json() == []


# --------------------------------------------------------------------------
# R5 : generateur
# --------------------------------------------------------------------------


def test_default_length_comes_from_config_defaults(config):
    assert len(accounts.generate_password(config)) == accounts.CONFIG_DEFAULTS["password_length"] == 20


@pytest.mark.parametrize("length", [12, 20, 64])
def test_generated_password_has_every_class_and_the_right_length(config, length):
    for _ in range(50):
        pw = accounts.generate_password(config, length)
        assert len(pw) == length
        assert any(c in string.ascii_lowercase for c in pw)
        assert any(c in string.ascii_uppercase for c in pw)
        assert any(c in string.digits for c in pw)
        assert all(c in string.ascii_letters + string.digits for c in pw)


def test_symbols_option_adds_a_symbol_class(config):
    for _ in range(50):
        pw = accounts.generate_password(config, 12, symbols=True)
        assert any(not c.isalnum() for c in pw)
        assert any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw)


def test_avoid_ambiguous_removes_lookalike_characters(config):
    for _ in range(100):
        pw = accounts.generate_password(config, 64, symbols=True, avoid_ambiguous=True)
        assert not set(pw) & set("Il1O0o|")


def test_generator_uses_secrets_not_random(config):
    src = Path(accounts.__file__).read_text(encoding="utf-8")
    assert "import secrets" in src and not re.search(r"^import random|^from random", src, re.M)


@pytest.mark.parametrize("length", [11, 65, 0, -5, 12.5, "20", True])
def test_out_of_bounds_length_is_refused(config, length):
    with pytest.raises(accounts.AccountsError, match="longueur invalide"):
        accounts.generate_password(config, length)


def test_generate_route(config, vault):
    c = local_client(config)
    ok = c.post("/api/accounts/generate", json={"length": 30, "symbols": True, "avoid_ambiguous": True})
    assert ok.status_code == 200 and len(ok.json()["password"]) == 30
    assert len(c.post("/api/accounts/generate", json={}).json()["password"]) == 20
    assert c.post("/api/accounts/generate", json={"length": 5}).status_code == 422
    assert c.post("/api/accounts/generate", json={"length": 70}).status_code == 422
    assert c.post("/api/accounts/generate", json={"symbols": "oui"}).status_code == 422
    assert c.post("/api/accounts/generate", json={"x": 1}).status_code == 422


# --------------------------------------------------------------------------
# R6 : ecran Comptes (test statique)
# --------------------------------------------------------------------------


def test_accounts_screen_is_wired_in_navigation_and_scripts():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    nav = page[page.index('<nav class="nav"'):page.index("</nav>", page.index('<nav class="nav"'))]

    assert 'href="#/accounts"' in nav and 'data-screen="accounts"' in nav
    assert nav.index("Configuration") < nav.index('href="#/accounts"')
    assert 'id="screen-accounts"' in page
    assert "/static/screens/accounts.js" in page
    assert page.index("/static/screens.js") < page.index("/static/screens/accounts.js") < page.index("/static/app.js")
    assert '"accounts"' in app_js


def test_accounts_screen_has_the_spec_features():
    js = (STATIC / "screens" / "accounts.js").read_text(encoding="utf-8")

    assert "Screens.accounts" in js
    for route in ("/api/accounts", "/password", "/api/accounts/generate"):
        assert route in js
    assert "••••" in js and "has_password" in js                      # liste masquée
    for label in ("Copier l'identifiant", "Copier le mot de passe", "Afficher", "Ajouter", "Modifier", "Supprimer"):
        assert label in js
    assert "navigator.clipboard" in js and "Copié" in js
    assert re.search(r"30\s*\*\s*1000|30000", js)                     # re-masqué après 30 s
    assert "confirmDialog" in js                                      # suppression confirmée
    assert "location.hostname" in js and "à distance" in js           # avis console distante
    assert "toastError" in js
    assert "ma_chaine" in js or "exemple@example.com" in js           # exemples neutres


def test_accounts_screen_never_persists_secrets_in_the_browser():
    js = (STATIC / "screens" / "accounts.js").read_text(encoding="utf-8")
    assert "localStorage" not in js and "sessionStorage" not in js
