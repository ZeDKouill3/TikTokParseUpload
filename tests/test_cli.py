from __future__ import annotations

import subprocess
import sys


def test_cli_config_explicit_and_missing_fails_naming_the_path(isolated_cwd):
    result = subprocess.run(
        [sys.executable, "-m", "clipper", "--config", "definitely_absent_xyz.toml", "status", "somefakeid"],
        capture_output=True,
        text=True,
        cwd=isolated_cwd,
    )

    assert result.returncode == 1
    assert "definitely_absent_xyz.toml" in result.stderr
