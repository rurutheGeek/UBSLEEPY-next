# -*- coding: utf-8 -*-
# tests/test_quiz.py
# ヒント表示、返信・ポケモン名投稿の扱い、出題条件まわりの回帰テスト。
import asyncio
import logging

import discord

import bot_module.config as cfg
import bot_module.quiz_session as session_module
import cogs.quiz as quiz_module
from bot_module.pokedex import Pokemon

QUIZ_CHANNEL_ID = cfg.QUIZ_CHANNEL_ID


def _pokemon(**overrides):
    values = dict(
        ndex_number="0006",
        form_id="00",
        species="6",
        name="リザードン",
        species_name="リザードン",
        form_name=None,
        aliases=(),
        type_1="ほのお",
        type_2="ひこう",
        ability_1="もうか",
        ability_2=None,
        ability_h="サンパワー",
        hp=78,
        atk=84,
        dfn=78,
        spa=109,
        spd=85,
        spe=100,
        region="カントー",
        evolution_stage="最終進化",
        first_title="RGB",
        generation=1,
        eng="Charizard",
        cht="噴火龍",
        display_number="6",
    )
    values.update(overrides)
    return Pokemon(**values)


class FakeUser:
    def __init__(self, user_id=1, name="tester", bot=False):
        self.id = user_id
        self.name = name
        self.bot = bot


class FakeGuild:
    def __init__(self, guild_id=None):
        # 既定は設定にあるギルド。ギルド設定の解決（既定値）を通すため。
        self.id = int(cfg.ACTIVE_GUILD_ID) if guild_id is None else guild_id


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
        return FakeMessage(author=None, channel=self)


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
    return quiz_module.QuizSession(FakeBot(), quiz_name)


def test_hint_shows_second_ability_when_all_abilities_are_shown():
    q = _quiz()
    q.rm = FakeRM()
    q.quizEmbed = discord.Embed()
    for name in ["タイプ1", "タイプ2", "特性1", "特性2", "隠れ特性"]:
        q.quizEmbed.add_field(name=name, value="x")
    q.ansText = "特性"
    q.ansZero = _pokemon(
        ability_1="しんりょく", ability_2="ようりょくそ", ability_h="くさのけがわ"
    )

    asyncio.run(q._QuizSession__hint())

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
        def __init__(self, bot, quiz_name, state=None):
            calls.append(quiz_name)

        async def try_response(self, response):
            calls.append(("try_response", response))

    monkeypatch.setattr(quiz_module, "QuizSession", FakeQuiz)

    with caplog.at_level(logging.WARNING, logger="ubsleepy"):
        asyncio.run(cog.on_message(message))

    assert calls[0] == "bq"
    assert ("try_response", message) in calls
    assert not any(
        "クイズ投稿が見つかりませんでした" in r.message for r in caplog.records
    )


class FakePokedex:
    def __init__(self, random_result=None):
        self.random_result = random_result

    def random(self, filter_dict):
        return self.random_result


def _cry_project(tmp_path, kinds):
    cry_dir = tmp_path / 'cry'
    for kind in kinds:
        (cry_dir / kind).mkdir(parents=True)
        (cry_dir / kind / '0006.ogg').write_bytes(b'ogg')
    return cry_dir


def test_cry_quiz_posts_the_cry_and_remembers_the_answer(monkeypatch, tmp_path):
    cry_dir = _cry_project(tmp_path, ('latest',))
    monkeypatch.setattr(session_module, 'CRY_DIRECTORY', cry_dir)

    class FakePokedex:
        records = [_pokemon()]

    monkeypatch.setattr(session_module, 'get_pokedex', lambda: FakePokedex())

    channel = FakeChannel()
    state = quiz_module.QuizState()
    session = quiz_module.QuizSession(FakeBot(), 'cryq', state)
    asyncio.run(session.post(channel))

    assert len(channel.sent) == 1
    _, kwargs = channel.sent[0]
    assert kwargs['file'].filename == 'cry.ogg'  # 答えが割れないファイル名
    assert state.cry_answers == {999: ('リザードン', 'latest')}


def test_cry_quiz_uses_the_old_cry_when_only_legacy_exists(monkeypatch, tmp_path):
    cry_dir = _cry_project(tmp_path, ('legacy',))
    monkeypatch.setattr(session_module, 'CRY_DIRECTORY', cry_dir)

    class FakePokedex:
        records = [_pokemon()]

    monkeypatch.setattr(session_module, 'get_pokedex', lambda: FakePokedex())

    state = quiz_module.QuizState()
    session = quiz_module.QuizSession(FakeBot(), 'cryq', state)
    asyncio.run(session.post(FakeChannel()))

    assert state.cry_answers == {999: ('リザードン', 'legacy')}


def test_cry_quiz_resolves_the_answer_from_the_state(monkeypatch):
    class FakePokedex:
        records = [_pokemon()]

    monkeypatch.setattr(session_module, 'get_pokedex', lambda: FakePokedex())

    q = _quiz('cryq')
    q.examText = 'リザードン'

    answers, aData = q._QuizSession__answers()

    assert answers == ['リザードン']
    assert aData.name == 'リザードン'


def test_bq_post_reports_no_matching_pokemon(monkeypatch):
    monkeypatch.setattr(session_module, "get_pokedex", lambda: FakePokedex())
    channel = FakeChannel()

    asyncio.run(_quiz().post(channel))

    assert len(channel.sent) == 1
    assert channel.sent[0][0] == ("現在の出題条件に合うポケモンがいません",)


def test_bqdata_removing_unset_key_does_not_raise(monkeypatch):
    cog = quiz_module.Quiz(FakeBot())
    channel = FakeChannel()
    message = FakeMessage(author=FakeUser(), content="/bqdata タイプ", channel=channel)

    cog.state.bq_filter_dict = {"進化段階": ["最終進化", "進化しない"]}
    monkeypatch.setattr(quiz_module.ub, "make_filter_dict", lambda words: {})

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
    cog.state.bq_filter_dict = {"進化段階": ["最終進化"]}
    monkeypatch.setattr(quiz_module.ub, "make_filter_dict", lambda words: {})

    asyncio.run(cog.on_message(message))

    assert cog.state.bq_filter_dict == default
    assert cog.state.bq_filter_dict is not default


def test_quiz_filter_dict_starts_as_a_copy():
    cog = quiz_module.Quiz(FakeBot())
    assert cog.state.bq_filter_dict == cfg.DEFAULT_FILTER_DICT
    assert cog.state.bq_filter_dict is not cfg.DEFAULT_FILTER_DICT


def test_quizrate_reports_save_error(monkeypatch):
    from bot_module.save import SaveError

    def fail(*args, **kwargs):
        raise SaveError("失敗")

    class FakeResponse:
        def __init__(self):
            self.messages = []

        async def send_message(self, *args, **kwargs):
            self.messages.append((args, kwargs))

        def is_done(self):
            return False

    interaction = type(
        "I",
        (),
        {
            "user": type("U", (), {"id": 1, "name": "tester"})(),
            "guild": type("G", (), {"id": 999})(),
            "response": FakeResponse(),
        },
    )()
    monkeypatch.setattr(quiz_module.ub, "report", fail)
    cog = quiz_module.Quiz(FakeBot())

    asyncio.run(cog.quizrate.callback(cog, interaction, None, "種族値クイズ"))

    assert interaction.response.messages
    assert interaction.response.messages[-1][1]["ephemeral"] is True
    assert "セーブデータ" in interaction.response.messages[-1][0][0]
