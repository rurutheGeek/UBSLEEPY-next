# -*- coding: utf-8 -*-
# tests/test_save.py
# セーブデータの保存（ubsleepy DBとCSVフォールバック）。
import contextlib

import pandas as pd
import pytest

from bot_module import save


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        if self._row is None:
            return []
        return self._row if isinstance(self._row, list) else [self._row]


class FakeConnection:
    def __init__(self, has_guild_column=True):
        self.calls = []
        self.closed = False
        self.last_value = None
        self.has_guild_column = has_guild_column

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "information_schema" in sql:
            return FakeResult((1,) if self.has_guild_column else None)
        if "RETURNING value" in sql:
            self.last_value = params[3]
            return FakeResult((self.last_value,))
        return FakeResult(None)

    def transaction(self):
        return contextlib.nullcontext()

    def close(self):
        self.closed = True


def _fake_store(has_guild_column=True):
    connection = FakeConnection(has_guild_column=has_guild_column)
    store = save.PostgresSaveStore({"password": "dummy"}, connect=lambda **kw: connection)
    return store, connection


def test_postgres_store_increments_with_upsert():
    store, connection = _fake_store()

    assert store.report(123, "おこづかい", 100, "テスト") == 100
    insert = [call for call in connection.calls if "RETURNING value" in call[0]][0]
    assert insert[1] == (save.SAVE_SCOPE, 123, "おこづかい", 100, 100)  # 新規は0+100、既存は+100
    assert any("INSERT INTO save_user" in call[0] for call in connection.calls)


def test_postgres_store_ticket_starts_at_one():
    store, connection = _fake_store()

    assert store.report(123, "クジびきけん", -1, "テスト") == 0
    insert = [call for call in connection.calls if "RETURNING value" in call[0]][0]
    assert insert[1] == (save.SAVE_SCOPE, 123, "クジびきけん", 0, -1)  # 1-1


def test_quiz_log_store_inserts():
    store, connection = _fake_store()

    store.add_quiz_log(999, "cryq", "正答", "リザードン", "リザードン", True)

    insert = [c for c in connection.calls if "INSERT INTO quiz_log" in c[0]][0]
    assert insert[1] == (
        999, "cryq", "正答", "リザードン", "リザードン", True, None, None, None)


def test_quiz_log_store_keeps_answer_and_quiz_message():
    store, connection = _fake_store()

    store.add_quiz_log(999, "ctojq", "誤答", "夢夢蝕", "ムウマ", True,
                       answer="ムシャーナ", quiz_message_id=12345, user_id=42)

    insert = [c for c in connection.calls if "INSERT INTO quiz_log" in c[0]][0]
    assert insert[1] == (
        999, "ctojq", "誤答", "夢夢蝕", "ムウマ", True, "ムシャーナ", 12345, 42)


def test_weak_questions_are_scoped_to_one_user_and_quiz():
    store, connection = _fake_store()

    assert store.weak_questions(42, "bq", 10) == []
    sql, params = [c for c in connection.calls if "GROUP BY question" in c[0]][0]
    assert "WHERE user_id = %s AND quiz_name = %s" in sql
    assert params == (42, "bq", 10)


def test_weak_questions_need_the_database(monkeypatch):
    monkeypatch.setattr(save, "get_store", lambda: None)

    assert save.weak_questions(42, "bq") is None


def test_weak_questions_failure_is_a_save_error(monkeypatch):
    class BrokenStore:
        def weak_questions(self, *args):
            raise RuntimeError("接続失敗")

    monkeypatch.setattr(save, "get_store", lambda: BrokenStore())
    monkeypatch.setattr(save, "reset_store", lambda: None)

    with pytest.raises(save.SaveError):
        save.weak_questions(42, "bq")


def test_quiz_log_table_gets_analysis_columns():
    assert "ADD COLUMN IF NOT EXISTS answer TEXT" in save.CREATE_SQL
    assert "ADD COLUMN IF NOT EXISTS quiz_message_id BIGINT" in save.CREATE_SQL
    assert "ADD COLUMN IF NOT EXISTS user_id BIGINT" in save.CREATE_SQL


