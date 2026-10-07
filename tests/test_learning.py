"""learning.py : rattachement post -> clip après relevé (TASK-32ae). Aucun réseau, aucun navigateur."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clipper import learning, publish, tiktok
from clipper.config import Config

ACCOUNT = "compte_a"
OTHER = "compte_b"
VIDEO = "VVVVVVVVVVV"
PUBLISH_AT = "2026-10-07T09:00:00+02:00"


def _config(tmp_path, **learning_overrides) -> Config:
    return Config(
        mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={
            "tiktok": {"stats_dir": str(tmp_path / "stats")},
            "publish": {"state_dir": str(tmp_path / "pub")},
            "learning": {"state_dir": str(tmp_path / "learning"), **learning_overrides},
        },
    )


def _sidecar(config, clip_id, *, account=ACCOUNT, post_id=None, url=None, caption="Un super clip",
             hashtags=("#jeu", "#fun"), publish_at=PUBLISH_AT, state="scheduled_on_tiktok", video=VIDEO) -> Path:
    path = Path(config.output_dir) / video / f"{clip_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "caption": caption, "hashtags": list(hashtags),
        "tiktok_post": {"url": url, "id": post_id, "state": state, "publish_at": publish_at,
                        "account": account, "note": "post programmé"},
    }), encoding="utf-8")
    return path


def _entry(config, clip_id, *, channel="chaine", post_id=None, video=VIDEO) -> Path:
    path = Path(config.section("publish")["state_dir"]) / f"{channel}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append({"video_id": video, "clip_id": clip_id, "series_id": None, "part": None, "status": "published", "slot_at": None,
                    "decided_at": None, "published_at": "2026-10-07T07:00:00+00:00", "error": None,
                    "account": ACCOUNT, "tiktok_state": "scheduled_on_tiktok", "post_id": post_id, "post_url": None})
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def _snapshot(config, fetched_at, *posts, account=ACCOUNT) -> None:
    snapshot = {"account": account, "fetched_at": fetched_at, "source": "tiktok_studio", "origin": "full",
                "overview": {}, "posts": [
                    {"post_id": pid, "post_url": f"https://www.tiktok.com/@x/video/{pid}", "caption": caption,
                     "posted_at": posted_at} for pid, caption, posted_at in posts]}
    tiktok.append_snapshot(account, tiktok.get_settings(config), snapshot)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _links(config) -> dict:
    return _read(Path(config.section("learning")["state_dir"]) / "links.json")


def test_defaults_declared():
    assert learning.CONFIG_DEFAULTS["state_dir"] == "state/learning"
    assert learning.CONFIG_DEFAULTS["enabled"] is True
    assert learning.CONFIG_DEFAULTS["link_window_h"] == 12


def test_links_scheduled_post_by_caption_and_time(tmp_path):
    config = _config(tmp_path)
    side = _sidecar(config, "clip-02")
    queue = _entry(config, "clip-02")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000001", "Un super clip #jeu #fun", "2026-10-07T09:02:00"))

    result = learning.link_posts(ACCOUNT, config=config)

    post = _read(side)["tiktok_post"]
    assert post["id"] == "7000000000000000001"
    assert post["url"] == "https://www.tiktok.com/@x/video/7000000000000000001"
    assert post["linked_by"] == "stats"
    assert datetime.fromisoformat(post["linked_at"]).tzinfo is not None
    assert post["note"] == "post programmé" and post["state"] == "scheduled_on_tiktok"
    entry = _read(queue)[0]
    assert entry["post_id"] == "7000000000000000001"
    assert entry["post_url"].endswith("/video/7000000000000000001")
    assert result["linked"] == [{"video_id": VIDEO, "clip_id": "clip-02", "post_id": "7000000000000000001"}]
    assert result["unlinked"] == {"none": 0, "ambiguous": 0}


def test_truncated_caption_with_ellipsis_still_matches(tmp_path):
    config = _config(tmp_path)
    side = _sidecar(config, "clip-01", caption="Une légende vraiment très longue pour ce clip")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000002", "Une légende vraiment très…", "2026-10-07T09:00:00"))
    learning.link_posts(ACCOUNT, config=config)
    assert _read(side)["tiktok_post"]["id"] == "7000000000000000002"


def test_no_candidate_is_recorded_with_reason_none(tmp_path):
    config = _config(tmp_path)
    side = _sidecar(config, "clip-01")
    before = side.read_text(encoding="utf-8")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000003", "Autre légende", "2026-10-07T09:00:00"))

    result = learning.link_posts(ACCOUNT, config=config)

    assert side.read_text(encoding="utf-8") == before
    assert result["unlinked"] == {"none": 1, "ambiguous": 0} and result["linked"] == []
    links = _links(config)
    [record] = links["unlinked"]
    assert {k: record[k] for k in ("video_id", "clip_id", "account", "reason", "matches")} == {
        "video_id": VIDEO, "clip_id": "clip-01", "account": ACCOUNT, "reason": "none", "matches": []}
    assert datetime.fromisoformat(record["checked_at"]).tzinfo is not None
    assert links["counts"][ACCOUNT] == {"linked": 0, "none": 1, "ambiguous": 0}


def test_post_outside_the_time_window_is_not_a_candidate(tmp_path):
    config = _config(tmp_path, link_window_h=1)
    side = _sidecar(config, "clip-01")
    before = side.read_text(encoding="utf-8")
    _snapshot(config, "2026-10-07T12:00:00+00:00", ("7000000000000000004", "Un super clip #jeu #fun", "2026-10-07T11:30:00"))
    result = learning.link_posts(ACCOUNT, config=config)
    assert side.read_text(encoding="utf-8") == before and result["unlinked"]["none"] == 1


def test_two_candidates_are_ambiguous_and_nothing_is_written(tmp_path):
    config = _config(tmp_path)
    side = _sidecar(config, "clip-01")
    queue = _entry(config, "clip-01")
    before = (side.read_text(encoding="utf-8"), queue.read_text(encoding="utf-8"))
    _snapshot(config, "2026-10-07T10:00:00+00:00",
              ("7000000000000000005", "Un super clip #jeu #fun", "2026-10-07T09:00:00"),
              ("7000000000000000006", "Un super clip #jeu #fun", "2026-10-07T09:05:00"))

    result = learning.link_posts(ACCOUNT, config=config)

    assert (side.read_text(encoding="utf-8"), queue.read_text(encoding="utf-8")) == before
    assert result["unlinked"] == {"none": 0, "ambiguous": 1}
    [record] = _links(config)["unlinked"]
    assert record["reason"] == "ambiguous"
    assert sorted(record["matches"]) == ["7000000000000000005", "7000000000000000006"]


def test_post_already_carried_by_another_sidecar_is_never_candidate(tmp_path):
    config = _config(tmp_path)
    _sidecar(config, "clip-01", post_id="7000000000000000007")
    side = _sidecar(config, "clip-02")
    before = side.read_text(encoding="utf-8")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000007", "Un super clip #jeu #fun", "2026-10-07T09:00:00"))
    result = learning.link_posts(ACCOUNT, config=config)
    assert side.read_text(encoding="utf-8") == before and result["unlinked"]["none"] == 1


def test_sidecar_with_an_id_is_never_modified(tmp_path):
    config = _config(tmp_path)
    side = _sidecar(config, "clip-01", post_id="7000000000000000008")
    before = side.read_text(encoding="utf-8")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000009", "Un super clip #jeu #fun", "2026-10-07T09:00:00"))
    result = learning.link_posts(ACCOUNT, config=config)
    assert side.read_text(encoding="utf-8") == before
    assert result == {"linked": [], "unlinked": {"none": 0, "ambiguous": 0}}


def test_other_accounts_sidecars_are_left_alone(tmp_path):
    config = _config(tmp_path)
    side = _sidecar(config, "clip-01", account=OTHER)
    before = side.read_text(encoding="utf-8")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000010", "Un super clip #jeu #fun", "2026-10-07T09:00:00"))
    learning.link_posts(ACCOUNT, config=config)
    assert side.read_text(encoding="utf-8") == before


def test_list_videos_reports_the_clip_after_linking(tmp_path):
    config = _config(tmp_path)
    _sidecar(config, "clip-02")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000011", "Un super clip #jeu #fun", "2026-10-07T09:00:00"))
    before = tiktok.list_videos(ACCOUNT, config=config)
    assert before[0]["outside_clipper"] is True
    learning.link_posts(ACCOUNT, config=config)
    [video] = tiktok.list_videos(ACCOUNT, config=config)
    assert video["clip"] == {"video_id": VIDEO, "clip_id": "clip-02"} and video["outside_clipper"] is False


def test_unreadable_sidecar_is_an_explicit_error_naming_the_file(tmp_path):
    config = _config(tmp_path)
    bad = Path(config.output_dir) / VIDEO / "casse.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{pas du json", encoding="utf-8")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000012", "x", "2026-10-07T09:00:00"))
    with pytest.raises(learning.LearningError, match="casse.json"):
        learning.link_posts(ACCOUNT, config=config)


def test_link_if_due_only_processes_accounts_with_a_newer_snapshot(tmp_path):
    config = _config(tmp_path)
    _sidecar(config, "clip-02")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000013", "Un super clip #jeu #fun", "2026-10-07T09:00:00"))
    now = datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc)

    done = learning.link_if_due(now, config=config)

    assert [(d["clip_id"], d["post_id"]) for d in done] == [("clip-02", "7000000000000000013")]
    assert _links(config)["last_run"][ACCOUNT] == now.isoformat()
    # rien de neuf depuis : aucun traitement (un nouveau sidecar non relié reste intact)
    side = _sidecar(config, "clip-03")
    before = side.read_text(encoding="utf-8")
    assert learning.link_if_due(datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc), config=config) == []
    assert side.read_text(encoding="utf-8") == before
    assert "unlinked" not in _links(config) or all(r["clip_id"] != "clip-03" for r in _links(config)["unlinked"])
    # un nouveau relevé : le compte est de nouveau traité
    _snapshot(config, "2026-10-07T11:30:00+00:00", ("7000000000000000014", "Un super clip #jeu #fun", "2026-10-07T09:10:00"))
    again = learning.link_if_due(datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc), config=config)
    assert [d["clip_id"] for d in again] == ["clip-03"]


def test_link_if_due_disabled_does_nothing(tmp_path):
    config = _config(tmp_path, enabled=False)
    side = _sidecar(config, "clip-02")
    before = side.read_text(encoding="utf-8")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000015", "Un super clip #jeu #fun", "2026-10-07T09:00:00"))
    assert learning.link_if_due(datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc), config=config) == []
    assert side.read_text(encoding="utf-8") == before


def test_a_linked_clip_leaves_the_unlinked_list(tmp_path):
    config = _config(tmp_path)
    _sidecar(config, "clip-01")
    _snapshot(config, "2026-10-07T10:00:00+00:00", ("7000000000000000016", "Autre", "2026-10-07T09:00:00"))
    learning.link_posts(ACCOUNT, config=config)
    assert len(_links(config)["unlinked"]) == 1
    _snapshot(config, "2026-10-07T11:00:00+00:00", ("7000000000000000017", "Un super clip #jeu #fun", "2026-10-07T09:00:00"))
    learning.link_posts(ACCOUNT, config=config)
    links = _links(config)
    assert links["unlinked"] == [] and links["counts"][ACCOUNT]["linked"] == 1


# ---- publish.attach_post

def test_attach_post_refuses_to_overwrite_a_different_post_id(tmp_path):
    config = _config(tmp_path)
    state = config.section("publish")["state_dir"]
    _entry(config, "clip-01", post_id="7000000000000000020")
    with pytest.raises(publish.PublishError, match="7000000000000000020"):
        publish.attach_post(VIDEO, "clip-01", "chaine", post_url="https://t/video/7000000000000000021",
                            post_id="7000000000000000021", state_dir=state)
    same = publish.attach_post(VIDEO, "clip-01", "chaine", post_url="https://t/video/7000000000000000020",
                               post_id="7000000000000000020", state_dir=state)
    assert same["post_id"] == "7000000000000000020"


def test_attach_post_unknown_entry_is_an_error(tmp_path):
    with pytest.raises(publish.PublishError, match="absent"):
        publish.attach_post(VIDEO, "nope", "chaine", post_url="u", post_id="1", state_dir=tmp_path)
