"""Tests de clipper.journal (TASK-8067 : journal global de toutes les
actions, tous les processus, un fichier par jour, purge au-dela de 2 jours).

Chaque groupe de tests correspond a une clause du done_criteria. Aucun test
n'utilise le reseau, le GPU ni le vrai LLM ; le test multi-processus lance de
vrais sous-processus Python (CPU, fichiers locaux seulement).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipper import journal
from clipper.config import Config


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Les tests d'installation posent un vrai JournalHandler sur le logger
    racine (partage par tout le processus pytest) : on l'enleve et on
    restaure le niveau d'origine, pour qu'aucun test d'ici ou d'ailleurs dans
    la suite n'en herite."""
    root = logging.getLogger()
    before_handlers = list(root.handlers)
    before_level = root.level
    yield
    for handler in list(root.handlers):
        if handler not in before_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(before_level)


def _record(message: str, *, name: str = "clipper.test", level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(name, level, "", 0, message, None, None)


def _journal_config(dir_path: Path, **overrides) -> Config:
    overrides.setdefault("dir", str(dir_path))
    return Config(
        mode="review", workspace_dir=dir_path / "workspace", output_dir=dir_path / "output",
        _sections={"journal": overrides},
    )


# --------------------------------------------------------------------------
# Clause 1 : CONFIG_DEFAULTS, install() sur le logger racine
# --------------------------------------------------------------------------


def test_config_defaults_declares_the_documented_keys():
    assert journal.CONFIG_DEFAULTS == {
        "enabled": True, "dir": "logs", "retention_days": 2,
        "level": "INFO", "exclude_paths": ["/static/", "/media/"],
    }


def test_install_adds_a_single_journalhandler_to_the_root_logger(tmp_path):
    config = _journal_config(tmp_path / "logs")

    handler = journal.install("run", config)

    assert isinstance(handler, journal.JournalHandler)
    assert handler in logging.getLogger().handlers


def test_install_is_idempotent_within_the_same_process(tmp_path):
    config = _journal_config(tmp_path / "logs")

    first = journal.install("run", config)
    second = journal.install("run", config)

    assert first is second
    assert sum(isinstance(h, journal.JournalHandler) for h in logging.getLogger().handlers) == 1


def test_install_disabled_adds_no_handler_and_creates_no_directory(tmp_path):
    config = _journal_config(tmp_path / "logs", enabled=False)

    handler = journal.install("run", config)

    assert handler is None
    assert not any(isinstance(h, journal.JournalHandler) for h in logging.getLogger().handlers)
    assert not (tmp_path / "logs").exists()


def test_install_removes_an_existing_handler_when_disabled_afterwards(tmp_path):
    config = _journal_config(tmp_path / "logs")
    journal.install("run", config)

    disabled = _journal_config(tmp_path / "logs", enabled=False)
    journal.install("run", disabled)

    assert not any(isinstance(h, journal.JournalHandler) for h in logging.getLogger().handlers)


def test_install_lowers_the_root_level_so_its_own_level_gets_through(tmp_path):
    """Independance de la verbosite console : meme si le logger racine est
    deja plus strict (ex. ERROR, comme sans -v), un message INFO journalise
    via un logger clipper.* ordinaire doit atteindre le fichier."""
    root = logging.getLogger()
    root.setLevel(logging.ERROR)
    config = _journal_config(tmp_path / "logs")

    journal.install("run", config)
    logging.getLogger("clipper.some_module_quelconque").info("doit atteindre le journal malgre la console silencieuse")

    today = journal._today()
    content = (tmp_path / "logs" / f"journal-{today.isoformat()}.log").read_text(encoding="utf-8")
    assert "doit atteindre le journal malgre la console silencieuse" in content


def test_install_rejects_an_unknown_level_name(tmp_path):
    config = _journal_config(tmp_path / "logs", level="PAS_UN_NIVEAU")

    with pytest.raises(ValueError):
        journal.install("run", config)


# --------------------------------------------------------------------------
# Clause 2 : format de ligne, horodatage Paris, rotation, ecriture multi-processus
# --------------------------------------------------------------------------


def test_format_line_uses_paris_time_never_system_local_time():
    record = _record("x")
    record.created = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc).timestamp()  # hiver : Paris = UTC+1

    line = journal.format_line(record, "run[1]")

    assert line.startswith("2026-01-15T11:00:00")


def test_format_line_uses_paris_summer_offset():
    record = _record("x")
    record.created = datetime(2026, 7, 15, 10, 0, 0, tzinfo=timezone.utc).timestamp()  # ete : Paris = UTC+2

    line = journal.format_line(record, "run[1]")

    assert line.startswith("2026-07-15T12:00:00")


