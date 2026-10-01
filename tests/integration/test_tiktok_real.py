"""Test reel de la publication TikTok (TASK-0b78, SPEC-9225 R9) : un vrai Chrome visible,
un vrai compte de TEST, une video publiee en PRIVE (``[tiktok] visibility = "private"``).

Saute par defaut : ``CLIPPER_TIKTOK_REAL=1`` pour le lancer, jamais en CI. Il sert aussi a
confirmer les selecteurs de ``clipper/assets/tiktok_selectors.toml`` (a verifier sur la vraie
page). Prerequis : Chrome, Playwright, un profil deja connecte a la main
(``python -m clipper browser login <compte>``).

    CLIPPER_TIKTOK_REAL=1 CLIPPER_TIKTOK_ACCOUNT=<compte> CLIPPER_TIKTOK_MP4=<clip.mp4> \\
        pytest tests/integration/test_tiktok_real.py -v -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from clipper import tiktok
from clipper.config import Config

pytestmark = pytest.mark.skipif(
    os.environ.get("CLIPPER_TIKTOK_REAL") != "1",
    reason="test reel TikTok : CLIPPER_TIKTOK_REAL=1 (compte de test, Chrome visible)",
)


def test_publish_a_private_video_on_a_test_account(tmp_path):
    account = os.environ.get("CLIPPER_TIKTOK_ACCOUNT")
    mp4 = os.environ.get("CLIPPER_TIKTOK_MP4")
    assert account and mp4 and Path(mp4).is_file(), "CLIPPER_TIKTOK_ACCOUNT et CLIPPER_TIKTOK_MP4 (un mp4 existant) sont requis"
    config = Config(mode="review", workspace_dir=tmp_path / "w", output_dir=tmp_path / "o",
                    _sections={"tiktok": {"visibility": "private"}})

    result = tiktok.publish({"video_path": Path(mp4), "caption": "Test clipper (prive)", "hashtags": ["#test"]},
                            account, mode="immediate", config=config)

    print(result)
    assert result["state"] == "published"