def test_quiz_log_falls_back_to_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(save, "get_store", lambda: None)
    path = tmp_path / "cryqlog.csv"

    save.add_quiz_log(999, "cryq", "正答", "リザードン", "リザードン", True,
                      csv_path=path)

    frame = pd.read_csv(path)
    assert frame.loc[0, "正誤判定"] == "正答"
    assert frame.loc[0, "内容"] == "リザードン"
    assert frame.loc[0, "解答"] == "リザードン"


def test_quiz_log_failure_does_not_raise(monkeypatch):
    class BrokenStore:
        def add_quiz_log(self, *args):
            raise RuntimeError("接続失敗")

    monkeypatch.setattr(save, "get_store", lambda: BrokenStore())
    monkeypatch.setattr(save, "reset_store", lambda: None)

    save.add_quiz_log(999, "cryq", "正答", "x", "y", True)  # 例外にならない


def test_guild_setting_store_upserts():
    store, connection = _fake_store()

    assert store.get_guild_setting(1, "QUIZ_CHANNEL_ID") is None
    store.set_guild_setting(1, "QUIZ_CHANNEL_ID", 123)
    insert = [c for c in connection.calls if "INSERT INTO guild_setting" in c[0]][0]
    assert insert[1] == (1, "QUIZ_CHANNEL_ID", 123)


def test_guild_setting_without_password(monkeypatch):
    monkeypatch.delenv("UBSLEEPY_DB_PASSWORD", raising=False)
    save.reset_store()
    try:
        assert save.get_guild_setting(1, "QUIZ_CHANNEL_ID") is None
        assert save.set_guild_setting(1, "QUIZ_CHANNEL_ID", 123) is False
    finally:
        save.reset_store()


def test_store_is_none_without_password(monkeypatch):
    monkeypatch.delenv("UBSLEEPY_DB_PASSWORD", raising=False)
    save.reset_store()
    try:
        assert save.get_store() is None
    finally:
        save.reset_store()


def test_store_is_created_with_password(monkeypatch):
    monkeypatch.setenv("UBSLEEPY_DB_PASSWORD", "dummy")
    save.reset_store()
    try:
        store = save.get_store()
        assert isinstance(store, save.PostgresSaveStore)
        assert save.get_store() is store
    finally:
        save.reset_store()


class FakeStore:
    def __init__(self):
        self.users = {}
        self.values = {}

    def set_user(self, user_id, user_name):
        self.users[user_id] = user_name

    def set_value(self, user_id, key, value):
        self.values[(user_id, key)] = value


def test_import_report_csv_keeps_large_ids(tmp_path):
    path = tmp_path / "report.csv"
    path.write_text(
        "ユーザーID,ユーザー名,クジびきけん,おこづかい,bq正答\n"
        "123456789012345678,テスト,1,1500,3\n"
        "999,名無し,,250,\n",
        encoding="utf-8",
    )
    store = FakeStore()

    count = save.import_report_csv(store, path)

    assert store.users == {123456789012345678: "テスト", 999: "名無し"}
    assert store.values[(123456789012345678, "おこづかい")] == 1500
    assert store.values[(123456789012345678, "bq正答")] == 3
    assert store.values[(999, "おこづかい")] == 250
    assert (999, "bq正答") not in store.values
    assert count == 4


def test_report_raises_when_store_fails_and_does_not_write_csv(monkeypatch, tmp_path):
    path = tmp_path / "report.csv"
    path.write_text(
        "ユーザーID,ユーザー名,クジびきけん,おこづかい\n", encoding="utf-8"
    )

    class BrokenStore:
        def report(self, *args, **kwargs):
            raise RuntimeError("接続失敗")

    monkeypatch.setattr(save, "get_store", lambda: BrokenStore())
    monkeypatch.setattr(save, "reset_store", lambda: None)

    with pytest.raises(save.SaveError):
        save.report(123456789, "おこづかい", 100, "テスト", path)

    saved = pd.read_csv(path, index_col=0)
    assert saved.empty  # どこにも書かない