def test_format_line_has_process_level_logger_and_message_tab_separated():
    record = _record("un evenement", name="clipper.pipeline", level=logging.WARNING)

    line = journal.format_line(record, "worker[9]")

    timestamp, process, level, logger_name, message = line.rstrip("\n").split("\t")
    datetime.fromisoformat(timestamp)  # ne leve pas
    assert process == "worker[9]"
    assert level == "WARNING"
    assert logger_name == "clipper.pipeline"
    assert message == "un evenement"
    assert line.count("\n") == 1


def test_format_line_flattens_embedded_newlines_to_one_physical_line():
    record = _record("ligne1\nligne2\r\nligne3")

    line = journal.format_line(record, "run[1]")

    assert line.count("\n") == 1
    assert "ligne1 ligne2 ligne3" in line


def test_parse_line_round_trips_format_line():
    record = _record("attention", name="clipper.pipeline", level=logging.ERROR)
    line = journal.format_line(record, "worker[9]")

    parsed = journal.parse_line(line)

    assert parsed["process"] == "worker[9]"
    assert parsed["level"] == "ERROR"
    assert parsed["logger"] == "clipper.pipeline"
    assert parsed["message"] == "attention"
    assert parsed["raw"] == line.rstrip("\n")


def test_parse_line_keeps_a_malformed_line_as_raw_message_instead_of_crashing():
    parsed = journal.parse_line("une ligne sans les bons separateurs\n")

    assert parsed["timestamp"] is None
    assert parsed["process"] is None
    assert parsed["message"] == "une ligne sans les bons separateurs"


def test_handler_writes_one_file_per_day_named_journal_date(tmp_path):
    handler = journal.JournalHandler(tmp_path / "logs", "run[1]", retention_days=2)
    try:
        handler.emit(_record("un evenement"))
    finally:
        handler.close()

    today = journal._today()
    path = tmp_path / "logs" / f"journal-{today.isoformat()}.log"
    assert path.is_file()
    assert "un evenement" in path.read_text(encoding="utf-8")


def test_handler_rolls_over_to_a_new_file_at_the_next_paris_day(tmp_path, monkeypatch):
    day_a, day_b = date(2026, 10, 3), date(2026, 10, 4)
    days = iter([day_a, day_a, day_a, day_b])
    monkeypatch.setattr(journal, "_today", lambda tz=journal.PARIS: next(days))

    handler = journal.JournalHandler(tmp_path / "logs", "run[1]", retention_days=2)
    try:
        handler.emit(_record("premier jour a"))
        handler.emit(_record("premier jour b"))
        handler.emit(_record("nouveau jour"))
    finally:
        handler.close()

    file_a = (tmp_path / "logs" / f"journal-{day_a.isoformat()}.log").read_text(encoding="utf-8")
    file_b = (tmp_path / "logs" / f"journal-{day_b.isoformat()}.log").read_text(encoding="utf-8")
    assert "premier jour a" in file_a and "premier jour b" in file_a and "nouveau jour" not in file_a
    assert "nouveau jour" in file_b and "premier jour" not in file_b


def test_handler_purges_on_open_and_on_each_rollover(tmp_path, monkeypatch):
    dir_ = tmp_path / "logs"
    dir_.mkdir()
    calls: list[date] = []
    real_purge = journal.purge

    def spy(dir_arg, retention_days, *, today=None):
        calls.append(today)
        return real_purge(dir_arg, retention_days, today=today)

    monkeypatch.setattr(journal, "purge", spy)
    day_a, day_b = date(2026, 10, 3), date(2026, 10, 4)
    days = iter([day_a, day_a, day_b])
    monkeypatch.setattr(journal, "_today", lambda tz=journal.PARIS: next(days))

    handler = journal.JournalHandler(dir_, "run[1]", retention_days=2)
    try:
        handler.emit(_record("meme jour, pas de nouvel appel a purge"))
        handler.emit(_record("jour suivant, rollover, purge de nouveau"))
    finally:
        handler.close()

    assert calls == [day_a, day_b]


def test_purge_removes_files_older_than_retention_days_keeps_the_rest(tmp_path):
    dir_ = tmp_path / "logs"
    dir_.mkdir()
    today = date(2026, 10, 10)
    for name in ("journal-2026-10-10.log", "journal-2026-10-09.log",
                 "journal-2026-10-08.log", "journal-2026-10-07.log"):
        (dir_ / name).write_text("x", encoding="utf-8")
    (dir_ / "pas-un-journal.log").write_text("y", encoding="utf-8")

    removed = journal.purge(dir_, retention_days=2, today=today)

    kept = {p.name for p in dir_.iterdir()}
    assert kept == {"journal-2026-10-10.log", "journal-2026-10-09.log",
                     "journal-2026-10-08.log", "pas-un-journal.log"}
    assert {p.name for p in removed} == {"journal-2026-10-07.log"}


