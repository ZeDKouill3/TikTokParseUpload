"""Collecte et mise en forme des données du visualiseur ank.

Les données viennent uniquement de la CLI (`ank ... --json`, `git`), jamais
des fichiers de .ank/ : ce module ne fait que parser leurs sorties.
"""
import json
from concurrent.futures import ThreadPoolExecutor

KINDS = ("task", "adr", "spec")


def short_id(full):
    """TASK-7aca619df8f4 -> TASK-7aca, comme l'affiche ank."""
    prefix, _, rest = full.partition("-")
    return "%s-%s" % (prefix, rest[:4]) if rest else full


def parse_corpus(text):
    return json.loads(text).get("corpus")


def parse_find(text):
    """Entités de `ank find --json ""`, sans les logs."""
    entities = []
    for row in json.loads(text)["results"]:
        if row["kind"] not in KINDS:
            continue
        state = row.get("state") or ""
        claimed_by = state.split(":", 1)[1] if state.startswith("claimed:") else None
        entities.append({
            "id": row["id"],
            "short": short_id(row["id"]),
            "kind": row["kind"],
            "status": row["status"],
            "claimed_by": claimed_by,
            "title": row["title"],
            "created": row.get("created"),
        })
    return entities


def parse_criterion(text):
    """done_criteria lu dans le frontmatter que renvoie `ank show --json`."""
    content = json.loads(text).get("content", "")
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("done_criteria:"):
            continue
        value = line[len("done_criteria:"):].strip()
        if value and value[0] not in "|>":
            return value.strip("\"'") if value[0] == value[-1] and value[0] in "\"'" else value
        block = []
        for nxt in lines[i + 1:]:
            if nxt.strip() and not nxt.startswith(" "):
                break
            block.append(nxt.strip())
        joined = "\n".join(block).strip()
        return joined.replace("\n", " ") if value.startswith(">") else joined
    return ""


def parse_edges(text):
    """Arêtes (tâche, bloquée_par) de `ank graph --json`."""
    return [(e["task"], e["blocked_by"]) for e in json.loads(text).get("edges", [])]


def parse_status(text):
    data = json.loads(text)
    claim = data.get("claim") or {}
    return {
        "branch": data.get("branch"),
        "default_branch": data.get("default_branch") or "main",
        "identity": (data.get("identity") or {}).get("value"),
        "claim": claim.get("id"),
    }


REF_FORMAT = "%(refname)%09%(objectname:short)%09%(committerdate:iso-strict)%09%(authorname)%09%(subject)"


def parse_refs(text):
    """Branches de `git for-each-ref --format=REF_FORMAT refs/heads refs/remotes`."""
    refs = []
    for line in text.splitlines():
        if not line.strip():
            continue
        ref, sha, date, author, subject = (line.split("\t", 4) + [""] * 5)[:5]
        if ref.endswith("/HEAD"):
            continue
        remote = ref.startswith("refs/remotes/")
        name = ref[len("refs/remotes/"):] if remote else ref[len("refs/heads/"):]
        refs.append({"ref": ref, "name": name, "remote": remote, "sha": sha,
                     "date": date, "author": author, "subject": subject})
    return refs


def parse_ahead_behind(text):
    """`git rev-list --left-right --count <main>...<ref>` : gauche = retard, droite = avance."""
    behind, ahead = (int(x) for x in text.split())
    return {"ahead": ahead, "behind": behind}


def group_tasks(tasks, edges):
    """en cours / prêtes / bloquées / faites / fermées ; une tâche ouverte est
    prête quand tous ses bloqueurs sont faits ou fermés."""
    status = {t["id"]: t["status"] for t in tasks}
    blockers = {}
    for t, b in edges:
        blockers.setdefault(t, []).append(b)
    groups = {"in_progress": [], "ready": [], "blocked": [], "done": [], "closed": []}
    for t in tasks:
        s = t["status"]
        if s == "open":
            finished = all(status.get(b) in ("done", "closed") for b in blockers.get(t["id"], []))
            groups["ready" if finished else "blocked"].append(t["id"])
        elif s in groups:
            groups[s].append(t["id"])
        else:
            groups["blocked"].append(t["id"])
    return groups


