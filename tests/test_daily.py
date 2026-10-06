# -*- coding: utf-8 -*-
# tests/test_daily.py
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import cogs.daily as daily

JST = ZoneInfo("Asia/Tokyo")


def test_should_post_daily_before_5():
    now = datetime(2026, 10, 4, 4, 59, tzinfo=JST)
    assert daily.should_post_daily(None, now) is False
    assert daily.should_post_daily("2026/10/03", now) is False


def test_should_post_daily_when_not_posted():
    now = datetime(2026, 10, 4, 5, 0, tzinfo=JST)
    assert daily.should_post_daily(None, now) is True
    assert daily.should_post_daily("2026/10/03", now) is True


def test_should_post_daily_when_already_posted():
    now = datetime(2026, 10, 4, 6, 0, tzinfo=JST)
    assert daily.should_post_daily("2026/10/04", now) is False


def test_last_daily_date_roundtrip(monkeypatch):
    stored = {}

    def fake_get(guild_id, key):
        return stored.get((guild_id, key))

    def fake_set(guild_id, key, value):
        stored[(guild_id, key)] = value
        return True

    monkeypatch.setattr(daily.save, "get_guild_setting", fake_get)
    monkeypatch.setattr(daily.save, "set_guild_setting", fake_set)

    assert daily.read_last_daily_date(999) is None
    daily.save_last_daily_date(999, datetime(2026, 10, 4, 5, 0, tzinfo=JST))
    assert daily.read_last_daily_date(999) == "2026/10/04"
    assert daily.read_last_daily_date(111) is None

class HistoryChannel:
    def __init__(self, messages):
        self._messages = messages

    async def history(self, limit=20):
        for message in self._messages:
            yield message


class HistoryBot:
    def __init__(self, channel):
        self.guilds = [type("G", (), {"id": 999, "name": "test-guild"})()]
        self._channel = channel

    def get_channel(self, channel_id):
        return self._channel


def _bot_message(content):
    author = type("A", (), {"bot": True})()
    return type("M", (), {"author": author, "content": content})()


def test_daily_catch_up_skips_when_another_bot_posted(monkeypatch):
    today = datetime.now(JST).strftime("%Y/%m/%d")
    posted = []
    saved = []

    async def fake_post(bot, now, channel_id):
        posted.append(channel_id)

    monkeypatch.setattr(daily, "post_daily", fake_post)
    monkeypatch.setattr(daily, "save_last_daily_date",
                        lambda guild_id, day: saved.append(guild_id))
    monkeypatch.setattr(daily, "read_last_daily_date", lambda guild_id: None)
    monkeypatch.setattr(daily, "should_post_daily", lambda last, now: True)
    monkeypatch.setattr(daily.guild_settings, "setting", lambda guild_id, key: 123)

    bot = HistoryBot(HistoryChannel([_bot_message(f"日付が変わりました。 {today} (火)")]))
    cog = daily.Daily(bot=bot)
    asyncio.run(cog._post_daily_all_guilds(catch_up=True))

    assert posted == []  # もう1つのBotの投稿を見て投稿しない
    assert saved == [999]


def test_daily_does_not_double_post_when_loop_and_catch_up_overlap(monkeypatch):
    posted = []
    stored = {}

    async def fake_post(bot, now, channel_id):
        posted.append(channel_id)
        await asyncio.sleep(0.01)

    monkeypatch.setattr(daily, "post_daily", fake_post)
    monkeypatch.setattr(daily, "read_last_daily_date",
                        lambda guild_id: stored.get(guild_id))

    def fake_save(guild_id, day):
        stored[guild_id] = day.strftime("%Y/%m/%d")

    monkeypatch.setattr(daily, "save_last_daily_date", fake_save)
    monkeypatch.setattr(daily, "should_post_daily",
                        lambda last, now: last != now.strftime("%Y/%m/%d"))
    monkeypatch.setattr(daily.guild_settings, "setting", lambda guild_id, key: 123)

    cog = daily.Daily(bot=HistoryBot(HistoryChannel([])))

    async def run():
        await asyncio.gather(
            cog._post_daily_all_guilds(),
            cog._post_daily_all_guilds(catch_up=True),
        )

    asyncio.run(run())

    assert posted == [123]  # ループとキャッチアップが重なっても1回だけ


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.deferred = []

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)

    def is_done(self):
        return bool(self.deferred)


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class FakeInteraction:
    def __init__(self, custom_id="lotoIdButton:12345:2000/01/01"):
        self.data = {"component_type": 2, "custom_id": custom_id}
        self.user = type("U", (), {"id": 123456, "name": "tester"})()
        self.guild = type("G", (), {"id": 999, "name": "test-guild"})()
        self.response = FakeResponse()
        self.followup = FakeFollowup()


def _raise_save_error(*args, **kwargs):
    from bot_module.save import SaveError

    raise SaveError("失敗")


def test_lottery_reports_save_error(monkeypatch):
    now = datetime.now(JST)
    today = now.date() - timedelta(days=1) if now.hour < 5 else now.date()
    interaction = FakeInteraction(f"lotoIdButton:12345:{today}")
    monkeypatch.setattr(daily.ub, "report", _raise_save_error)

    asyncio.run(daily.Daily(bot=None).on_interaction(interaction))

    assert interaction.followup.messages
    assert "保存に失敗" in interaction.followup.messages[-1][0][0]


def test_pocketmoney_reports_save_error(monkeypatch):
    interaction = FakeInteraction()
    monkeypatch.setattr(daily.ub, "report", _raise_save_error)

    asyncio.run(daily.Daily.pocketmoney.callback(daily.Daily(bot=None), interaction))

    assert interaction.response.messages
    assert interaction.response.messages[-1][1]["ephemeral"] is True
    assert "セーブデータ" in interaction.response.messages[-1][0][0]