def test_purge_does_nothing_when_the_directory_does_not_exist(tmp_path):
    assert journal.purge(tmp_path / "absent", retention_days=2) == []


def test_handler_write_failure_is_logged_once_on_stderr_and_never_raises(tmp_path, monkeypatch, capsys):
    handler = journal.JournalHandler(tmp_path / "logs", "run[1]", retention_days=2)
    monkeypatch.setattr(journal.os, "write", lambda *a, **k: (_ for _ in ()).throw(OSError("disque plein")))
    try:
        handler.emit(_record("premier essai"))
        handler.emit(_record("second essai"))
    finally:
        monkeypatch.undo()
        handler.close()

    err = capsys.readouterr().err
    assert err.count("journal : ecriture impossible") == 1
    assert "disque plein" in err


@pytest.mark.skipif(sys.platform != "win32", reason="le verrou msvcrt ne concerne que Windows")
def test_two_real_processes_appending_concurrently_lose_no_line_and_never_corrupt_one(tmp_path):
    """Deux vrais processus (pas de reseau, pas de GPU) ecrivent chacun 500
    lignes dans le meme fichier journal : la somme doit faire exactement
    1000 lignes entieres, aucune perdue ni fusionnee avec une autre."""
    script = tmp_path / "stress_journal.py"
    script.write_text(
        "import logging, sys\n"
        "from pathlib import Path\n"
        "from clipper import journal\n"
        "from clipper.config import Config\n"
        "tag, dir_, n = sys.argv[1], sys.argv[2], int(sys.argv[3])\n"
        "config = Config(mode='review', workspace_dir=Path('workspace'), output_dir=Path('output'),\n"
        "                _sections={'journal': {'dir': dir_, 'retention_days': 2}})\n"
        "journal.install(tag, config)\n"
        "logger = logging.getLogger('stress')\n"
        "for i in range(n):\n"
        "    logger.info(f'{tag}-{i}')\n"
        "logging.shutdown()\n",
        encoding="utf-8",
    )
    dir_ = tmp_path / "logs"
    n = 500
    procs = [
        subprocess.Popen([sys.executable, str(script), tag, str(dir_), str(n)])
        for tag in ("a", "b")
    ]
    for proc in procs:
        assert proc.wait(timeout=60) == 0

    today = journal._today()
    path = dir_ / f"journal-{today.isoformat()}.log"
    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2 * n
    parsed = [journal.parse_line(line + "\n") for line in lines]
    assert all(p["process"] is not None and p["process"].split("[")[0] in ("a", "b") for p in parsed)
    for tag in ("a", "b"):
        seen = {p["message"] for p in parsed if p["process"].split("[")[0] == tag}
        assert seen == {f"{tag}-{i}" for i in range(n)}


# --------------------------------------------------------------------------
# Clause 3 : purge deja couverte ci-dessus (install() purge a l'ouverture
# via JournalHandler.__init__, teste par test_handler_purges_on_open_and_on_each_rollover).
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Clause 4 : resume de corps masque (utilise par le middleware web)
# --------------------------------------------------------------------------


def test_mask_secrets_masks_password_cookie_and_token_keys_recursively():
    data = {
        "username": "bob", "password": "s3cret",
        "nested": {"api_token": "abc", "ok": 1},
        "jeton_acces": "xyz", "mot_de_passe": "azerty",
    }

    masked = journal.mask_secrets(data)

    assert masked["username"] == "bob"
    assert masked["password"] == "***"
    assert masked["nested"] == {"api_token": "***", "ok": 1}
    assert masked["jeton_acces"] == "***"
    assert masked["mot_de_passe"] == "***"


def test_mask_secrets_passes_through_lists_and_scalars():
    assert journal.mask_secrets([{"password": "x"}, "texte", 42]) == [{"password": "***"}, "texte", 42]


def test_summarize_body_masks_secrets_and_truncates(tmp_path):
    raw = json.dumps({"password": "topsecret", "note": "x" * 600}).encode("utf-8")

    summary = journal.summarize_body(raw)

    assert "topsecret" not in summary
    assert '"password": "***"' in summary
    assert len(summary) <= 501


def test_summarize_body_returns_none_for_an_empty_body():
    assert journal.summarize_body(b"") is None


