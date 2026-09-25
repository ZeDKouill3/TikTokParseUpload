"""TASK-6585 : la police configuree pour les sous-titres est livree avec sa
licence sous clipper/assets/fonts/, verifie sans reseau et sans nouvelle
dependance (parsing sfnt/name en stdlib pur)."""

from __future__ import annotations

import struct
from pathlib import Path

from clipper.subtitles import CONFIG_DEFAULTS

FONTS_DIR = Path(__file__).resolve().parent.parent / "clipper" / "assets" / "fonts"

SFNT_MAGICS = (b"\x00\x01\x00\x00", b"OTTO", b"true")


def _read_name_table(path: Path) -> dict[int, str]:
    """Renvoie {name_id: texte} depuis la table 'name' d'un fichier sfnt.

    Leve AssertionError si le fichier n'est pas un TrueType/OpenType valide
    ou n'a pas de table 'name'.
    """
    data = path.read_bytes()
    assert data[:4] in SFNT_MAGICS, f"{path} n'est pas un TrueType/OpenType valide"

    num_tables = struct.unpack(">H", data[4:6])[0]
    tables: dict[str, tuple[int, int]] = {}
    offset = 12
    for _ in range(num_tables):
        tag, _checksum, table_offset, length = struct.unpack(
            ">4sIII", data[offset : offset + 16]
        )
        tables[tag.decode("ascii")] = (table_offset, length)
        offset += 16

    assert "name" in tables, f"{path} n'a pas de table 'name'"
    name_offset, _ = tables["name"]
    _fmt, count, storage_offset = struct.unpack(
        ">HHH", data[name_offset : name_offset + 6]
    )
    storage = name_offset + storage_offset

    records: dict[int, str] = {}
    rec_offset = name_offset + 6
    for _ in range(count):
        platform_id, _enc, _lang, name_id, length, rec_off = struct.unpack(
            ">HHHHHH", data[rec_offset : rec_offset + 12]
        )
        raw = data[storage + rec_off : storage + rec_off + length]
        if platform_id in (0, 3):
            text = raw.decode("utf-16-be", errors="replace")
        else:
            text = raw.decode("latin-1", errors="replace")
        records.setdefault(name_id, text)
        rec_offset += 12

    return records


def _find_configured_font() -> tuple[Path | None, dict[int, str] | None]:
    """Le .ttf sous FONTS_DIR dont la table 'name' correspond a
    CONFIG_DEFAULTS['font_name'] (famille + sous-famille), ou (None, None)."""
    if not FONTS_DIR.is_dir():
        return None, None
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        try:
            records = _read_name_table(path)
        except (AssertionError, struct.error):
            continue
        family = records.get(16) or records.get(1) or ""
        subfamily = records.get(17) or records.get(2) or ""
        full_name = f"{family} {subfamily}".strip()
        if full_name == CONFIG_DEFAULTS["font_name"]:
            return path, records
    return None, None


def test_fonts_directory_exists():
    assert FONTS_DIR.is_dir(), f"{FONTS_DIR} est absent"


def test_font_file_present_for_configured_family():
    path, _records = _find_configured_font()
    assert path is not None, (
        f"aucun .ttf sous {FONTS_DIR} ne correspond a la police configuree "
        f"{CONFIG_DEFAULTS['font_name']!r}"
    )


def test_font_file_is_valid_truetype():
    path, records = _find_configured_font()
    assert path is not None
    assert records, f"{path} n'a pas pu etre lu comme sfnt valide"


def test_font_name_table_has_poppins_extrabold():
    _path, records = _find_configured_font()
    assert records is not None
    family = records.get(16) or records.get(1) or ""
    subfamily = records.get(17) or records.get(2) or ""
    assert "Poppins" in family, f"famille inattendue : {family!r}"
    assert "ExtraBold" in subfamily, f"sous-famille inattendue : {subfamily!r}"


def test_license_file_present_and_is_ofl():
    licence_path = FONTS_DIR / "OFL.txt"
    assert licence_path.is_file(), f"{licence_path} est absent"
    text = licence_path.read_text(encoding="utf-8", errors="replace")
    assert "SIL Open Font License" in text
