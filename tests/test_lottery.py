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

    def is_done(self):
        return any(call[0] == "defer" for call in self.calls)


class FakeFollowup:
    def __init__(self, calls):
        self.calls = calls

    async def send(self, *args, **kwargs):
        self.calls.append(("followup.send", args, kwargs))


class FakeRole:
    def __init__(self, role_id=42, name="おかねもち"):
        self.id = role_id
        self.name = name


class FakeUser:
    def __init__(self, user_id, guild=None):
        self.id = user_id
        self.name = f"user{user_id}"
        self.roles = []
        self.guild = guild

    async def add_roles(self, role):
        self.roles.append(role)

    async def remove_roles(self, role):
        if role in self.roles:
            self.roles.remove(role)


class FakeGuild:
    id = 999
    name = "test-guild"

    def __init__(self):
        self.role = FakeRole()
        self.members = {}

    def get_role(self, role_id):
        return self.role

    def get_member(self, user_id):
        return self.members.get(int(user_id))


class FakeInteraction:
    def __init__(self, custom_id, calls):
        self.data = {"component_type": 2, "custom_id": custom_id}
        self.user = FakeUser(123456)
        self.guild = FakeGuild()
        self.user.guild = self.guild
        self.response = FakeResponse(calls)
        self.followup = FakeFollowup(calls)


def _press_lottery(monkeypatch, calls, draws):
    """メモリ上に引換券とおこづかいを持ち、ボタンを draws 回押した場合を再現する。"""
    balance = {"クジびきけん": 1, "おこづかい": 0}

    def fake_report(user_id, index, modifi, user_name):
        calls.append(("report", index, modifi))
        balance[index] = balance.get(index, 0) + modifi
        return balance[index]

    monkeypatch.setattr(daily.ub, "report", fake_report)
    monkeypatch.setattr(
        daily.ub, "attachment_file", lambda path: ("file", "attachment://image.png")
    )
    # ランキング1位を十分大きくして、ロールの付与・剥奪まで進めない
    monkeypatch.setattr(daily.ub, "top_value", lambda key: 10**9)
    monkeypatch.setattr(
        daily.ub, "ranking", lambda key, limit=5: [])

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


def test_lottery_removes_the_role_from_all_stale_holders(monkeypatch):
    """1位になったら、間に持っていない人がいても古い保持者全員から剥奪する。"""
    calls = []
    balance = {"クジびきけん": 1, "おこづかい": 0}

    def fake_report(user_id, index, modifi, user_name):
        calls.append(("report", index, modifi))
        balance[index] = balance.get(index, 0) + modifi
        return balance[index]

    monkeypatch.setattr(daily.ub, "report", fake_report)
    monkeypatch.setattr(
        daily.ub, "attachment_file", lambda path: ("file", "attachment://image.png"))
    monkeypatch.setattr(daily.ub, "top_value", lambda key: balance["おこづかい"])
    monkeypatch.setattr(daily.guild_settings, "setting", lambda guild_id, key: 42)

    role = FakeRole()
    stale_top = FakeUser(111)
    stale_low = FakeUser(333)
    no_role = FakeUser(222)
    stale_top.roles.append(role)
    stale_low.roles.append(role)

    interaction = FakeInteraction(
        f"lotoIdButton:12345:{_today_for_lottery()}", calls)
    interaction.guild.role = role
    interaction.guild.members = {111: stale_top, 222: no_role, 333: stale_low}
    monkeypatch.setattr(daily.ub, "ranking", lambda key, limit=5: [
        (123456, 100, 1), (111, 90, 2), (222, 80, 3), (333, 70, 4)])

    cog = daily.Daily(bot=None)
    asyncio.run(cog.on_interaction(interaction))

    assert role in interaction.user.roles
    assert role not in stale_top.roles
    assert role not in stale_low.roles


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
