# -*- coding: utf-8 -*-
# guild_settings.py
"""ギルドごとの設定の解決。

優先順位は DB（/channel・/role で保存した値）→ config.json の既定値 → 0。
config.json は「既定値＋開発用」として残す。
値はプロセス内でキャッシュする（設定変更時に更新。外部から直接DBを書き換えた
場合は再起動まで反映されない）。
"""
import bot_module.config as cfg
from bot_module import config_file, save

_CACHE: dict = {}


def reset_cache() -> None:
    """キャッシュを捨てる（テストや再読み込み用）。"""
    _CACHE.clear()


def setting(guild_id, key: str) -> int:
    """ギルド設定（チャンネルID・ロールIDなど）。未設定は0。"""
    cache_key = (int(guild_id), key)
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    stored = save.get_guild_setting(guild_id, key)
    if stored is not None:
        value = stored
    else:
        guild = cfg.GUILD_SETTINGS.get(str(guild_id))
        value = getattr(guild, key.lower(), 0) if guild else 0
    _CACHE[cache_key] = value
    return value


def set_setting(guild_id, key: str, value: int) -> str:
    """保存して保存先を返す: 'db' / 'config'（DB未設定の手元） / 'failed'。"""
    try:
        if save.set_guild_setting(guild_id, key, value):
            _CACHE[(int(guild_id), key)] = int(value)
            return 'db'
    except save.SaveError:
        return 'failed'
    if str(guild_id) not in cfg.GUILD_SETTINGS:
        # config.json に無いギルドへ書き込むと、次回起動の設定読み込みが壊れる
        return 'failed'
    config_file.update_config("config.json", guild_id, key, value)
    _CACHE[(int(guild_id), key)] = int(value)
    return 'config'
