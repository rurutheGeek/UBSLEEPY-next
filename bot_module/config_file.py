# -*- coding: utf-8 -*-
# config_file.py
"""config.json の書き換え（Botが投稿先チャンネルを変えるとき用）。"""
import json
import os


def update_config(path, guild_id, key, value):
    """該当ギルドの値を書き換えて、原子的に置き換える。

    書き込み中に落ちても壊れた config.json が残らないようにする。
    """
    with open(path, encoding="utf-8") as file:
        config = json.load(file)
    config["GUILD_DICT"][str(guild_id)][key] = value
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=4, ensure_ascii=False)
    os.replace(temporary, path)
