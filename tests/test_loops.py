# -*- coding: utf-8 -*-
# tests/test_loops.py
# tasks.loop が1回の例外で止まらないことを確認する。
import asyncio
import logging

import cogs.daily as daily
import cogs.logs as logs


def test_daily_bonus_survives_exception(monkeypatch, caplog):
    saved = []

    async def fail(*args, **kwargs):
        raise RuntimeError("送信失敗")

    monkeypatch.setattr(daily, "post_daily", fail)
    monkeypatch.setattr(daily, "save_last_daily_date", lambda day: saved.append(day))

    cog = daily.Daily(bot=None)
    with caplog.at_level(logging.ERROR, logger="ubsleepy"):
        asyncio.run(daily.Daily.daily_bonus.coro(cog))

    assert saved == []
    assert any(
        "日替わり投稿に失敗しました" in record.message for record in caplog.records
    )


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(text)


class FakeBot:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id):
        return self.channel


def _warning(handler, message):
    record = logging.LogRecord("ubsleepy", logging.WARNING, "", 0, message, None, None)
    handler.handle(record)


def test_log_relay_survives_send_failure(caplog):
    channel = FakeChannel()
    cog = logs.LogRelay(FakeBot(channel))
    try:
        _warning(cog.handler, "ひとつめ")

        async def fail_send(text):
            raise RuntimeError("送信失敗")

        original_send = channel.send
        channel.send = fail_send

        with caplog.at_level(logging.ERROR, logger="ubsleepy"):
            asyncio.run(logs.LogRelay.relay.coro(cog))
        assert channel.sent == []
        assert any("ログの中継に失敗しました" in record.message for record in caplog.records)

        channel.send = original_send
        asyncio.run(logs.LogRelay.relay.coro(cog))
        assert channel.sent == ["[WARNING] ひとつめ\n[ERROR] ログの中継に失敗しました\n送信失敗"]
    finally:
        # logger に足したハンドラをテスト間に残さない
        logs.logger.removeHandler(cog.handler)
