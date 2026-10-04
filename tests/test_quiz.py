# -*- coding: utf-8 -*-
# tests/test_quiz.py
# ヒント表示、返信・ポケモン名投稿の扱い、出題条件まわりの回帰テスト。
import asyncio
import copy
import logging

import discord
import pandas as pd

import bot_module.config as cfg
import cogs.quiz as quiz_module

QUIZ_CHANNEL_ID = cfg.QUIZ_CHANNEL_ID


class FakeUser:
    def __init__(self, user_id=1, name="tester", bot=False):
        self.id = user_id
        self.name = name
        self.bot = bot


class FakeGuild:
    def __init__(self, guild_id=1):
        self.id = guild_id


class FakeChannel:
    def __init__(self, resolved=None, history=(), channel_id=1):
        self.id = channel_id
        self._resolved = resolved
        self._history = list(history)
        self.sent = []

    async def fetch_message(self, message_id):
        return self._resolved

    def history(self, limit=10):
        async def _history():
            for message in self._history:
                yield message

        return _history()

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeReference:
    def __init__(self, message_id=1):
        self.message_id = message_id
        self.resolved = None


class FakeMessage:
    def __init__(self, author, content="", channel=None, reference=None, embeds=None):
        self.author = author
        self.content = content
        self.channel = channel
        self.reference = reference
        self.embeds = embeds or []
        self.id = 999
        self.guild = FakeGuild()


class FakeBot:
    def __init__(self):
        self.user = FakeUser(user_id=10, name="ubsleepy", bot=True)


class FakeRM:
    def __init__(self):
        self.replies = []

    async def reply(self, text):
        self.replies.append(text)


def _quiz(quiz_name="bq"):
    return quiz_module.quiz(FakeBot(), quiz_name)


def test_hint_shows_second_ability_when_all_abilities_are_shown():
    q = _quiz()
    q.rm = FakeRM()
    q.quizEmbed = discord.Embed()
    for name in ["タイプ1", "タイプ2", "特性1", "特性2", "隠れ特性"]:
        q.quizEmbed.add_field(name=name, value="x")
    q.ansText = "特性"
    q.ansZero = {
        "特性1": "しんりょく",
        "特性2": "ようりょくそ",
        "隠れ特性": "くさのけがわ",
    }

    asyncio.run(q._quiz__hint())

    assert q.rm.replies == ["とくせいはしんりょく/ようりょくそ/くさのけがわです"]


def test_reply_to_bot_message_without_embeds_is_ignored(caplog):
    bot = FakeBot()
    cog = quiz_module.Quiz(bot)
    resolved = FakeMessage(author=bot.user, content="戦績")
    channel = FakeChannel(resolved=resolved)
    message = FakeMessage(
        author=FakeUser(),
        content="ありがとう",
        channel=channel,
        reference=FakeReference(),
    )

    with caplog.at_level(logging.INFO, logger="ubsleepy"):
        asyncio.run(cog.on_message(message))

    assert any("botへのリプライは無視されました" in r.message for r in caplog.records)


def test_reply_to_embed_without_footer_is_ignored(caplog):
    bot = FakeBot()
    cog = quiz_module.Quiz(bot)
    resolved = FakeMessage(
        author=bot.user, embeds=[discord.Embed(description="フッターなし")]
    )
    channel = FakeChannel(resolved=resolved)
    message = FakeMessage(
        author=FakeUser(),
        content="ありがとう",
        channel=channel,
        reference=FakeReference(),
    )

    with caplog.at_level(logging.INFO, logger="ubsleepy"):
        asyncio.run(cog.on_message(message))

    assert any("botへのリプライは無視されました" in r.message for r in caplog.records)


def _pokemon_name_message(channel, monkeypatch):
    monkeypatch.setattr(quiz_module.ub, "fetch_pokemon", lambda text: object())
    return FakeMessage(author=FakeUser(), content="ピカチュウ", channel=channel)


def test_pokemon_name_with_empty_history_warns(monkeypatch, caplog):
    cog = quiz_module.Quiz(FakeBot())
    channel = FakeChannel(history=[], channel_id=QUIZ_CHANNEL_ID)
    message = _pokemon_name_message(channel, monkeypatch)

    with caplog.at_level(logging.WARNING, logger="ubsleepy"):
        asyncio.run(cog.on_message(message))

    assert any("クイズ投稿が見つかりませんでした" in r.message for r in caplog.records)


def test_pokemon_name_without_quiz_post_warns(monkeypatch, caplog):
    cog = quiz_module.Quiz(FakeBot())
    other = FakeMessage(
        author=FakeUser(), embeds=[discord.Embed(description="別の埋め込み")]
    )
    channel = FakeChannel(history=[other], channel_id=QUIZ_CHANNEL_ID)
    message = _pokemon_name_message(channel, monkeypatch)

    with caplog.at_level(logging.WARNING, logger="ubsleepy"):
        asyncio.run(cog.on_message(message))

    assert any("クイズ投稿が見つかりませんでした" in r.message for r in caplog.records)


