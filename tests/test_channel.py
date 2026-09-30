from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


def test_config_defaults_has_exactly_the_spec_keys_and_defaults():
    from clipper.channel import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS == {
        "display_name": "",
        "source_url": "",
        "watch": False,
        "watch_interval_s": 1800,
        "watch_min_duration_s": 600,
        "mode": "",
        "slots": [],
        "timezone": "Europe/Paris",
        "tiktok_account": "",
        "logo": "",
    }


def test_list_channels_returns_only_presets_with_channel_table_sorted_by_name(isolated_cwd):
    from clipper.channel import list_channels

    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine_b.toml").write_text('[channel]\ndisplay_name = "B"\n')
    (presets_dir / "ma_chaine_a.toml").write_text('[channel]\ndisplay_name = "A"\n')
    (presets_dir / "cli_only.toml").write_text('mode = "auto"\n')

    assert list_channels(presets_dir) == ["ma_chaine_a", "ma_chaine_b"]


def test_list_channels_refuses_invalid_channel_name(isolated_cwd):
    from clipper.channel import ChannelError, list_channels

    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "Ma-Chaine-Invalide.toml").write_text('[channel]\ndisplay_name = "X"\n')

    with pytest.raises(ChannelError, match="Ma-Chaine-Invalide"):
        list_channels(presets_dir)


def test_load_channel_returns_merged_config_and_channel_dict(isolated_cwd):
    from clipper.channel import load_channel

    (isolated_cwd / "config.toml").write_text('mode = "review"\nworkspace_dir = "ws"\n')
    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine.toml").write_text(
        '[channel]\ndisplay_name = "Ma Chaine"\nsource_url = "https://example.invalid/x"\n'
    )

    config, channel = load_channel("ma_chaine")

    assert config.workspace_dir == Path("ws")
    assert channel["display_name"] == "Ma Chaine"
    assert channel["source_url"] == "https://example.invalid/x"


def test_load_channel_defaults_display_name_to_channel_name_when_absent(isolated_cwd):
    from clipper.channel import load_channel

    (isolated_cwd / "config.toml").write_text('mode = "review"\n')
    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine.toml").write_text('[channel]\nwatch = true\n')

    _, channel = load_channel("ma_chaine")

    assert channel["display_name"] == "ma_chaine"


def test_load_channel_mode_absent_falls_back_to_global_mode(isolated_cwd):
    from clipper.channel import load_channel

    (isolated_cwd / "config.toml").write_text('mode = "auto"\n')
    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine.toml").write_text('[channel]\n')

    config, channel = load_channel("ma_chaine")

    assert config.mode == "auto"
    assert channel["mode"] == "auto"


def test_load_channel_mode_set_on_channel_overrides_global_mode(isolated_cwd):
    from clipper.channel import load_channel

    (isolated_cwd / "config.toml").write_text('mode = "review"\n')
    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine.toml").write_text('[channel]\nmode = "auto"\n')

    _, channel = load_channel("ma_chaine")

    assert channel["mode"] == "auto"


def test_load_channel_rejects_invalid_mode(isolated_cwd):
    from clipper.config import ConfigError
    from clipper.channel import load_channel

    (isolated_cwd / "config.toml").write_text('mode = "review"\n')
    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine.toml").write_text('[channel]\nmode = "bogus"\n')

    with pytest.raises(ConfigError, match="bogus"):
        load_channel("ma_chaine")


def test_load_channel_accepts_valid_slots(isolated_cwd):
    from clipper.channel import load_channel

    (isolated_cwd / "config.toml").write_text('mode = "review"\n')
    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine.toml").write_text(
        '[channel]\n[[channel.slots]]\nday = "mon"\ntime = "18:30"\n'
    )

    _, channel = load_channel("ma_chaine")

    assert channel["slots"] == [{"day": "mon", "time": "18:30"}]


def test_load_channel_rejects_slot_with_invalid_day(isolated_cwd):
    from clipper.config import ConfigError
    from clipper.channel import load_channel

    (isolated_cwd / "config.toml").write_text('mode = "review"\n')
    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine.toml").write_text(
        '[channel]\n[[channel.slots]]\nday = "someday"\ntime = "18:30"\n'
    )

    with pytest.raises(ConfigError, match="someday"):
        load_channel("ma_chaine")


