# -*- coding: utf-8 -*-
# quiz_panel.py
"""/q で出す、クイズ選択と出題形式の選択パネル（メッセージの選択メニュー・ボタン）。

- /q（クイズ未指定）: クイズを選ぶメニュー。選ぶと、そのクイズの出題形式パネルに変わる
  （出題形式の無いクイズは、そのまま出題する）。
- /q でクイズを指定: そのクイズの出題形式パネル。
- 出題形式パネル: 項目ごとの選択メニューと「出題」ボタン。項目には、ほかの項目で
  特定の値を選んだときだけ出るもの（穴埋めの穴の数など）がある。

いま選んでいる値は「出題」ボタンの custom_id に持つ（Botを再起動しても古いパネルが動く）。
押されたときの処理は cogs/quiz.py の on_interaction が custom_id の接頭辞で振り分ける。

種族値を使うクイズは、みな「種族値クイズ」（bq）の出し方として選ぶ。中では出し方ごとに
別の種別（bq・bhq・bvq）で出題する（resolve）。種別は投稿のフッターに残るので、
連続出題・判定は種別ごとに動く。
"""
from dataclasses import dataclass

import discord

from bot_module.quiz_kinds.bhq import RANDOM_MODE
from bot_module.quiz_kinds.bq import MIN_MODE
from bot_module.quiz_kinds.bvq import SPEED_MODE, TOP_MODE

PREFIX = "qpanel:"
QUIZ_SELECT_ID = PREFIX + "quiz"
SET_PREFIX = PREFIX + "set:"  # qpanel:set:<識別子>:<項目>
GO_PREFIX = PREFIX + "go:"  # qpanel:go:<識別子>:<項目>=<値>;<項目>=<値>
DEFAULT = "-"  # 選択メニューの値は空にできないので、既定はこれで表す

HOLE_MODE = "穴埋め"
NUMBER_FROM_NUMBER = "番号→ポケモン"


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    choices: tuple  # (表示, 値, 説明)。先頭が既定。表示はスマホで切れないよう24字くらいまで
    when: tuple = ()  # (項目, 値)。その値を選んでいるときだけ出す


FORMATS = {
    "bq": (
        Field("mode", "出し方", (
            ("種族値クイズ：グラフであてる", DEFAULT,
             "種族値のグラフと数字を見て、ポケモンをあてる"),
            ("むしくい種族値クイズ：穴をうめる", HOLE_MODE,
             "穴のあいた種族値の穴に数字を入れて、いるポケモンの種族値にする"),
            ("一意の種族値クイズ：少ない欄であてる", MIN_MODE,
             "1匹に決まるだけの、いちばん少ない欄の種族値を見て、ポケモンをあてる"),
            ("高いとこクイズ：一番高い値をあてる", TOP_MODE,
             "ポケモンを見て、種族値のなかで一番高い値を答える"),
            ("すばやさクイズ：すばやさをあてる", SPEED_MODE,
             "ポケモンを見て、すばやさの種族値を答える"),
        )),
        Field("holes", "穴の数", (
            ("穴の数：1つ", "1", None), ("穴の数：2つ", "2", None), ("穴の数：3つ", "3", None),
        ), when=("mode", HOLE_MODE)),
        Field("pos", "穴の位置", (
            ("穴の位置：目立つ値は見せる", DEFAULT,
             "種族値で一番高い値・すばやさ・ほかのポケモンが持っていない値は穴にしない"),
            ("穴の位置：どこでも", "random", "どの値も穴になる"),
        ), when=("mode", HOLE_MODE)),
    ),
    "noq": (Field("mode", "出し方", (
        ("ポケモン → 番号", DEFAULT, "ポケモンの名前を見て、図鑑番号を答える"),
        ("番号 → ポケモン", NUMBER_FROM_NUMBER, "図鑑番号を見て、ポケモンを答える"),
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


def visible_fields(quiz_name, state: dict) -> list:
    """いま出す項目（ほかの項目の選び方で出たり消えたりする）。"""
    return [field for field in FORMATS[quiz_name]
            if not field.when or state.get(field.when[0], DEFAULT) == field.when[1]]


def format_view(quiz_name, state: dict) -> discord.ui.View:
    """出題形式パネル。state は {項目: 値}（無い項目は既定）。"""
    view = discord.ui.View(timeout=None)
    for field in visible_fields(quiz_name, state):
        current = state.get(field.key, DEFAULT)
        if current == DEFAULT:
            current = field.choices[0][1]
        view.add_item(discord.ui.Select(
            custom_id=f"{SET_PREFIX}{quiz_name}:{field.key}",
            placeholder=field.label,
            options=[discord.SelectOption(label=label[:100], value=value,
                                          description=description,
                                          default=value == current)
                     for label, value, description in field.choices],
        ))
    view.add_item(discord.ui.Button(
        label="出題", style=discord.ButtonStyle.primary,
        custom_id=go_id(quiz_name, state)))
    return view


def go_id(quiz_name, state) -> str:
    """「出題」ボタンの custom_id。いま出ている項目の値だけ持つ。"""
    pairs = ";".join(f"{field.key}={state.get(field.key, DEFAULT)}"
                     for field in visible_fields(quiz_name, state))
    return f"{GO_PREFIX}{quiz_name}:{pairs}"


def parse_go(custom_id):
    """「出題」ボタンの custom_id → (識別子, state)。"""
    quiz_name, _, pairs = custom_id.removeprefix(GO_PREFIX).partition(":")
    state = dict(pair.split("=", 1) for pair in pairs.split(";") if "=" in pair)
    return quiz_name, state


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


@dataclass(frozen=True)
class Start:
    """出題に使う種別と、セッションに渡す出し方。"""
    quiz_name: str
    mode: str | None = None
    holes: int | None = None
    from_number: bool = False


def resolve(quiz_name, state: dict) -> Start:
    """パネルで選んだ値から、出題する種別と出し方を決める。"""
    mode = state.get("mode", DEFAULT)
    if quiz_name == "bq":
        if mode == HOLE_MODE:
            holes = state.get("holes", DEFAULT)
            return Start("bhq",
                         RANDOM_MODE if state.get("pos") == "random" else None,
                         None if holes == DEFAULT else int(holes))
        if mode in (TOP_MODE, SPEED_MODE):
            return Start("bvq", mode)
        if mode == MIN_MODE:
            return Start("bq", MIN_MODE)
        return Start("bq")
    if quiz_name == "noq":
        return Start("noq", None if mode == DEFAULT else mode,
                     from_number=mode == NUMBER_FROM_NUMBER)
    return Start(quiz_name)