def test_pokemon_name_finds_unanswered_quiz(monkeypatch, caplog):
    bot = FakeBot()
    cog = quiz_module.Quiz(bot)
    quiz_embed = discord.Embed()
    quiz_embed.set_footer(text="No.26 ポケモンクイズ - bq")
    quiz_message = FakeMessage(
        author=bot.user,
        channel=FakeChannel(channel_id=QUIZ_CHANNEL_ID),
        embeds=[quiz_embed],
    )
    channel = FakeChannel(history=[quiz_message], channel_id=QUIZ_CHANNEL_ID)
    message = _pokemon_name_message(channel, monkeypatch)

    calls = []

    class FakeQuiz:
        def __init__(self, bot, quiz_name):
            calls.append(quiz_name)

        async def try_response(self, response):
            calls.append(("try_response", response))

    monkeypatch.setattr(quiz_module, "quiz", FakeQuiz)

    with caplog.at_level(logging.WARNING, logger="ubsleepy"):
        asyncio.run(cog.on_message(message))

    assert calls[0] == "bq"
    assert ("try_response", message) in calls
    assert not any(
        "クイズ投稿が見つかりませんでした" in r.message for r in caplog.records
    )


def test_shotgun_returns_none_when_no_pokemon_matches(monkeypatch):
    monkeypatch.setattr(
        quiz_module.ub, "filter_dataframe", lambda filter_dict: pd.DataFrame()
    )

    assert _quiz()._quiz__shotgun({"進化段階": ["存在しない"]}) is None


def test_bq_post_reports_no_matching_pokemon(monkeypatch):
    monkeypatch.setattr(
        quiz_module.ub, "filter_dataframe", lambda filter_dict: pd.DataFrame()
    )
    channel = FakeChannel()

    asyncio.run(_quiz().post(channel))

    assert len(channel.sent) == 1
    assert channel.sent[0][0] == ("現在の出題条件に合うポケモンがいません",)


def test_bqdata_removing_unset_key_does_not_raise(monkeypatch):
    cog = quiz_module.Quiz(FakeBot())
    channel = FakeChannel()
    message = FakeMessage(author=FakeUser(), content="/bqdata タイプ", channel=channel)

    monkeypatch.setattr(
        cfg, "BQ_FILTER_DICT", {"進化段階": ["最終進化", "進化しない"]}
    )
    monkeypatch.setattr(cfg, "BQ_FILTERED_DF", pd.DataFrame({"おなまえ": ["ピカチュウ"]}))
    monkeypatch.setattr(quiz_module.ub, "make_filter_dict", lambda words: {})
    monkeypatch.setattr(
        quiz_module.ub,
        "filter_dataframe",
        lambda filter_dict: pd.DataFrame({"おなまえ": ["ピカチュウ"]}),
    )

    asyncio.run(cog.on_message(message))

    assert channel.sent


def test_bqdata_reset_restores_defaults(monkeypatch):
    cog = quiz_module.Quiz(FakeBot())
    channel = FakeChannel()
    message = FakeMessage(
        author=FakeUser(), content="/bqdata リセット", channel=channel
    )

    default = {"出身地": ["カントー"]}
    monkeypatch.setattr(cfg, "DEFAULT_FILTER_DICT", default)
    monkeypatch.setattr(cfg, "BQ_FILTER_DICT", {"進化段階": ["最終進化"]})
    monkeypatch.setattr(cfg, "BQ_FILTERED_DF", pd.DataFrame({"おなまえ": ["ピカチュウ"]}))
    monkeypatch.setattr(quiz_module.ub, "make_filter_dict", lambda words: {})
    monkeypatch.setattr(
        quiz_module.ub,
        "filter_dataframe",
        lambda filter_dict: pd.DataFrame({"おなまえ": ["ピカチュウ"]}),
    )

    asyncio.run(cog.on_message(message))

    assert cfg.BQ_FILTER_DICT == default
    assert cfg.BQ_FILTER_DICT is not default


def test_bq_filter_dict_is_independent_from_defaults():
    cfg.load_config()
    try:
        assert cfg.BQ_FILTER_DICT == cfg.DEFAULT_FILTER_DICT
        assert cfg.BQ_FILTER_DICT is not cfg.DEFAULT_FILTER_DICT

        before = copy.deepcopy(cfg.DEFAULT_FILTER_DICT)
        cfg.BQ_FILTER_DICT.pop(next(iter(cfg.BQ_FILTER_DICT)))
        assert cfg.DEFAULT_FILTER_DICT == before
    finally:
        cfg.load_config()
