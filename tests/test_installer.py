"""TASK-b82ee001ec52 : scripts de l'installeur portable (SPEC-38f7761891f6
R2, R3, R4, R6, R8 ; ADR-e1dac9ba2284). Tous les tests lancent
installer/install.ps1 et installer/desinstaller.ps1 avec ``--dry-run`` via
``powershell -NoProfile -ExecutionPolicy Bypass`` sur des dossiers
temporaires : aucun reseau, aucun telechargement, aucun vrai binaire ffmpeg
ni modele. Le decodeur GPU est exerce avec un ``nvidia-smi`` simule (script
place en tete du PATH), jamais le vrai.

``--dry-run`` traverse le meme code de decision que l'installation reelle
(une fonction par etape qui recoit ``-DryRun``) : ces tests prouvent donc le
plan affiche, pas une implementation separee."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SRC = REPO_ROOT / "installer"

POWERSHELL = shutil.which("powershell")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="powershell absent du PATH")

NEW_VERSION = "2.0.0"
OLDER_VERSION = "1.0.0"
NEWER_VERSION = "3.0.0"


# --------------------------------------------------------------------------
# Fixtures (locales a ce fichier, jamais dans tests/conftest.py)
# --------------------------------------------------------------------------


@pytest.fixture
def installer_dir(tmp_path: Path) -> Path:
    """Copie installer/** dans un dossier temporaire avec un version.txt a
    cote (meme disposition que le zip, SPEC-38f7 R1), sans jamais toucher au
    depot."""
    dest = tmp_path / "installer"
    dest.mkdir()
    for name in (
        "install.ps1",
        "desinstaller.ps1",
        "Clipper.bat.template",
        "PREMIER-CLIP.txt",
        "Installer.bat",
        "Desinstaller.bat",
    ):
        shutil.copy(INSTALLER_SRC / name, dest / name)
    (tmp_path / "version.txt").write_text(NEW_VERSION, encoding="utf-8")
    return tmp_path


@pytest.fixture
def zip_layout_dir(tmp_path: Path) -> Path:
    """Disposition exacte du zip (SPEC-38f7761891f6 R1) : Installer.bat et
    Desinstaller.bat a la racine, le reste sous installer/ ; contrairement a
    ``installer_dir`` ci-dessus (tout a plat dans un seul dossier), c'est la
    seule disposition qui exerce le chemin relatif que les .bat calculent
    reellement a l'execution (``%~dp0``)."""
    root = tmp_path / f"Clipper-portable-{NEW_VERSION}"
    sub = root / "installer"
    sub.mkdir(parents=True)
    for name in ("Installer.bat", "Desinstaller.bat"):
        shutil.copy(INSTALLER_SRC / name, root / name)
    for name in ("install.ps1", "desinstaller.ps1", "Clipper.bat.template", "PREMIER-CLIP.txt"):
        shutil.copy(INSTALLER_SRC / name, sub / name)
    (root / "version.txt").write_text(NEW_VERSION, encoding="utf-8")
    return root


@pytest.fixture
def fake_nvidia_smi(tmp_path: Path) -> Path:
    """Dossier contenant un nvidia-smi.bat simule (sortie non vide, code 0),
    a placer en tete du PATH : jamais le vrai nvidia-smi."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    script = bin_dir / "nvidia-smi.bat"
    script.write_text("@echo off\r\necho GPU 0: Fake NVIDIA GPU, 8192 MiB\r\n", encoding="utf-8")
    return bin_dir


@pytest.fixture
def listening_port():
    """Ouvre un vrai socket local sur 127.0.0.1 (port ephemere choisi par
    l'OS, jamais 8000 en dur : des tests xdist paralleles ou un vrai
    ``clipper serve`` deja lance sur la machine ne doivent jamais se
    percuter) pour simuler une console Clipper en cours d'execution."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        yield port
    finally:
        sock.close()


def _free_port() -> int:
    """Un port ephemere probablement libre (l'OS l'attribue puis on
    referme tout de suite) : evite de dependre du port 8000 reel, qui peut
    deja etre occupe sur la machine par une vraie console Clipper."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _env_with_prepended_path(extra_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = str(extra_dir) + os.pathsep + env.get("PATH", "")
    return env


def _env_without_command(name: str) -> dict[str, str]:
    """Environnement sans aucun repertoire du PATH contenant ``name``
    (jamais le vrai nvidia-smi dans le test « sans GPU »)."""
    env = dict(os.environ)
    found = shutil.which(name)
    if found:
        found_dir = os.path.normcase(os.path.normpath(str(Path(found).parent)))
        parts = [
            part
            for part in env.get("PATH", "").split(os.pathsep)
            if os.path.normcase(os.path.normpath(part or ".")) != found_dir
        ]
        env["PATH"] = os.pathsep.join(parts)
    return env


def run_install(root: Path, args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    install_ps1 = root / "installer" / "install.ps1"
    cmd = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(install_ps1), *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)


def run_desinstaller(
    root: Path, args: list[str], env: dict[str, str] | None = None, port: int | None = None
) -> subprocess.CompletedProcess:
    desinstaller_ps1 = root / "installer" / "desinstaller.ps1"
    cmd = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(desinstaller_ps1)]
    if port is not None:
        cmd += ["-Port", str(port)]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)


def run_bat(bat_path: Path, args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    cmd = ["cmd", "/c", str(bat_path), *args]
    return subprocess.run(cmd, cwd=str(bat_path.parent), capture_output=True, text=True, env=env, timeout=120)


def _dir_snapshot(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {str(p.relative_to(path)) for p in path.rglob("*")}


# --------------------------------------------------------------------------
# (1) les fichiers existent, et install.ps1 / desinstaller.ps1 sont du
# PowerShell 5.1 (jamais &&, ??, ni operateur ternaire).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Installer.bat",
        "install.ps1",
        "Desinstaller.bat",
        "desinstaller.ps1",
        "Clipper.bat.template",
        "PREMIER-CLIP.txt",
    ],
)
def test_installer_files_exist(name: str) -> None:
    assert (INSTALLER_SRC / name).is_file()


def _strip_powershell_comments(text: str) -> str:
    """Retire les blocs ``<# ... #>`` et les commentaires ``# ...`` avant de
    chercher une syntaxe PowerShell 7 : la prose des scripts decrit cette
    meme contrainte (« pas de &&, ni ?? ») et declencherait un faux positif
    si on la scannait telle quelle."""
    without_blocks = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    lines = [line.split("#", 1)[0] for line in without_blocks.splitlines()]
    return "\n".join(lines)


@pytest.mark.parametrize("name", ["install.ps1", "desinstaller.ps1"])
def test_scripts_avoid_powershell7_only_syntax(name: str) -> None:
    code = _strip_powershell_comments((INSTALLER_SRC / name).read_text(encoding="utf-8"))
    assert "&&" not in code
    assert "??" not in code


# --------------------------------------------------------------------------
# (2) --dry-run n'ecrit rien, ne telecharge rien ; les 11 etapes s'affichent
# dans l'ordre.
# --------------------------------------------------------------------------


def test_dry_run_writes_nothing(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    before = _dir_snapshot(installer_dir)

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert not app_dir.exists()
    assert not data_dir.exists()
    assert _dir_snapshot(installer_dir) == before


def test_dry_run_shows_eleven_steps_in_order(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    positions = [result.stdout.find(f"[{n}/11]") for n in range(1, 12)]
    assert all(p != -1 for p in positions), result.stdout
    assert positions == sorted(positions)


def test_dry_run_shows_resolved_paths(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert str(app_dir) in result.stdout
    assert str(data_dir) in result.stdout


# --------------------------------------------------------------------------
# (6) options incompatibles : message explicite, code non nul.
# --------------------------------------------------------------------------


def test_installer_bat_wrapper_finds_install_ps1_under_installer_subdir(zip_layout_dir: Path) -> None:
    app_dir = zip_layout_dir / "app"
    data_dir = zip_layout_dir / "data"

    result = run_bat(
        zip_layout_dir / "Installer.bat",
        ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "n'existe pas" not in result.stdout
    assert "[1/11]" in result.stdout


def test_desinstaller_bat_wrapper_finds_desinstaller_ps1_under_installer_subdir(zip_layout_dir: Path) -> None:
    app_dir = zip_layout_dir / "app"
    app_dir.mkdir()

    result = run_bat(zip_layout_dir / "Desinstaller.bat", ["--app", str(app_dir), "--dry-run"])

    # Pas d'assertion sur returncode/stdout complet : Desinstaller.bat ne
    # transmet jamais -Port (toujours le vrai port 8000, par conception,
    # desinstaller.ps1), donc le resultat depend de ce qui tourne reellement
    # sur la machine. Seul le branchement .bat -> installer/desinstaller.ps1
    # est en jeu ici : si le chemin etait faux, PowerShell echouerait avant
    # meme d'atteindre une ligne ecrite par le script.
    combined = result.stdout + result.stderr
    assert "n'existe pas" not in combined
    assert "desinstaller.ps1" not in combined.lower() or "parametre -file" not in combined.lower()


def test_cpu_and_cuda_together_is_rejected(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"

    result = run_install(
        installer_dir,
        ["--app", str(app_dir), "--data", str(data_dir), "--cpu", "--cuda", "--dry-run"],
    )

    assert result.returncode != 0
    assert "incompatible" in result.stdout.lower()
    assert not app_dir.exists()


# --------------------------------------------------------------------------
# (3) decision CPU / CUDA.
# --------------------------------------------------------------------------


def test_gpu_decision_without_nvidia_smi_is_cpu(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    env = _env_without_command("nvidia-smi")

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"], env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CPU" in result.stdout
    assert "[cuda]" not in result.stdout


def test_gpu_decision_with_simulated_nvidia_smi_is_cuda(installer_dir: Path, fake_nvidia_smi: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    env = _env_with_prepended_path(fake_nvidia_smi)

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"], env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[cuda]" in result.stdout


def test_cpu_flag_overrides_simulated_nvidia_smi(installer_dir: Path, fake_nvidia_smi: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    env = _env_with_prepended_path(fake_nvidia_smi)

    result = run_install(
        installer_dir,
        ["--app", str(app_dir), "--data", str(data_dir), "--cpu", "--dry-run"],
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[cuda]" not in result.stdout
    assert "CPU" in result.stdout


# --------------------------------------------------------------------------
# (3) premiere installation / mise a jour / refus de retrogradation.
# --------------------------------------------------------------------------


def test_fresh_app_is_first_install(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "premiere installation" in result.stdout


def test_older_installed_version_is_an_update_with_venv_removal(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    app_dir.mkdir()
    (app_dir / "version.txt").write_text(OLDER_VERSION, encoding="utf-8")

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "mise a jour" in result.stdout
    assert ".venv" in result.stdout
    assert "supprime" in result.stdout


def test_equal_installed_version_is_an_update(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    app_dir.mkdir()
    (app_dir / "version.txt").write_text(NEW_VERSION, encoding="utf-8")

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "mise a jour" in result.stdout


def test_newer_installed_version_refuses_downgrade(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    app_dir.mkdir()
    (app_dir / "version.txt").write_text(NEWER_VERSION, encoding="utf-8")
    before = _dir_snapshot(app_dir)

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode != 0
    assert "plus ancienne" in result.stdout.lower() or "retrograd" in result.stdout.lower()
    assert _dir_snapshot(app_dir) == before


# --------------------------------------------------------------------------
# (3) data existant avec config.toml : aucune ligne d'ecriture sous data
# sauf PREMIER-CLIP.txt, clipper init non appele.
# --------------------------------------------------------------------------


def test_existing_data_with_config_skips_init(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    data_dir.mkdir()
    (data_dir / "config.toml").write_text("[pipeline]\n", encoding="utf-8")
    before = _dir_snapshot(data_dir)

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "clipper init sera execute" not in result.stdout
    assert "clipper init non appele" in result.stdout
    assert "PREMIER-CLIP.txt" in result.stdout
    assert _dir_snapshot(data_dir) == before


def test_missing_data_config_calls_init(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "clipper init sera execute" in result.stdout


# --------------------------------------------------------------------------
# (4) Clipper.bat.template rempli, affiche en --dry-run.
# --------------------------------------------------------------------------


def test_clipper_bat_preview_has_path_and_launch_logic(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    stdout = result.stdout
    assert str(app_dir) + "\\ffmpeg\\bin" in stdout
    assert str(app_dir) + "\\.venv\\Scripts" in stdout
    assert "Clipper serve" in stdout
    assert "clipper.exe" in stdout
    assert "127.0.0.1:8000" in stdout
    assert f"set DATA={data_dir}" in stdout
    assert 'cd /d "%DATA%"' in stdout


# --------------------------------------------------------------------------
# (TASK-5d378e43fda0) ffmpeg epingle sur une version figee : l'URL ne
# contient ni "latest" ni "master", et le --dry-run l'affiche telle quelle.
# --------------------------------------------------------------------------


def test_sans_raccourci_skips_desktop_shortcut_mention(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"

    result = run_install(
        installer_dir,
        ["--app", str(app_dir), "--data", str(data_dir), "--sans-raccourci", "--dry-run"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Bureau" not in result.stdout
    assert "Clipper.lnk" not in result.stdout


def test_without_sans_raccourci_mentions_desktop_shortcut(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Bureau" in result.stdout
    assert "Clipper.lnk" in result.stdout


def test_pip_install_targets_app_venv_explicitly() -> None:
    """Regression (TASK-a093c293ea3f, trouve par le vrai passage) : sans
    --python explicite, 'uv pip install' remonte les dossiers (ou lit
    VIRTUAL_ENV) pour choisir un venv, et peut tomber sur un .venv de
    developpement ambiant totalement different de celui que l'on vient de
    creer sous $App -- observe reellement (clipper installe dans le venv du
    depot, jamais dans app\\.venv)."""
    source = _strip_powershell_comments((INSTALLER_SRC / "install.ps1").read_text(encoding="utf-8"))
    match = re.search(r"&\s*uv pip install[^\r\n]*", source)
    assert match, "commande '& uv pip install' introuvable dans install.ps1"
    assert "--python" in match.group(0), match.group(0)
    assert "venvDir" in match.group(0) or "venvPython" in match.group(0)


def test_finish_step_writes_app_version_file() -> None:
    """Regression (TASK-a093c293ea3f, trouve par le vrai passage) : sans
    cette ecriture, Step1-Prepare ne voit jamais app\\version.txt et croit
    toujours etre a la premiere installation ; une relance ne supprime alors
    pas l'ancien .venv et 'uv venv' echoue -- deja observe reellement (une
    mise a jour sur un app existant plantait a chaque fois)."""
    source = _strip_powershell_comments((INSTALLER_SRC / "install.ps1").read_text(encoding="utf-8"))
    match = re.search(r"function Invoke-Step11-Finish\b.*?\n}\n", source, re.DOTALL)
    assert match, "Invoke-Step11-Finish introuvable dans install.ps1"
    body = match.group(0)
    assert re.search(r'Set-Content\s+-Path\s+\(Join-Path\s+\$App\s+"version\.txt"\)', body), body


def test_ffmpeg_url_is_pinned_and_shown_in_dry_run(installer_dir: Path) -> None:
    source = (INSTALLER_SRC / "install.ps1").read_text(encoding="utf-8")
    match = re.search(r'\$FFMPEG_URL\s*=\s*"([^"]+)"', source)
    assert match, "constante $FFMPEG_URL introuvable dans install.ps1"
    url = match.group(1)
    assert "latest" not in url.lower()
    assert "master" not in url.lower()

    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"

    result = run_install(installer_dir, ["--app", str(app_dir), "--data", str(data_dir), "--dry-run"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert url in result.stdout


# --------------------------------------------------------------------------
# (5) desinstaller.ps1 --dry-run.
# --------------------------------------------------------------------------


def test_desinstaller_dry_run_lists_app_and_shortcut_not_data_by_default(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    app_dir.mkdir()
    (app_dir / "install.json").write_text(
        f'{{"app": "{app_dir.as_posix()}", "data": "{data_dir.as_posix()}", "version": "{NEW_VERSION}"}}',
        encoding="utf-8",
    )

    result = run_desinstaller(installer_dir, ["--app", str(app_dir), "--dry-run"], port=_free_port())

    assert result.returncode == 0, result.stdout + result.stderr
    assert str(app_dir) in result.stdout
    assert "Clipper.lnk" in result.stdout
    assert str(data_dir) not in result.stdout
    assert app_dir.exists()


def test_desinstaller_dry_run_lists_data_with_donnees(installer_dir: Path) -> None:
    app_dir = installer_dir / "app"
    data_dir = installer_dir / "data"
    app_dir.mkdir()
    (app_dir / "install.json").write_text(
        f'{{"app": "{app_dir.as_posix()}", "data": "{data_dir.as_posix()}", "version": "{NEW_VERSION}"}}',
        encoding="utf-8",
    )

    result = run_desinstaller(
        installer_dir, ["--app", str(app_dir), "--donnees", "--dry-run"], port=_free_port()
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert data_dir.as_posix() in result.stdout


def test_desinstaller_refuses_when_console_port_listens(installer_dir: Path, listening_port: int) -> None:
    app_dir = installer_dir / "app"
    app_dir.mkdir()

    result = run_desinstaller(
        installer_dir, ["--app", str(app_dir), "--dry-run"], port=listening_port
    )

    assert result.returncode != 0
    assert str(listening_port) in result.stdout
    assert app_dir.exists()


# --------------------------------------------------------------------------
# (7) PREMIER-CLIP.txt : francais, dit comment faire un premier clip.
# --------------------------------------------------------------------------


def test_premier_clip_txt_is_french_and_actionable() -> None:
    text = (INSTALLER_SRC / "PREMIER-CLIP.txt").read_text(encoding="utf-8")
    assert len(text.strip()) > 0
    assert "clip" in text.lower()
    assert "console" in text.lower()
