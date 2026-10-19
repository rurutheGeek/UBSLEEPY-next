# -*- coding: utf-8 -*-
# tests/test_quiz_panel.py
# /q のクイズ選択パネルと出題形式パネル。
import asyncio

import discord

import bot_module.config as cfg
import cogs.quiz as quiz_module
from bot_module import quiz_panel


class FakeResponse:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.deferred = False

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

    async def edit_message(self, **kwargs):
        self.edited.append(kwargs)

    async def defer(self, **kwargs):
        self.deferred = True

    def is_done(self):
        return bool(self.sent or self.edited or self.deferred)


class FakePanelMessage:
    def __init__(self, view=None):
        self.deleted = False
        self.components = []
        if view is not None:
            # 送った View を、受け取ったメッセージの components の形にする
            row = type("Row", (), {"children": view.children})()
            self.components = [row]

    async def delete(self):
        self.deleted = True


class FakeInteraction:
    def __init__(self, data=None, message=None):
        self.data = data or {}
        self.message = message
        self.channel = object()
        self.response = FakeResponse()


class FakeBot:
    user = None


def _cog(monkeypatch):
    cog = quiz_module.Quiz(FakeBot())
    started = []

    async def start_quiz(channel, start):
        started.append(start)

    monkeypatch.setattr(cog, "start_quiz", start_quiz)
    return cog, started


def _ids(view):
    return [child.custom_id for child in view.children]


def test_q_without_a_quiz_shows_the_quiz_menu(monkeypatch):
    cog, started = _cog(monkeypatch)
    interaction = FakeInteraction()
    asyncio.run(cog.q.callback(cog, interaction))
    content, kwargs = interaction.response.sent[0]
    assert content == quiz_panel.QUIZ_SELECT_TEXT
    menu = kwargs["view"].children[0]
    assert menu.custom_id == quiz_panel.QUIZ_SELECT_ID
    assert {option.value for option in menu.options} == set(cfg.QUIZNAME_DICT.values())
    assert started == []


def test_the_stats_quizzes_are_one_quiz():
    # 種族値を使うクイズは、みな種族値クイズの出し方。物理特殊クイズは別
    assert "bhq" not in cfg.QUIZNAME_DICT.values()
    assert "bvq" not in cfg.QUIZNAME_DICT.values()
    assert "acq" in cfg.QUIZNAME_DICT.values()


def test_q_with_a_quiz_shows_only_that_quizs_formats(monkeypatch):
    cog, started = _cog(monkeypatch)
    interaction = FakeInteraction()
    asyncio.run(cog.q.callback(cog, interaction, "種族値クイズ"))
    content, kwargs = interaction.response.sent[0]
    assert "種族値クイズ" in content
    # 穴の数・位置は、穴埋めを選ぶまで出さない
    assert _ids(kwargs["view"]) == ["qpanel:set:bq:mode", "qpanel:go:bq:mode=-"]
    assert started == []


def test_q_with_a_quiz_without_formats_posts_at_once(monkeypatch):
    cog, started = _cog(monkeypatch)
    asyncio.run(cog.q.callback(cog, FakeInteraction(), "物理特殊クイズ"))
    assert started == [quiz_panel.Start("acq")]


def test_choosing_a_quiz_turns_the_panel_into_its_formats(monkeypatch):
    cog, started = _cog(monkeypatch)
    interaction = FakeInteraction(
        {"component_type": 3, "custom_id": quiz_panel.QUIZ_SELECT_ID, "values": ["noq"]},
        FakePanelMessage())
    asyncio.run(cog.on_interaction(interaction))
    edited = interaction.response.edited[0]
    assert "図鑑番号クイズ" in edited["content"]
    assert _ids(edited["view"])[-1] == "qpanel:go:noq:mode=-"
    assert started == []


def test_choosing_a_quiz_without_formats_posts_and_removes_the_panel(monkeypatch):
    cog, started = _cog(monkeypatch)
    panel = FakePanelMessage()
    interaction = FakeInteraction(
        {"component_type": 3, "custom_id": quiz_panel.QUIZ_SELECT_ID, "values": ["cryq"]},
        panel)
    asyncio.run(cog.on_interaction(interaction))
    assert started == [quiz_panel.Start("cryq")]
    assert panel.deleted


def _select(cog, panel_view, key, value):
    interaction = FakeInteraction(
        {"component_type": 3, "custom_id": f"qpanel:set:bq:{key}", "values": [value]},
        FakePanelMessage(panel_view))
    asyncio.run(cog.on_interaction(interaction))
    return interaction.response.edited[0]["view"]


def test_choosing_the_hole_format_shows_the_hole_choices(monkeypatch):
    cog, started = _cog(monkeypatch)
    view = _select(cog, quiz_panel.format_view("bq", {}), "mode", "穴埋め")
    assert _ids(view) == [
        "qpanel:set:bq:mode", "qpanel:set:bq:holes", "qpanel:set:bq:pos",
        "qpanel:go:bq:mode=穴埋め;holes=-;pos=-"]
    view = _select(cog, view, "holes", "3")
    view = _select(cog, view, "pos", "random")
    assert _ids(view)[-1] == "qpanel:go:bq:mode=穴埋め;holes=3;pos=random"
    # 選んだものが選ばれたまま見える
    assert [[o.value for o in menu.options if o.default] for menu in view.children[:3]] == [
        ["穴埋め"], ["3"], ["random"]]
    # ほかの出し方に戻すと、穴の項目は消える
    view = _select(cog, view, "mode", "すばやさをあてる")
    assert _ids(view) == ["qpanel:set:bq:mode", "qpanel:go:bq:mode=すばやさをあてる"]


def test_the_go_button_posts_with_the_choices(monkeypatch):
    cog, started = _cog(monkeypatch)
    panel = FakePanelMessage()
    asyncio.run(cog.on_interaction(FakeInteraction(
        {"component_type": 2, "custom_id": "qpanel:go:bq:mode=穴埋め;holes=2;pos=random"},
        panel)))
    assert started == [quiz_panel.Start("bhq", "穴の位置ランダム", 2)]
    assert panel.deleted


def test_resolve_picks_the_quiz_kind():
    resolve = quiz_panel.resolve
    assert resolve("bq", {}) == quiz_panel.Start("bq")
    assert resolve("bq", {"mode": "1匹に決まる欄だけ"}) == quiz_panel.Start("bq", "1匹に決まる欄だけ")
    assert resolve("bq", {"mode": "穴埋め", "holes": "-", "pos": "-"}) == quiz_panel.Start("bhq")
    assert resolve("bq", {"mode": "一番高い欄をあてる"}) == quiz_panel.Start("bvq", "一番高い欄をあてる")
    assert resolve("bq", {"mode": "すばやさをあてる"}) == quiz_panel.Start("bvq", "すばやさをあてる")
    assert resolve("noq", {"mode": "番号→ポケモン"}).from_number
    assert not resolve("noq", {}).from_number


def test_every_panel_fits_discord_limits():
    for quiz in quiz_panel.FORMATS:
        for mode in ("-", "穴埋め"):
            view = quiz_panel.format_view(quiz, {"mode": mode})
            assert len(view.children) <= 5
            for child in view.children:
                assert len(child.custom_id) <= 100
                if isinstance(child, discord.ui.Select):
                    assert all(len(o.label) <= 100 for o in child.options)
