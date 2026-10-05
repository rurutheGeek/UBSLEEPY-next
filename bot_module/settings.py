# -*- coding: utf-8 -*-
# settings.py
"""型つきの設定。

config.json（無ければ document/default_config.json）を一度だけ読み、
以降は Settings オブジェクトとして参照する。globals() への展開はしない。
Discord・pandas に依存しないので、テストは設定ファイルだけで動く。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = "document/default_config.json"


class SettingsError(Exception):
    """設定ファイルの読み込み・内容に問題があるときのエラー。"""


@dataclass(frozen=True)
class GuildIds:
    developer_user_id: int
    developer_guild_id: str
    pdw_server_id: str
    guild_ids: list[int]


@dataclass(frozen=True)
class GuildSettings:
    debug_channel_id: int
    guideline_channel_id: int
    stage_channel_id: int
    dairy_channel_id: int
    hello_channel_id: int
    quiz_channel_id: int
    reactionrole_channel_id: int
    callstatus_channel_id: int
    log_channel_id: int
    unknown_role_id: int
    stagehost_role_id: int
    menymoney_role_id: int


@dataclass(frozen=True)
class EmojiSettings:
    ball_icon: str
    bangbang_icon: str
    exclamation_icon: str


@dataclass(frozen=True)
class PathSettings:
    pokedex: str
    notfound_image: str
    pokecalendar: str
    pokesenryu: str
    memberdata: str
    report: str
    bss_graph: str
    memory: str
    calldata: str
    feedback: str
    memberlist: str
    calllog: str


@dataclass(frozen=True)
class Settings:
    debug_mode: bool
    ids: GuildIds
    guild_id: str
    guild: GuildSettings
    guilds: dict[str, GuildSettings]
    emoji: EmojiSettings
    ex_source_link: str
    paths: PathSettings
    quizname_dict: dict[str, str]
    pokename_prefix_dict: dict[str, str]
    base_stats_dict: dict[str, str]
    weak_dict: dict[str, str]
    type_color_dict: dict[str, int]
    prize_dict: dict[str, dict]
    default_filter_dict: dict[str, list[str]]


def _require(section: dict, key: str, where: str):
    try:
        return section[key]
    except (KeyError, TypeError) as exc:
        raise SettingsError(f"{where} に {key!r} がありません") from exc


def load_settings(
    config_path: str | Path = "config.json",
    default_path: str | Path = DEFAULT_CONFIG_PATH,
    debug: bool = False,
) -> Settings:
    """設定ファイルを読み、Settings を組み立てる。

    config_path が無いときは default_path を使う（従来の load_config と同じ）。
    読み込んだ Settings は get_settings() で参照できるようになる。
    """
    path = Path(config_path)
    if not path.exists():
        path = Path(default_path)
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)

    develop = _require(raw, "DEVELOP_ID_DICT", str(path))
    guild_ids = list(_require(develop, "GUILD_IDS", str(path)))
    # デバッグ以外で使うサーバーは設定から読む。無ければ GUILD_IDS の最後を使う。
    default_guild_id = develop.get("DEFAULT_GUILD_ID") or (guild_ids[-1] if guild_ids else None)
    if default_guild_id is None:
        raise SettingsError(f"{path} の DEVELOP_ID_DICT に GUILD_IDS がありません")
    guild_id = str(_require(develop, "DEVELOPER_GUILD_ID", str(path)) if debug else default_guild_id)
    guild_raw = _require(raw, "GUILD_DICT", str(path))

    def build_guild(entry: dict, where: str) -> GuildSettings:
        return GuildSettings(
            debug_channel_id=_require(entry, "DEBUG_CHANNEL_ID", where),
            guideline_channel_id=_require(entry, "GUIDELINE_CHANNEL_ID", where),
            stage_channel_id=_require(entry, "STAGE_CHANNEL_ID", where),
            dairy_channel_id=_require(entry, "DAIRY_CHANNEL_ID", where),
            hello_channel_id=_require(entry, "HELLO_CHANNEL_ID", where),
            quiz_channel_id=_require(entry, "QUIZ_CHANNEL_ID", where),
            reactionrole_channel_id=_require(entry, "REACTIONROLE_CHANNEL_ID", where),
            callstatus_channel_id=_require(entry, "CALLSTATUS_CHANNEL_ID", where),
            log_channel_id=_require(entry, "LOG_CHANNEL_ID", where),
            unknown_role_id=_require(entry, "UNKNOWN_ROLE_ID", where),
            stagehost_role_id=_require(entry, "STAGEHOST_ROLE_ID", where),
            menymoney_role_id=_require(entry, "MENYMONEY_ROLE_ID", where),
        )

    guilds = {
        key: build_guild(entry, f"{path} の GUILD_DICT[{key}]")
        for key, entry in guild_raw.items()
    }
    guild = _require(guilds, guild_id, f"{path} の GUILD_DICT")
    emoji = _require(raw, "EMOJI_ID_DICT", str(path))
    links = _require(raw, "LINK_DICT", str(path))
    paths = _require(raw, "PATH_DICT", str(path))
    systems = _require(raw, "SYSTEM_DICT_DICT", str(path))

    settings = Settings(
        debug_mode=debug,
        ids=GuildIds(
            developer_user_id=_require(develop, "DEVELOPER_USER_ID", str(path)),
            developer_guild_id=str(_require(develop, "DEVELOPER_GUILD_ID", str(path))),
            pdw_server_id=str(_require(develop, "PDW_SERVER_ID", str(path))),
            guild_ids=guild_ids,
        ),
        guild_id=guild_id,
        guild=guild,
        guilds=guilds,
        emoji=EmojiSettings(
            ball_icon=_require(emoji, "BALL_ICON", str(path)),
            bangbang_icon=_require(emoji, "BANGBANG_ICON", str(path)),
            exclamation_icon=_require(emoji, "EXCLAMATION_ICON", str(path)),
        ),
        ex_source_link=_require(links, "EX_SOURCE_LINK", str(path)),
        paths=PathSettings(
            pokedex=_require(paths, "POKEDEX_PATH", str(path)),
            notfound_image=_require(paths, "NOTFOUND_IMAGE_PATH", str(path)),
            pokecalendar=_require(paths, "POKECALENDAR_PATH", str(path)),
            pokesenryu=_require(paths, "POKESENRYU_PATH", str(path)),
            memberdata=_require(paths, "MEMBERDATA_PATH", str(path)),
            report=_require(paths, "REPORT_PATH", str(path)),
            bss_graph=_require(paths, "BSS_GRAPH_PATH", str(path)),
            memory=_require(paths, "MEMORY_PATH", str(path)),
            calldata=_require(paths, "CALLDATA_PATH", str(path)),
            feedback=_require(paths, "FEEDBACK_PATH", str(path)),
            memberlist=_require(paths, "MEMBERLIST_PATH", str(path)),
            calllog=_require(paths, "CALLLOG_PATH", str(path)),
        ),
        quizname_dict=dict(_require(systems, "QUIZNAME_DICT", str(path))),
        pokename_prefix_dict=dict(_require(systems, "POKENAME_PREFIX_DICT", str(path))),
        base_stats_dict=dict(_require(systems, "BASE_STATS_DICT", str(path))),
        weak_dict=dict(_require(systems, "WEAK_DICT", str(path))),
        type_color_dict=dict(_require(systems, "TYPE_COLOR_DICT", str(path))),
        prize_dict=dict(_require(systems, "PRIZE_DICT", str(path))),
        default_filter_dict=dict(_require(systems, "DEFAULT_FILTER_DICT", str(path))),
    )
    set_settings(settings)
    return settings


_settings: Settings | None = None


def set_settings(settings: Settings) -> None:
    global _settings
    _settings = settings


def get_settings() -> Settings:
    """読み込み済みの設定を返す。読み込んでいなければ RuntimeError。"""
    if _settings is None:
        raise RuntimeError("設定が読み込まれていません。load_settings() を先に呼んでください")
    return _settings