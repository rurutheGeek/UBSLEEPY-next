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

    async def start_quiz(channel, quiz, mode=None, holes=None):
        started.append((quiz, mode, holes))

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


def test_q_with_a_quiz_shows_only_that_quizs_formats(monkeypatch):
    cog, started = _cog(monkeypatch)
    interaction = FakeInteraction()
    asyncio.run(cog.q.callback(cog, interaction, "種族値穴埋めクイズ"))
    content, kwargs = interaction.response.sent[0]
    assert "種族値穴埋めクイズ" in content
    assert _ids(kwargs["view"]) == [
        "qpanel:set:bhq:holes", "qpanel:set:bhq:mode", "qpanel:go:bhq:-:-"]
    assert started == []


def test_q_with_a_quiz_without_formats_posts_at_once(monkeypatch):
    cog, started = _cog(monkeypatch)
    asyncio.run(cog.q.callback(cog, FakeInteraction(), "物理特殊クイズ"))
    assert started == [("acq", None, None)]


def test_choosing_a_quiz_turns_the_panel_into_its_formats(monkeypatch):
    cog, started = _cog(monkeypatch)
    interaction = FakeInteraction(
        {"component_type": 3, "custom_id": quiz_panel.QUIZ_SELECT_ID, "values": ["noq"]},
        FakePanelMessage())
    asyncio.run(cog.on_interaction(interaction))
    edited = interaction.response.edited[0]
    assert "図鑑番号クイズ" in edited["content"]
    assert _ids(edited["view"])[-1] == "qpanel:go:noq:-:-"
    assert started == []


def test_choosing_a_quiz_without_formats_posts_and_removes_the_panel(monkeypatch):
    cog, started = _cog(monkeypatch)
    panel = FakePanelMessage()
    interaction = FakeInteraction(
        {"component_type": 3, "custom_id": quiz_panel.QUIZ_SELECT_ID, "values": ["cryq"]},
        panel)
    asyncio.run(cog.on_interaction(interaction))
    assert started == [("cryq", None, None)]
    assert panel.deleted


def test_choosing_formats_keeps_the_other_choices(monkeypatch):
    cog, started = _cog(monkeypatch)
    panel = FakePanelMessage(quiz_panel.format_view("bhq", {"holes": "3"}))
    interaction = FakeInteraction(
        {"component_type": 3, "custom_id": "qpanel:set:bhq:mode",
         "values": ["穴の位置ランダム"]},
        panel)
    asyncio.run(cog.on_interaction(interaction))
    view = interaction.response.edited[0]["view"]
    assert _ids(view)[-1] == "qpanel:go:bhq:穴の位置ランダム:3"
    # 選んだものが選ばれたまま見える
    holes_menu, mode_menu = view.children[:2]
    assert [o.value for o in holes_menu.options if o.default] == ["3"]
    assert [o.value for o in mode_menu.options if o.default] == ["穴の位置ランダム"]


def test_the_go_button_posts_with_the_choices(monkeypatch):
    cog, started = _cog(monkeypatch)
    panel = FakePanelMessage()
    interaction = FakeInteraction(
        {"component_type": 2, "custom_id": "qpanel:go:bhq:穴の位置ランダム:2"}, panel)
    asyncio.run(cog.on_interaction(interaction))
    assert started == [("bhq", "穴の位置ランダム", 2)]
    assert panel.deleted

    cog, started = _cog(monkeypatch)
    asyncio.run(cog.on_interaction(FakeInteraction(
        {"component_type": 2, "custom_id": "qpanel:go:bq:-:-"}, FakePanelMessage())))
    assert started == [("bq", None, None)]


def test_the_number_quiz_direction_comes_from_the_panel(monkeypatch):
    cog = quiz_module.Quiz(FakeBot())
    sessions = []

    class Session:
        def __init__(self, bot, quiz, state=None):
            sessions.append(self)

        async def post(self, channel, voiceChannel=None):
            pass

    monkeypatch.setattr(quiz_module, "QuizSession", Session)
    asyncio.run(cog.start_quiz(object(), "noq", "番号→ポケモン"))
    asyncio.run(cog.start_quiz(object(), "noq"))
    assert [s.fromNumber for s in sessions] == [True, False]


def test_every_panel_fits_discord_limits():
    for quiz in quiz_panel.FORMATS:
        view = quiz_panel.format_view(quiz, {})
        assert len(view.children) <= 5
        for child in view.children:
            assert len(child.custom_id) <= 100
            if isinstance(child, discord.ui.Select):
                assert all(len(o.label) <= 100 for o in child.options)