def test_summarize_body_describes_a_non_json_body_by_its_size_only():
    summary = journal.summarize_body(b"ceci n'est pas du JSON")

    assert "octet" in summary
    assert "ceci" not in summary


# --------------------------------------------------------------------------
# Clause 5 : lecture pour GET /api/journal (clipper.web.app.get_journal appelle tail())
# --------------------------------------------------------------------------


def test_tail_reads_lines_across_files_in_chronological_order(tmp_path):
    dir_ = tmp_path / "logs"
    dir_.mkdir()
    (dir_ / "journal-2026-10-03.log").write_text(
        journal.format_line(_record("hier"), "run[1]"), encoding="utf-8")
    (dir_ / "journal-2026-10-04.log").write_text(
        journal.format_line(_record("aujourdhui"), "run[2]"), encoding="utf-8")
    config = _journal_config(dir_)

    result = journal.tail(config)

    assert result["available"] is True
    assert [line["message"] for line in result["lines"]] == ["hier", "aujourdhui"]


def test_tail_filters_by_text_and_by_level(tmp_path):
    dir_ = tmp_path / "logs"
    dir_.mkdir()
    content = (
        journal.format_line(_record("premier evenement", level=logging.INFO), "run[1]")
        + journal.format_line(_record("deuxieme evenement important", level=logging.WARNING), "run[1]")
    )
    today = journal._today()
    (dir_ / f"journal-{today.isoformat()}.log").write_text(content, encoding="utf-8")
    config = _journal_config(dir_)

    by_level = journal.tail(config, level="WARNING")
    by_text = journal.tail(config, text="premier")

    assert [l["message"] for l in by_level["lines"]] == ["deuxieme evenement important"]
    assert [l["message"] for l in by_text["lines"]] == ["premier evenement"]


def test_tail_caps_at_limit_keeping_the_most_recent(tmp_path):
    dir_ = tmp_path / "logs"
    dir_.mkdir()
    today = journal._today()
    content = "".join(journal.format_line(_record(f"evenement {i}"), "run[1]") for i in range(10))
    (dir_ / f"journal-{today.isoformat()}.log").write_text(content, encoding="utf-8")
    config = _journal_config(dir_)

    result = journal.tail(config, limit=3)

    assert [l["message"] for l in result["lines"]] == ["evenement 7", "evenement 8", "evenement 9"]


def test_tail_reports_unavailable_when_the_directory_does_not_exist(tmp_path):
    config = _journal_config(tmp_path / "absent")

    result = journal.tail(config)

    assert result["available"] is False
    assert result["lines"] == []
    assert result["reason"]


# --------------------------------------------------------------------------
# Clause 1 (suite) : clipper.__main__ installe le journal dans CHAQUE
# processus (serve, worker, run et sous-processus, CLI), avec le bon tag.
# --------------------------------------------------------------------------


def test_process_kind_maps_serve_and_worker_to_themselves_and_everything_else_to_run():
    from clipper.__main__ import _process_kind

    assert _process_kind("serve") == "serve"
    assert _process_kind("worker") == "worker"
    for command in ("run", "render", "decide", "status", "queue", "browser"):
        assert _process_kind(command) == "run"


@pytest.mark.parametrize(
    "argv,expected_kind",
    [(["status", "no-such-video"], "run"), (["worker"], "worker")],
)
def test_main_installs_the_journal_once_per_process_with_the_right_kind(
    monkeypatch, isolated_cwd, argv, expected_kind
):
    from clipper import __main__ as main_mod
    from clipper import worker as worker_mod

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(journal, "install", lambda kind, config: calls.append((kind, config)))
    monkeypatch.setattr(worker_mod.Worker, "loop", lambda self: None)  # 'worker' ne boucle pas vraiment

    main_mod.main(argv)

    assert len(calls) == 1
    assert calls[0][0] == expected_kind


def test_main_does_not_install_the_journal_for_init(monkeypatch, isolated_cwd):
    from clipper import __main__ as main_mod

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(journal, "install", lambda kind, config: calls.append((kind, config)))

    main_mod.main(["init"])

    assert calls == []


def test_main_keeps_the_console_handler_at_its_own_level_while_lowering_root_for_the_journal(
    monkeypatch, isolated_cwd
):
    """Sans -v (WARNING), le journal (INFO par defaut) doit tout de meme
    recevoir les evenements, sans rendre la console plus bavarde qu'avant."""
    from clipper import __main__ as main_mod

    main_mod.main(["status", "no-such-video"])

    root = logging.getLogger()
    console_handlers = [h for h in root.handlers if not isinstance(h, journal.JournalHandler)]
    assert console_handlers and all(h.level == logging.WARNING for h in console_handlers)
    assert root.level <= logging.INFO
