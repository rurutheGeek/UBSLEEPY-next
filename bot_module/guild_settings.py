# -*- coding: utf-8 -*-
# guild_settings.py
"""ギルドごとの設定の解決。

優先順位は DB（/channel で保存した値）→ config.json の既定値 → 0。
config.json は「既定値＋開発用」として残す。
"""
import bot_module.config as cfg
from bot_module import config_file, save


def channel_id(guild_id, key: str) -> int:
    """ギルドの投稿先チャンネルID。未設定は0。"""
    stored = save.get_guild_setting(guild_id, key)
    if stored is not None:
        return stored
    guild = cfg.GUILD_SETTINGS.get(str(guild_id))
    if guild is None:
        return 0
    return getattr(guild, key.lower(), 0)


def set_channel(guild_id, key: str, value: int) -> str:
    """保存して保存先を返す: 'db' / 'config'（DB未設定の手元） / 'failed'。"""
    try:
        if save.set_guild_setting(guild_id, key, value):
            return 'db'
    except save.SaveError:
        return 'failed'
    if str(guild_id) not in cfg.GUILD_SETTINGS:
        # config.json に無いギルドへ書き込むと、次回起動の設定読み込みが壊れる
        return 'failed'
    config_file.update_config("config.json", guild_id, key, value)
    return 'config'
