"""`ank status` peut rester bloqué plusieurs minutes (TASK-7177, mesuré
> 160 s, quasi aucun CPU consommé pendant l'attente, indépendant de la
taille du dépôt) : il doit être lu en arrière-plan, mis en cache, et ne
jamais retarder l'affichage des tâches (ADR-ad2e : jamais une info fausse
en silence, donc toujours dit explicitement en attente ou périmé)."""
import threading
import time

import ankviz
import server

STATUS_JSON = ('{"branch":"b","default_branch":"main",'
               '"identity":{"value":"w-x"},"claim":{"id":null}}')


def make_run(status_delay, status_text=STATUS_JSON):
    """find/graph/git répondent tout de suite ; `ank status` bloque `status_delay` s."""

    def run(argv):
        if argv[:2] == ["ank", "find"]:
            return '{"corpus":"c1","results":[]}'
        if argv[:2] == ["ank", "graph"]:
            return '{"edges":[]}'
        if argv[:2] == ["ank", "status"]:
            time.sleep(status_delay)
            return status_text
        if argv[:2] == ["git", "for-each-ref"]:
            return ""
        if argv[:2] == ["git", "rev-list"]:
            return "0\t0\n"
        raise AssertionError("commande inattendue: %r" % argv)

    return run


def wait_until(predicate, timeout=2.0, step=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def test_status_poller_reports_loading_while_the_first_call_is_still_running():
    poller = server.StatusPoller(make_run(status_delay=1.0), min_pause=0.05)
    threading.Thread(target=poller.loop, daemon=True).start()
    time.sleep(0.1)
    snap = poller.snapshot()
    assert snap["loading"] is True
    assert snap["collecting"] is True
    assert snap["data"] is None


def test_status_poller_publishes_once_the_call_returns():
    poller = server.StatusPoller(make_run(status_delay=0.05), min_pause=0.05)
    threading.Thread(target=poller.loop, daemon=True).start()
    assert wait_until(lambda: not poller.snapshot()["loading"])
    snap = poller.snapshot()
    assert snap["data"]["default_branch"] == "main"
    assert snap["collected_at"] is not None
    assert snap["error"] is None


def test_status_poller_reports_the_error_instead_of_hiding_it():
    def failing(argv):
        raise RuntimeError("boom")

    poller = server.StatusPoller(failing, min_pause=0.05)
    threading.Thread(target=poller.loop, daemon=True).start()
    assert wait_until(lambda: not poller.snapshot()["loading"])
    snap = poller.snapshot()
    assert snap["data"] is None
    assert "boom" in snap["error"]


def test_poller_shows_tasks_fast_even_while_status_is_still_slow():
    # Regression TASK-7177 : avant le découplage, `Collector.refresh` attendait
    # `ank status` dans le même pool que find/graph, donc la première passe
    # (censée être rapide) prenait aussi longtemps que le statut. Ici le
    # statut met 5 s ; la page doit afficher les tâches bien avant.
    run = make_run(status_delay=5.0)
    status_poller = server.StatusPoller(run, min_pause=1.0)
    poller = server.Poller(ankviz.Collector(run), interval=5.0, status_poller=status_poller)
    threading.Thread(target=status_poller.loop, daemon=True).start()
    started = time.time()
    threading.Thread(target=poller.loop, daemon=True).start()

    assert wait_until(lambda: not poller.snapshot().get("loading", True), timeout=2.0)
    elapsed = time.time() - started

    snap = poller.snapshot()
    assert elapsed < 2.0  # très inférieur aux 5 s du statut : jamais attendu dessus
    assert snap["tasks"] == []
    assert snap["status"] is None
    assert snap["status_loading"] is True
    assert snap["default_branch"] is None
    for b in snap["branches"]:
        assert b["ahead"] is None and b["behind"] is None
