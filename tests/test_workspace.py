from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_workspace_dir_is_root_slash_video_id(isolated_cwd):
    from clipper.workspace import Workspace

    ws = Workspace("abc123", root=isolated_cwd / "workspace")

    assert ws.dir == isolated_cwd / "workspace" / "abc123"


def test_workspace_step_is_not_done_until_marked(isolated_cwd):
    from clipper.workspace import Workspace

    ws = Workspace("abc123", root=isolated_cwd / "workspace")

    assert ws.is_done("transcribe") is False

    ws.mark_done("transcribe", {"text": "hello"})

    assert ws.is_done("transcribe") is True


def test_workspace_skips_a_done_step_unless_forced(isolated_cwd):
    from clipper.workspace import Workspace

    ws = Workspace("abc123", root=isolated_cwd / "workspace")

    assert ws.should_run("transcribe") is True

    ws.mark_done("transcribe", {"text": "hello"})

    assert ws.should_run("transcribe") is False
    assert ws.should_run("transcribe", force=True) is True


def test_gitignore_excludes_workspace_and_output_dirs():
    lines = (REPO_ROOT / ".gitignore").read_text().splitlines()

    assert "workspace/" in lines
    assert "output/" in lines
