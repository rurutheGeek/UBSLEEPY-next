# -*- coding: utf-8 -*-
# config.py
"""従来のグローバル名を維持するための互換レイヤー。

値は bot_module.settings.Settings から取り出す。新しいコードは
bot_module.settings.get_settings() を使ってよい。旧コードは今までどおり
`from bot_module.config import *` で参照できる。

図鑑データは bot_module.pokedex が持つ。ここには置かない。
"""
import copy
import sys

from .settings import load_settings

####################################################################################################
# グローバル変数の宣言
DEBUG_MODE = len(sys.argv) > 1 and sys.argv[1] == "debug"
SETTINGS = load_settings(debug=DEBUG_MODE)

# config.json（document/default_config.json）から読み取る変数
DEVELOPER_USER_ID = SETTINGS.ids.developer_user_id
DEVELOPER_GUILD_ID = SETTINGS.ids.developer_guild_id
PDW_SERVER_ID = SETTINGS.ids.pdw_server_id
GUILD_IDS = SETTINGS.ids.guild_ids
# いまの起動モードで使うギルド（debug=開発用、通常=既定）
ACTIVE_GUILD_ID = SETTINGS.guild_id
# 全ギルドの設定（多サーバー対応の既定値解決に使う）
GUILD_SETTINGS = SETTINGS.guilds

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