def test_report_uses_csv_when_store_is_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(save, "get_store", lambda: None)
    path = tmp_path / "report.csv"
    path.write_text(
        "ユーザーID,ユーザー名,クジびきけん,おこづかい\n", encoding="utf-8"
    )

    assert save.report(123456789, "おこづかい", 100, "テスト", path) == 100
    saved = pd.read_csv(path, index_col=0)
    assert saved.loc[123456789, "おこづかい"] == 100


def test_migration_runs_for_old_schema():
    store, connection = _fake_store(has_guild_column=False)
    store.get_guild_setting(1, "QUIZ_CHANNEL_ID")
    sqls = [call[0] for call in connection.calls]
    assert any("ADD COLUMN guild_id" in sql for sql in sqls)
    assert any("SET guild_id = 0" in sql for sql in sqls)
    assert any("PRIMARY KEY (guild_id, user_id)" in sql for sql in sqls)
    assert any("FOREIGN KEY (guild_id, user_id)" in sql for sql in sqls)
    # 主キーを変える前に外部キーを外す
    fk_drop = next(
        i for i, sql in enumerate(sqls)
        if "DROP CONSTRAINT IF EXISTS save_value_user_id_fkey" in sql)
    pk_drop = next(
        i for i, sql in enumerate(sqls)
        if "DROP CONSTRAINT save_user_pkey" in sql)
    assert fk_drop < pk_drop


def test_migration_skips_when_already_migrated():
    store, connection = _fake_store()
    store.get_guild_setting(1, "QUIZ_CHANNEL_ID")
    # quiz_log の列追加（ADD COLUMN IF NOT EXISTS）は毎回流れる。セーブの移行だけを見る
    assert not any("ALTER TABLE save_" in call[0] for call in connection.calls)


def test_store_ranking_sql_scopes_by_guild():
    store, connection = _fake_store()
    store.ranking("おこづかい", 5)
    sql, params = [c for c in connection.calls if "RANK() OVER" in c[0]][0]
    assert "guild_id = %s" in sql
    assert params == (save.SAVE_SCOPE, "おこづかい", 5)


def test_ranking_csv_ranks_ties_together(tmp_path):
    path = tmp_path / "report.csv"
    path.write_text(
        "ユーザーID,ユーザー名,おこづかい\n"
        "1,あ,300\n2,い,200\n3,う,200\n4,え,100\n",
        encoding="utf-8")
    assert save.ranking_csv(path, "おこづかい") == [
        ("1", 300, 1), ("2", 200, 2), ("3", 200, 2), ("4", 100, 4)]
    assert save.rank_csv(path, 3, "おこづかい") == 2
    assert save.rank_csv(path, 999, "おこづかい") == 0
    assert save.top_value_csv(path, "おこづかい") == 300


def test_reset_value_csv_sets_all(tmp_path):
    path = tmp_path / "report.csv"
    path.write_text("ユーザーID,ユーザー名,クジびきけん\n1,あ,0\n2,い,0\n",
                    encoding="utf-8")
    save.reset_value_csv(path, "クジびきけん", 1)
    frame = pd.read_csv(path, dtype={"ユーザーID": str})
    assert list(frame["クジびきけん"]) == [1, 1]


def test_store_rank_counts_higher_values():
    class RankConnection(FakeConnection):
        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            if "information_schema" in sql:
                return FakeResult((1,))
            if "SELECT value FROM save_value" in sql:
                return FakeResult((100,))
            if "count(*)" in sql:
                return FakeResult((2,))
            return FakeResult(None)

    connection = RankConnection()
    store = save.PostgresSaveStore(
        {"password": "dummy"}, connect=lambda **kw: connection)

    assert store.rank(123, "おこづかい") == 3
    count_sql, params = [c for c in connection.calls if "count(*)" in c[0]][0]
    assert params == (save.SAVE_SCOPE, "おこづかい", 100)


def test_index_is_created_after_migration():
    store, connection = _fake_store(has_guild_column=False)
    store.get_guild_setting(1, "QUIZ_CHANNEL_ID")
    sqls = [call[0] for call in connection.calls]
    index_at = next(
        i for i, sql in enumerate(sqls) if "save_value_rank_idx" in sql)
    fk_add = next(
        i for i, sql in enumerate(sqls)
        if "ADD CONSTRAINT save_value_user_fkey" in sql)
    assert index_at > fk_add
