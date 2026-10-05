# -*- coding: utf-8 -*-
# tests/test_debug_cli.py
# DiscordなしのデバッグCLI（本物のCogを偽Discordで呼ぶ）。
import asyncio

import pytest


@pytest.fixture
def harness(monkeypatch, tmp_path):
    import bot_module.config as cfg
    import bot_module.func as ub

    report_path = str(tmp_path / "report.csv")
    monkeypatch.setattr(cfg, "REPORT_PATH", report_path)
    monkeypatch.setattr(ub, "REPORT_PATH", report_path)
    monkeypatch.setattr(ub, "BSS_GRAPH_PATH", str(tmp_path / "graph.png"))

    from debug_cli import Harness

    instance = Harness(save=False)
    yield instance
    instance.restore()


def test_dex_prints_embed(harness, capsys):
    asyncio.run(harness.dispatch(["dex", "リザードン"]))

    out = capsys.readouterr().out
    assert "リザードンの図鑑データ" in out
    assert "No.6" in out


def test_dex_not_found(harness, capsys):
    asyncio.run(harness.dispatch(["dex", "でんきだま"]))

    assert "404 NotFound" in capsys.readouterr().out


def test_search_query(harness, capsys):
    asyncio.run(harness.dispatch(["search", "みず", "合計<400"]))

    out = capsys.readouterr().out
    assert "検索結果" in out
    assert "ゼニガメ" in out


def test_search_panel(harness, capsys):
    asyncio.run(harness.dispatch(["search"]))

    out = capsys.readouterr().out
    assert "ポケモンサーチャー" in out
    assert "view:" in out


def test_quiz_hint_and_give(harness, capsys):
    asyncio.run(harness.dispatch(["q", "bq"]))
    asyncio.run(harness.dispatch(["hint", "ヒント"]))
    asyncio.run(harness.dispatch(["give"]))

    out = capsys.readouterr().out
    assert "出題: 種族値クイズ" in out
    assert "答えは" in out


def test_quiz_answer_wrong(harness, capsys):
    asyncio.run(harness.dispatch(["q", "bq"]))
    asyncio.run(harness.dispatch(["answer", "でんきだま"]))

    out = capsys.readouterr().out
    assert "図鑑に登録されていません" in out


def test_pocketmoney_without_users(harness, capsys):
    asyncio.run(harness.dispatch(["pocketmoney"]))

    out = capsys.readouterr().out
    assert "おこづかい銀行" in out
    assert "まだ ランキングは ないみたい" in out


def test_bqdata_reset(harness, capsys):
    asyncio.run(harness.dispatch(["bqdata", "リセット"]))

    out = capsys.readouterr().out
    assert "種族値クイズの出題条件" in out
    assert "最終進化" in out


def test_stdin_mode_runs_commands_in_one_process(harness, capsys, monkeypatch):
    import io
    import sys

    monkeypatch.setattr(
        sys, "stdin", io.StringIO("dex リザードン\nsearch みず 合計<400\n")
    )

    asyncio.run(harness.run_stdin())

    out = capsys.readouterr().out
    assert "リザードンの図鑑データ" in out
    assert "検索結果" in out


def test_stdin_mode_keeps_quiz_state(harness, capsys, monkeypatch):
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO("q bq\nhint ヒント\ngive\n"))

    asyncio.run(harness.run_stdin())

    out = capsys.readouterr().out
    assert "出題: 種族値クイズ" in out
    assert "答えは" in out


def test_comp_and_simil_use_followup(harness, capsys):
    asyncio.run(harness.dispatch(["comp", "リザードン", "ピカチュウ"]))
    asyncio.run(harness.dispatch(["simil", "リザードン", "final"]))

    out = capsys.readouterr().out
    assert "種族値を比較" in out
    assert "似ている種族値" in out
    assert "エラー" not in out
