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


def test_last_daily_date_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "last_daily.txt"
    monkeypatch.setattr(daily, "LAST_DAILY_PATH", str(path))

    assert daily.read_last_daily_date() is None
    daily.save_last_daily_date(datetime(2026, 10, 4, 5, 0, tzinfo=JST))
    assert daily.read_last_daily_date() == "2026/10/04"

class FakeResponse:
    def __init__(self):
        self.messages = []
        self.deferred = []

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)


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
