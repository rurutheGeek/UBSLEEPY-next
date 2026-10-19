# -*- coding: utf-8 -*-
# quiz_panel.py
"""/q で出す、クイズ選択と出題形式の選択パネル（メッセージの選択メニュー・ボタン）。

- /q（クイズ未指定）: クイズを選ぶメニュー。選ぶと、そのクイズの出題形式パネルに変わる
  （出題形式の無いクイズは、そのまま出題する）。
- /q でクイズを指定: そのクイズの出題形式パネル。
- 出題形式パネル: 項目ごとの選択メニューと「出題」ボタン。

いま選んでいる値は「出題」ボタンの custom_id に持つ（Botを再起動しても古いパネルが動く）。
押されたときの処理は cogs/quiz.py の on_interaction が custom_id の接頭辞で振り分ける。
"""
from dataclasses import dataclass

import discord

from bot_module.quiz_kinds.bhq import RANDOM_MODE
from bot_module.quiz_kinds.bq import MIN_MODE

PREFIX = "qpanel:"
QUIZ_SELECT_ID = PREFIX + "quiz"
SET_PREFIX = PREFIX + "set:"  # qpanel:set:<識別子>:<項目>
GO_PREFIX = PREFIX + "go:"  # qpanel:go:<識別子>:<出し方>:<穴の数>
DEFAULT = "-"  # 選択メニューの値は空にできないので、既定はこれで表す


@dataclass(frozen=True)
class Field:
    key: str  # "mode" か "holes"
    label: str
    choices: tuple  # (表示, 値)。先頭が既定


FORMATS = {
    "bq": (Field("mode", "出し方", (
        ("いつもの（グラフと種族値）", DEFAULT),
        (MIN_MODE, MIN_MODE),
    )),),
    "bhq": (
        Field("holes", "穴の数", (("穴 1つ", "1"), ("穴 2つ", "2"), ("穴 3つ", "3"))),
        Field("mode", "穴の位置", (
            ("手がかりの欄（いちばん高い欄・めずらしい値・すばやさ）は残す", DEFAULT),
            ("どこでも（ランダム）", RANDOM_MODE),
        )),
    ),
    "noq": (Field("mode", "出し方", (
        ("ポケモン → 番号", DEFAULT),
        ("番号 → ポケモン", "番号→ポケモン"),
    )),),
}


def has_formats(quiz_name) -> bool:
    return quiz_name in FORMATS


def quiz_label(quiz_names: dict, quiz_name) -> str:
    """識別子 → 表示名（QUIZNAME_DICT は 表示名 → 識別子）。"""
    return next((label for label, name in quiz_names.items() if name == quiz_name),
                quiz_name)


def quiz_select_view(quiz_names: dict) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Select(
        custom_id=QUIZ_SELECT_ID,
        placeholder="クイズを えらぶ",
        options=[discord.SelectOption(label=label, value=name)
                 for label, name in quiz_names.items()][:25],
    ))
    return view


QUIZ_SELECT_TEXT = "出すクイズを えらんでね"


def format_text(quiz_names: dict, quiz_name) -> str:
    return f"**{quiz_label(quiz_names, quiz_name)}** の出し方を えらんで、「出題」を押してね"


def format_view(quiz_name, state: dict) -> discord.ui.View:
    """出題形式パネル。state は {"mode": 値, "holes": 値}（無い項目は既定）。"""
    view = discord.ui.View(timeout=None)
    for field in FORMATS[quiz_name]:
        current = state.get(field.key, DEFAULT)
        if current == DEFAULT:
            current = field.choices[0][1]
        view.add_item(discord.ui.Select(
            custom_id=f"{SET_PREFIX}{quiz_name}:{field.key}",
            placeholder=field.label,
            options=[discord.SelectOption(label=f"{field.label}: {label}"[:100], value=value,
                                          default=value == current)
                     for label, value in field.choices],
        ))
    view.add_item(discord.ui.Button(
        label="出題", style=discord.ButtonStyle.primary,
        custom_id=go_id(quiz_name, state)))
    return view


def go_id(quiz_name, state) -> str:
    return (f"{GO_PREFIX}{quiz_name}:{state.get('mode', DEFAULT)}:"
            f"{state.get('holes', DEFAULT)}")


def parse_go(custom_id):
    """「出題」ボタンの custom_id → (識別子, state)。"""
    quiz_name, mode, holes = custom_id.removeprefix(GO_PREFIX).split(":")
    return quiz_name, {"mode": mode, "holes": holes}


def state_from_message(message, quiz_name) -> dict:
    """パネルの投稿から、いま選んでいる値を読む（「出題」ボタンの custom_id から）。"""
    for row in getattr(message, "components", None) or []:
        for child in getattr(row, "children", None) or []:
            custom_id = getattr(child, "custom_id", None) or ""
            if custom_id.startswith(GO_PREFIX):
                name, state = parse_go(custom_id)
                if name == quiz_name:
                    return state
    return {}


def session_options(state) -> tuple:
    """state → (出し方 mode, 穴の数 holes)。既定は None。"""
    mode = state.get("mode", DEFAULT)
    holes = state.get("holes", DEFAULT)
    return (None if mode == DEFAULT else mode,
            None if holes == DEFAULT else int(holes))