def _topo(ids, blockers):
    """Ordre où chaque bloqueur précède ce qu'il bloque, stable sur l'ordre donné."""
    order, emitted, pending = [], set(), list(ids)
    while pending:
        for n in pending:
            if all(b in emitted for b in blockers.get(n, ())):
                break
        else:
            n = pending[0]  # cycle : on le casse plutôt que de boucler
        pending.remove(n)
        emitted.add(n)
        order.append(n)
    return order


def layout_graph(ids, edges):
    """Place le DAG blocked_by en lanes, à la manière de `git log --graph`."""
    known = set(ids)
    blockers = {}
    for t, b in edges:
        if t in known and b in known:
            blockers.setdefault(t, []).append(b)
    order = _topo(ids, blockers)
    children = {n: [c for c in order if n in blockers.get(c, ())] for n in order}

    def free(lanes):
        for i, v in enumerate(lanes):
            if v is None:
                return i
        lanes.append(None)
        return len(lanes) - 1

    lanes, nodes, out_edges, width = [], [], [], 0
    for row, n in enumerate(order):
        slots = [i for i, v in enumerate(lanes) if v == n]
        lane = slots[0] if slots else free(lanes)
        for i in slots:
            lanes[i] = None
        nodes.append({"id": n, "row": row, "lane": lane})
        for c in children[n]:
            if c in lanes:  # déjà attendue ailleurs : on rejoint sa lane
                out_edges.append({"from": n, "to": c, "lane": lanes.index(c)})
                continue
            slot = lane if lanes[lane] is None else free(lanes)
            lanes[slot] = c
            out_edges.append({"from": n, "to": c, "lane": slot})
        width = max(width, len(lanes))
        while lanes and lanes[-1] is None:
            lanes.pop()
    return {"nodes": nodes, "edges": out_edges, "lanes": width}


def link_task(branch, tasks):
    """La tâche dont l'id (court ou complet) apparaît dans le nom de branche."""
    name = branch.lower()
    for t in tasks:
        if t["id"].lower() in name:
            return t["id"]
    for t in tasks:
        if t["short"].lower() in name:
            return t["id"]
    return None


class Collector:
    """Assemble l'état affiché par la page. `run(argv) -> stdout` est la seule
    porte vers le dépôt ; les critères sont gardés tant que le hash du corpus
    renvoyé par `ank find` ne bouge pas (chaque appel ank coûte ~2 s)."""

    def __init__(self, run, workers=8):
        self.run = run
        self.workers = workers
        self._corpus = None
        self._criteria = {}

    def _criteria_for(self, corpus, ids):
        if corpus != self._corpus:
            self._criteria = {}
            self._corpus = corpus
        missing = [i for i in ids if i not in self._criteria]
        if missing:
            with ThreadPoolExecutor(self.workers) as pool:
                texts = pool.map(lambda i: self.run(["ank", "show", i, "--json"]), missing)
                for i, text in zip(missing, texts):
                    self._criteria[i] = parse_criterion(text)
        return self._criteria

    def refresh(self):
        with ThreadPoolExecutor(3) as pool:
            find_text, graph_text, status_text = pool.map(self.run, [
                ["ank", "find", "", "--json"], ["ank", "graph", "--json"], ["ank", "status", "--json"]])
        entities = parse_find(find_text)
        edges = parse_edges(graph_text)
        status = parse_status(status_text)
        tasks = [e for e in entities if e["kind"] == "task"]
        criteria = self._criteria_for(parse_corpus(find_text), [t["id"] for t in tasks])
        for t in tasks:
            t["criterion"] = criteria.get(t["id"], "")
            t["blocked_by"] = [b for x, b in edges if x == t["id"]]

        base = status["default_branch"]
        branches = parse_refs(self.run(["git", "for-each-ref", "--format=" + REF_FORMAT,
                                        "refs/heads", "refs/remotes"]))
        for b in branches:
            try:
                b.update(parse_ahead_behind(self.run(
                    ["git", "rev-list", "--left-right", "--count", "%s...%s" % (base, b["ref"])])))
            except (ValueError, RuntimeError):
                b.update({"ahead": None, "behind": None})
            b["task"] = link_task(b["name"], tasks)

        return {
            "status": status,
            "default_branch": base,
            "tasks": tasks,
            "groups": group_tasks(tasks, edges),
            "documents": [e for e in entities if e["kind"] in ("adr", "spec")],
            "graph": layout_graph([t["id"] for t in tasks], edges),
            "branches": branches,
        }
