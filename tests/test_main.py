# -*- coding: utf-8 -*-
# tests/test_main.py
# 追加時の案内先チャンネルの選び方。
from types import SimpleNamespace

from main import greeting_channel


def test_greeting_channel_prefers_system_channel():
    system = object()
    guild = SimpleNamespace(system_channel=system, text_channels=[object()])
    assert greeting_channel(guild) is system


def test_greeting_channel_falls_back_to_first_text_channel():
    first = object()
    guild = SimpleNamespace(system_channel=None, text_channels=[first, object()])
    assert greeting_channel(guild) is first


def test_greeting_channel_none_without_text_channels():
    guild = SimpleNamespace(system_channel=None, text_channels=[])
    assert greeting_channel(guild) is None
