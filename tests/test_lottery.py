# -*- coding: utf-8 -*-
# tests/test_lottery.py
# IDくじのボタン処理。連打で2回引けないこと、応答を先に保留することを確認する。
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import cogs.daily as daily

JST = ZoneInfo("Asia/Tokyo")


def _today_for_lottery() -> str:
    now = datetime.now(JST)
    today = now.date()
    if now.hour < 5:
        today = today - timedelta(days=1)
    return str(today)


class FakeResponse:
    def __init__(self, calls):
        self.calls = calls

    async def defer(self, **kwargs):
        self.calls.append(("defer", kwargs))

    async def send_message(self, *args, **kwargs):
        self.calls.append(("response.send_message", args, kwargs))


class FakeFollowup:
    def __init__(self, calls):
        self.calls = calls

    async def send(self, *args, **kwargs):
        self.calls.append(("followup.send", args, kwargs))


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id
        self.name = "tester"
        self.roles = []


class FakeGuild:
    id = 999
    name = "test-guild"


class FakeInteraction:
    def __init__(self, custom_id, calls):
        self.data = {"component_type": 2, "custom_id": custom_id}
        self.user = FakeUser(123456)
        self.guild = FakeGuild()
        self.response = FakeResponse(calls)
        self.followup = FakeFollowup(calls)


def _press_lottery(monkeypatch, calls, draws):
    """メモリ上に引換券とおこづかいを持ち、ボタンを draws 回押した場合を再現する。"""
    balance = {"クジびきけん": 1, "おこづかい": 0}

    def fake_report(guild_id, user_id, index, modifi, user_name):
        calls.append(("report", index, modifi))
        balance[index] = balance.get(index, 0) + modifi
        return balance[index]

    monkeypatch.setattr(daily.ub, "report", fake_report)
    monkeypatch.setattr(
        daily.ub, "attachment_file", lambda path: ("file", "attachment://image.png")
    )
    # ランキング1位を十分大きくして、ロールの付与・剥奪まで進めない
    monkeypatch.setattr(daily.ub, "top_value", lambda guild_id, key: 10**9)
    monkeypatch.setattr(
        daily.ub, "ranking", lambda guild_id, key, limit=5: [])

    cog = daily.Daily(bot=None)
    custom_id = f"lotoIdButton:12345:{_today_for_lottery()}"
    for _ in range(draws):
        asyncio.run(cog.on_interaction(FakeInteraction(custom_id, calls)))
    return balance


def test_lottery_defers_first_and_consumes_ticket_before_money(monkeypatch):
    calls = []
    balance = _press_lottery(monkeypatch, calls, draws=1)

    assert calls[0][0] == "defer"
    assert all(call[0] != "response.send_message" for call in calls)
    assert balance["クジびきけん"] == 0

    reports = [call for call in calls if call[0] == "report"]
    used = [
        i
        for i, call in enumerate(reports)
        if call[1] == "クジびきけん" and call[2] == -1
    ]
    gained = [
        i
        for i, call in enumerate(reports)
        if call[1] == "おこづかい" and call[2] > 0
    ]
    assert used and gained
    assert used[0] < gained[0]


def test_lottery_second_click_is_rejected(monkeypatch):
    calls = []
    balance = _press_lottery(monkeypatch, calls, draws=2)

    assert balance["クジびきけん"] == 0
    gains = [
        call
        for call in calls
        if call[0] == "report" and call[1] == "おこづかい" and call[2] > 0
    ]
    assert len(gains) == 1

    sends = [call for call in calls if call[0] == "followup.send"]
    assert len(sends) == 2
    assert "1日1回" in sends[1][1][0]