def test_load_channel_rejects_slot_with_invalid_time(isolated_cwd):
    from clipper.config import ConfigError
    from clipper.channel import load_channel

    (isolated_cwd / "config.toml").write_text('mode = "review"\n')
    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine.toml").write_text(
        '[channel]\n[[channel.slots]]\nday = "mon"\ntime = "25:99"\n'
    )

    with pytest.raises(ConfigError, match="25:99"):
        load_channel("ma_chaine")


def test_save_channel_writes_toml_rereadable_by_load_channel(isolated_cwd):
    from clipper.channel import load_channel, save_channel

    (isolated_cwd / "config.toml").write_text('mode = "review"\n')
    (isolated_cwd / "presets").mkdir()

    save_channel("ma_chaine", {"channel": {"display_name": "Ma Chaine", "watch": True}})

    _, channel = load_channel("ma_chaine")
    assert channel["display_name"] == "Ma Chaine"
    assert channel["watch"] is True


def test_save_channel_leaves_existing_file_intact_on_config_error(isolated_cwd):
    from clipper.config import ConfigError
    from clipper.channel import save_channel

    (isolated_cwd / "config.toml").write_text('mode = "review"\n')
    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    original = '[channel]\ndisplay_name = "Avant"\n'
    (presets_dir / "ma_chaine.toml").write_text(original)

    with pytest.raises(ConfigError):
        save_channel("ma_chaine", {"channel": {"not_a_real_key": 1}})

    assert (presets_dir / "ma_chaine.toml").read_text() == original


def test_delete_channel_removes_the_preset_file(isolated_cwd):
    from clipper.channel import delete_channel

    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()
    (presets_dir / "ma_chaine.toml").write_text('[channel]\ndisplay_name = "X"\n')

    delete_channel("ma_chaine", presets_dir=presets_dir)

    assert not (presets_dir / "ma_chaine.toml").exists()


def test_delete_channel_refuses_unknown_name(isolated_cwd):
    from clipper.channel import ChannelError, delete_channel

    presets_dir = isolated_cwd / "presets"
    presets_dir.mkdir()

    with pytest.raises(ChannelError, match="ma_chaine"):
        delete_channel("ma_chaine", presets_dir=presets_dir)


def test_next_slots_returns_empty_list_when_no_slots():
    from clipper.channel import next_slots

    channel = {"slots": [], "timezone": "UTC"}
    after = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    assert next_slots(channel, after, 3) == []


def test_next_slots_returns_same_day_slot_when_still_ahead():
    from clipper.channel import next_slots

    channel = {"slots": [{"day": "mon", "time": "09:00"}], "timezone": "UTC"}
    after = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)  # monday, before 09:00

    result = next_slots(channel, after, 1)

    assert result == [datetime(2026, 9, 28, 9, 0, tzinfo=ZoneInfo("UTC"))]


def test_next_slots_cycles_weekly_past_the_slot_time(isolated_cwd):
    from clipper.channel import next_slots

    channel = {"slots": [{"day": "mon", "time": "09:00"}], "timezone": "UTC"}
    after = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)  # monday, after 09:00

    result = next_slots(channel, after, 3)

    assert result == [
        datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 10, 12, 9, 0, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 10, 19, 9, 0, tzinfo=ZoneInfo("UTC")),
    ]


def test_next_slots_interleaves_multiple_slots_chronologically():
    from clipper.channel import next_slots

    channel = {
        "slots": [{"day": "mon", "time": "09:00"}, {"day": "wed", "time": "09:00"}],
        "timezone": "UTC",
    }
    after = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)  # monday, after 09:00

    result = next_slots(channel, after, 2)

    assert result == [
        datetime(2026, 9, 30, 9, 0, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("UTC")),
    ]


def test_next_slots_uses_the_channel_timezone():
    from clipper.channel import next_slots

    channel = {"slots": [{"day": "mon", "time": "09:00"}], "timezone": "Europe/Paris"}
    after = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)

    result = next_slots(channel, after, 1)

    assert result == [datetime(2026, 9, 28, 9, 0, tzinfo=ZoneInfo("Europe/Paris"))]
    assert result[0].utcoffset().total_seconds() == 2 * 3600
