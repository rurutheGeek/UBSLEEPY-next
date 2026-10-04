# -*- coding: utf-8 -*-
# tests/test_daily.py
from datetime import datetime
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