from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.parametrize(
    "url,expected_id",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=43s", "dQw4w9WgXcQ"),
        ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=5", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_extract_video_id_from_known_url_shapes(url, expected_id):
    from clipper.download import extract_video_id

    assert extract_video_id(url) == expected_id


def test_extract_video_id_raises_for_unrecognized_url():
    from clipper.download import DownloadError, extract_video_id

    with pytest.raises(DownloadError):
        extract_video_id("https://example.com/not-youtube")


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _make_fake_ydl(info: dict, captured_opts: dict):
    """Stand-in for yt_dlp.YoutubeDL: records the opts it is built with and
    returns a pre-recorded info_dict instead of touching the network. Writes
    a dummy file at the resolved outtmpl path to simulate the download."""

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured_opts.clear()
            captured_opts.update(opts)
            self._opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def extract_info(self, url, download=True):
            if download:
                video_path = Path(self._opts["outtmpl"] % {"id": info["id"], "ext": "mp4"})
                video_path.parent.mkdir(parents=True, exist_ok=True)
                video_path.write_bytes(b"fake video bytes")
            return info

    return FakeYoutubeDL


def test_download_writes_meta_json_with_full_fields(isolated_cwd):
    from clipper.download import download

    info = _load_fixture("info_dict_full.json")
    workspace_dir = isolated_cwd / "workspace"
    captured_opts: dict = {}
    ydl_factory = _make_fake_ydl(info, captured_opts)

    meta = download(
        f"https://www.youtube.com/watch?v={info['id']}",
        workspace_dir=workspace_dir,
        ydl_factory=ydl_factory,
    )

    expected = {
        "video_id": info["id"],
        "title": info["title"],
        "description": info["description"],
        "duration": info["duration"],
        "channel": info["channel"],
        "language": info["language"],
        "chapters": info["chapters"],
        "heatmap": info["heatmap"],
        "sponsorblock_segments": info["sponsorblock_chapters"],
    }
    assert meta == expected

    meta_file = workspace_dir / info["id"] / "meta.json"
    assert json.loads(meta_file.read_text(encoding="utf-8")) == expected


def test_download_defaults_chapters_heatmap_sponsorblock_to_empty_list(isolated_cwd):
    from clipper.download import download

    info = _load_fixture("info_dict_minimal.json")
    workspace_dir = isolated_cwd / "workspace"
    captured_opts: dict = {}
    ydl_factory = _make_fake_ydl(info, captured_opts)

    meta = download(
        f"https://youtu.be/{info['id']}",
        workspace_dir=workspace_dir,
        ydl_factory=ydl_factory,
    )

    assert meta["chapters"] == []
    assert meta["heatmap"] == []
    assert meta["sponsorblock_segments"] == []
    assert meta["channel"] == info["uploader"]


def test_download_skips_when_video_and_meta_already_present(isolated_cwd):
    from clipper.download import download

    info = _load_fixture("info_dict_full.json")
    workspace_dir = isolated_cwd / "workspace"
    video_dir = workspace_dir / info["id"]
    video_dir.mkdir(parents=True)
    (video_dir / f"{info['id']}.mp4").write_bytes(b"already downloaded")
    existing_meta = {"video_id": info["id"], "title": "deja telecharge"}
    (video_dir / "meta.json").write_text(json.dumps(existing_meta), encoding="utf-8")

    def ydl_factory_that_must_not_be_called(opts):
        raise AssertionError("yt-dlp ne doit pas etre invoque : la video est deja presente")

    meta = download(
        f"https://youtu.be/{info['id']}",
        workspace_dir=workspace_dir,
        ydl_factory=ydl_factory_that_must_not_be_called,
    )

    assert meta == existing_meta


def test_download_redownloads_when_only_meta_present_without_video_file(isolated_cwd):
    from clipper.download import download

    info = _load_fixture("info_dict_full.json")
    workspace_dir = isolated_cwd / "workspace"
    video_dir = workspace_dir / info["id"]
    video_dir.mkdir(parents=True)
    (video_dir / "meta.json").write_text(json.dumps({"video_id": info["id"]}), encoding="utf-8")

    captured_opts: dict = {}
    ydl_factory = _make_fake_ydl(info, captured_opts)

    meta = download(
        f"https://youtu.be/{info['id']}",
        workspace_dir=workspace_dir,
        ydl_factory=ydl_factory,
    )

    assert meta["title"] == info["title"]
    assert captured_opts


def test_download_requests_mp4_up_to_1080p(isolated_cwd):
    from clipper.download import download

    info = _load_fixture("info_dict_full.json")
    workspace_dir = isolated_cwd / "workspace"
    captured_opts: dict = {}
    ydl_factory = _make_fake_ydl(info, captured_opts)

    download(
        f"https://youtu.be/{info['id']}",
        workspace_dir=workspace_dir,
        ydl_factory=ydl_factory,
    )

    assert captured_opts["merge_output_format"] == "mp4"
    assert "1080" in captured_opts["format"]
    assert "mp4" in captured_opts["format"]
    assert captured_opts["js_runtimes"] == {"node": {}}


def test_download_passes_configured_js_runtimes_to_ydl_opts(isolated_cwd):
    from clipper.download import download

    info = _load_fixture("info_dict_full.json")
    workspace_dir = isolated_cwd / "workspace"
    captured_opts: dict = {}
    ydl_factory = _make_fake_ydl(info, captured_opts)

    download(
        f"https://youtu.be/{info['id']}",
        workspace_dir=workspace_dir,
        js_runtimes="deno",
        ydl_factory=ydl_factory,
    )

    assert captured_opts["js_runtimes"] == {"deno": {}}


def test_download_omits_js_runtimes_when_disabled(isolated_cwd):
    from clipper.download import download

    info = _load_fixture("info_dict_full.json")
    workspace_dir = isolated_cwd / "workspace"
    captured_opts: dict = {}
    ydl_factory = _make_fake_ydl(info, captured_opts)

    download(
        f"https://youtu.be/{info['id']}",
        workspace_dir=workspace_dir,
        js_runtimes=None,
        ydl_factory=ydl_factory,
    )

    assert "js_runtimes" not in captured_opts


def test_config_defaults_declares_cookies_options():
    from clipper.download import CONFIG_DEFAULTS

    assert "cookies_file" in CONFIG_DEFAULTS
    assert "cookies_from_browser" in CONFIG_DEFAULTS


def test_config_defaults_declares_js_runtimes_option_defaulting_to_node():
    from clipper.download import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["js_runtimes"] == "node"


def test_download_passes_cookies_file_to_ydl_opts(isolated_cwd, tmp_path):
    from clipper.download import download

    info = _load_fixture("info_dict_full.json")
    workspace_dir = isolated_cwd / "workspace"
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("# netscape cookies\n", encoding="utf-8")
    captured_opts: dict = {}
    ydl_factory = _make_fake_ydl(info, captured_opts)

    download(
        f"https://youtu.be/{info['id']}",
        workspace_dir=workspace_dir,
        cookies_file=cookies_path,
        ydl_factory=ydl_factory,
    )

    assert captured_opts["cookiefile"] == str(cookies_path)


def test_download_passes_cookies_from_browser_to_ydl_opts(isolated_cwd):
    from clipper.download import download

    info = _load_fixture("info_dict_full.json")
    workspace_dir = isolated_cwd / "workspace"
    captured_opts: dict = {}
    ydl_factory = _make_fake_ydl(info, captured_opts)

    download(
        f"https://youtu.be/{info['id']}",
        workspace_dir=workspace_dir,
        cookies_from_browser="firefox",
        ydl_factory=ydl_factory,
    )

    assert captured_opts["cookiesfrombrowser"] == ("firefox",)


def test_config_section_download_resolves_via_clipper_config(isolated_cwd):
    from clipper.config import load_config

    (isolated_cwd / "config.toml").write_text(
        '[download]\ncookies_file = "cookies.txt"\n', encoding="utf-8"
    )

    config = load_config(isolated_cwd / "config.toml")

    assert config.section("download") == {
        "cookies_file": "cookies.txt",
        "cookies_from_browser": None,
        "js_runtimes": "node",
    }
