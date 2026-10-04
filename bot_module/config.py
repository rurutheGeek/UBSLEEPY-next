# -*- coding: utf-8 -*-
# config.py
"""従来のグローバル名を維持するための互換レイヤー。

値は bot_module.settings.Settings から取り出す。新しいコードは
bot_module.settings.get_settings() を使ってよい。旧コードは今までどおり
`from bot_module.config import *` で参照できる。

ここに残っているのは移行の途中経過で、Cog分割が済んだら整理する。
"""
import copy
import sys

import pandas as pd

from .settings import load_settings

####################################################################################################
# グローバル変数の宣言
DEBUG_MODE = len(sys.argv) > 1 and sys.argv[1] == "debug"
SETTINGS = load_settings(debug=DEBUG_MODE)

# 実行時の状態（設定ではない）
QUIZ_PROCESSING_FLAG = 0  # クイズ処理中フラグ
BAKUSOKU_MODE = True
GLOBAL_BRELOOM_DF = None
BQ_FILTERED_DF = None
BQ_FILTER_DICT = {}

# config.json（document/default_config.json）から読み取る変数
DEVELOPER_USER_ID = SETTINGS.ids.developer_user_id
DEVELOPER_GUILD_ID = SETTINGS.ids.developer_guild_id
PDW_SERVER_ID = SETTINGS.ids.pdw_server_id
GUILD_IDS = SETTINGS.ids.guild_ids

DEBUG_CHANNEL_ID = SETTINGS.guild.debug_channel_id
GUIDELINE_CHANNEL_ID = SETTINGS.guild.guideline_channel_id
REACTIONROLE_CHANNEL_ID = SETTINGS.guild.reactionrole_channel_id
STAGE_CHANNEL_ID = SETTINGS.guild.stage_channel_id
DAIRY_CHANNEL_ID = SETTINGS.guild.dairy_channel_id
HELLO_CHANNEL_ID = SETTINGS.guild.hello_channel_id
QUIZ_CHANNEL_ID = SETTINGS.guild.quiz_channel_id
CALLSTATUS_CHANNEL_ID = SETTINGS.guild.callstatus_channel_id
LOG_CHANNEL_ID = SETTINGS.guild.log_channel_id
UNKNOWN_ROLE_ID = SETTINGS.guild.unknown_role_id
STAGEHOST_ROLE_ID = SETTINGS.guild.stagehost_role_id
MENYMONEY_ROLE_ID = SETTINGS.guild.menymoney_role_id

BALL_ICON = SETTINGS.emoji.ball_icon
BANGBANG_ICON = SETTINGS.emoji.bangbang_icon
EXCLAMATION_ICON = SETTINGS.emoji.exclamation_icon
EX_SOURCE_LINK = SETTINGS.ex_source_link

POKEDEX_PATH = SETTINGS.paths.pokedex
NOTFOUND_IMAGE_PATH = SETTINGS.paths.notfound_image
POKECALENDAR_PATH = SETTINGS.paths.pokecalendar
POKESENRYU_PATH = SETTINGS.paths.pokesenryu
MEMBERDATA_PATH = SETTINGS.paths.memberdata
REPORT_PATH = SETTINGS.paths.report
BSS_GRAPH_PATH = SETTINGS.paths.bss_graph
MEMORY_PATH = SETTINGS.paths.memory
CALLDATA_PATH = SETTINGS.paths.calldata
FEEDBACK_PATH = SETTINGS.paths.feedback
MEMBERLIST_PATH = SETTINGS.paths.memberlist
CALLLOG_PATH = SETTINGS.paths.calllog

QUIZNAME_DICT = SETTINGS.quizname_dict
POKENAME_PREFIX_DICT = SETTINGS.pokename_prefix_dict
BASE_STATS_DICT = SETTINGS.base_stats_dict
WEAK_DICT = SETTINGS.weak_dict
TYPE_COLOR_DICT = SETTINGS.type_color_dict
PRIZE_DICT = SETTINGS.prize_dict
DEFAULT_FILTER_DICT = copy.deepcopy(SETTINGS.default_filter_dict)


def load_config():
    """図鑑データとクイズの絞り込み状態を読み直す。"""
    global GLOBAL_BRELOOM_DF, BQ_FILTERED_DF, BQ_FILTER_DICT

    # グローバルずかんデータを用意
    GLOBAL_BRELOOM_DF = pd.read_csv(POKEDEX_PATH)
    GLOBAL_BRELOOM_DF["ぜんこくずかんナンバー"] = GLOBAL_BRELOOM_DF[
        "ぜんこくずかんナンバー"
    ].apply(lambda x: str(int(x)) if x.is_integer() else str(x))
    BQ_FILTERED_DF = GLOBAL_BRELOOM_DF.copy()
    BQ_FILTER_DICT = copy.deepcopy(DEFAULT_FILTER_DICT)


# config.jsonを読み込む
load_config()