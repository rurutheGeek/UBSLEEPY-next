# -*- coding: utf-8 -*-
# save.py
"""セーブデータ（おこづかい・クジびきけん・クイズ戦績）の保存。

pkdbサーバーの `ubsleepy` DB へ1件ずつupsertする。CSVのような
「読んで全部書き直す」をやめ、同時更新でも壊れないようにする。
`UBSLEEPY_DB_PASSWORD` が無いときは従来どおりCSVを使うが、これは
ローカル開発・テスト専用。本番（コンテナ）は必ずDBが設定される。
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from .logging_setup import logger

DEFAULT_DB_HOST = "pkdb.apextox.dpdns.org"
DEFAULT_DB_PORT = 5432
DEFAULT_DB_NAME = "ubsleepy"
DEFAULT_DB_USER = "ubsleepy_writer"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS save_user (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    user_name TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS save_value (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    save_key TEXT NOT NULL,
    value BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, user_id, save_key),
    CONSTRAINT save_value_user_fkey FOREIGN KEY (guild_id, user_id)
        REFERENCES save_user (guild_id, user_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS guild_setting (
    guild_id BIGINT NOT NULL,
    setting_key TEXT NOT NULL,
    value BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, setting_key)
)
"""

# ランキング・順位をギルド内で値順に引くための索引。
# guild_id 列の移行が終わってから作る（旧スキーマには列が無いため）。
INDEX_SQL = """
CREATE INDEX IF NOT EXISTS save_value_rank_idx
    ON save_value (guild_id, save_key, value DESC)
"""

# セーブデータ（おこづかい・クジびきけん・戦績）は全サーバー共通。
# DBの guild_id 列は共通スコープの固定値として使う（過去のスキーマとの互換）。
SAVE_SCOPE = 0

# 旧スキーマ（guild_idなし）からの移行。既存行は共通スコープへ入れる。
MIGRATE_SQL = (
    "ALTER TABLE save_user ADD COLUMN guild_id BIGINT",
    "ALTER TABLE save_value ADD COLUMN guild_id BIGINT",
    f"UPDATE save_user SET guild_id = {SAVE_SCOPE} WHERE guild_id IS NULL",
    f"UPDATE save_value SET guild_id = {SAVE_SCOPE} WHERE guild_id IS NULL",
    "ALTER TABLE save_user ALTER COLUMN guild_id SET NOT NULL",
    "ALTER TABLE save_value ALTER COLUMN guild_id SET NOT NULL",
    # 外部キーが save_user の主キーを参照しているので、先に外す
    "ALTER TABLE save_value DROP CONSTRAINT IF EXISTS save_value_user_id_fkey",
    "ALTER TABLE save_user DROP CONSTRAINT save_user_pkey",
    "ALTER TABLE save_user ADD PRIMARY KEY (guild_id, user_id)",
    "ALTER TABLE save_value DROP CONSTRAINT save_value_pkey",
    "ALTER TABLE save_value ADD PRIMARY KEY (guild_id, user_id, save_key)",
    "ALTER TABLE save_value ADD CONSTRAINT save_value_user_fkey "
    "FOREIGN KEY (guild_id, user_id) REFERENCES save_user (guild_id, user_id) "
    "ON DELETE CASCADE",
)

# 新規ユーザーの引換券は1枚から始める（CSV時代と同じ）
def initial_value(key: str) -> int:
    return 1 if key == "クジびきけん" else 0


def _db_config() -> dict | None:
    password = os.environ.get("UBSLEEPY_DB_PASSWORD")
    if not password:
        return None
    return {
        "host": os.environ.get("UBSLEEPY_DB_HOST", DEFAULT_DB_HOST),
        "port": int(os.environ.get("UBSLEEPY_DB_PORT", DEFAULT_DB_PORT)),
        "dbname": os.environ.get("UBSLEEPY_DB_NAME", DEFAULT_DB_NAME),
        "user": os.environ.get("UBSLEEPY_DB_USER", DEFAULT_DB_USER),
        "password": password,
        "connect_timeout": 10,
    }


class PostgresSaveStore:
    """ubsleepy DBへの読み書き。接続は使い回し、切れていたら張り直す。"""

    def __init__(self, config: dict, connect=None):
        self.config = config
        self._connect = connect
        self._connection = None

    def _connection_or_connect(self):
        if self._connection is not None and not self._connection.closed:
            return self._connection
        if self._connect is None:
            import psycopg  # 遅延import（CSVだけで動かすときは不要）

            self._connect = psycopg.connect
        self._connection = self._connect(**self.config, autocommit=True)
        self._connection.execute(CREATE_SQL)
        self._migrate_guild_columns()
        self._connection.execute(INDEX_SQL)
        return self._connection

    def _has_guild_column(self) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'save_user' AND column_name = 'guild_id'"
        ).fetchone()
        return row is not None

    def _migrate_guild_columns(self) -> None:
        """旧スキーマ（guild_idなし）をguild_id付きへ移行する。"""
        if self._has_guild_column():
            return
        with self._connection.transaction():
            for sql in MIGRATE_SQL:
                self._connection.execute(sql)

    def set_user(self, user_id: int, user_name: str) -> None:
        self._connection_or_connect().execute(
            "INSERT INTO save_user (guild_id, user_id, user_name) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE "
            "SET user_name = EXCLUDED.user_name, updated_at = now()",
            (SAVE_SCOPE, user_id, user_name),
        )

    def set_value(self, user_id: int, key: str, value: int) -> None:
        """移行用。増減ではなく値をそのまま入れる。"""
        self._connection_or_connect().execute(
            "INSERT INTO save_value (guild_id, user_id, save_key, value) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (guild_id, user_id, save_key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_at = now()",
            (SAVE_SCOPE, user_id, key, value),
        )

    def report(self, user_id: int, key: str, delta: int, user_name: str) -> int:
        """1項目をdeltaだけ増減し、増減後の値を返す。"""
        connection = self._connection_or_connect()
        with connection.transaction():
            self.set_user(user_id, user_name)
            row = connection.execute(
                "INSERT INTO save_value (guild_id, user_id, save_key, value) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (guild_id, user_id, save_key) DO UPDATE "
                "SET value = save_value.value + %s, updated_at = now() "
                "RETURNING value",
                (SAVE_SCOPE, user_id, key, initial_value(key) + delta, delta),
            ).fetchone()
        return int(row[0])

    def ranking(self, key: str, limit: int = 5) -> list:
        """値の大きい順の (user_id, value, rank)。同値は同順位。"""
        rows = self._connection_or_connect().execute(
            "SELECT user_id, value, RANK() OVER (ORDER BY value DESC) "
            "FROM save_value WHERE guild_id = %s AND save_key = %s "
            "ORDER BY value DESC LIMIT %s",
            (SAVE_SCOPE, key, limit),
        ).fetchall()
        return [(int(user_id), int(value), int(rank))
                for user_id, value, rank in rows]

    def rank(self, user_id: int, key: str) -> int:
        """ユーザーの順位。記録が無ければ0。同値は同順位。

        全件のランク付けをせず「自分より大きい値の数+1」で求める。
        """
        connection = self._connection_or_connect()
        row = connection.execute(
            "SELECT value FROM save_value "
            "WHERE guild_id = %s AND user_id = %s AND save_key = %s",
            (SAVE_SCOPE, user_id, key),
        ).fetchone()
        if row is None:
            return 0
        value = int(row[0])
        row = connection.execute(
            "SELECT count(*) FROM save_value "
            "WHERE guild_id = %s AND save_key = %s AND value > %s",
            (SAVE_SCOPE, key, value),
        ).fetchone()
        return int(row[0]) + 1

    def top_value(self, key: str) -> int:
        """いちばん高い値。記録が無ければ0。"""
        row = self._connection_or_connect().execute(
            "SELECT value FROM save_value "
            "WHERE guild_id = %s AND save_key = %s "
            "ORDER BY value DESC LIMIT 1",
            (SAVE_SCOPE, key),
        ).fetchone()
        return int(row[0]) if row else 0

    def reset_value(self, key: str, value: int) -> None:
        """全員の値を同じ値にする（クジびきけんのリセット）。"""
        self._connection_or_connect().execute(
            "UPDATE save_value SET value = %s, updated_at = now() "
            "WHERE guild_id = %s AND save_key = %s",
            (value, SAVE_SCOPE, key),
        )

    def get_guild_setting(self, guild_id: int, key: str) -> int | None:
        """ギルド設定を読む。未設定ならNone。"""
        row = self._connection_or_connect().execute(
            "SELECT value FROM guild_setting "
            "WHERE guild_id = %s AND setting_key = %s",
            (guild_id, key),
        ).fetchone()
        return int(row[0]) if row else None

    def set_guild_setting(self, guild_id: int, key: str, value: int) -> None:
        self._connection_or_connect().execute(
            "INSERT INTO guild_setting (guild_id, setting_key, value) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (guild_id, setting_key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_at = now()",
            (guild_id, key, value),
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


# ---------------------------------------------------------------------------
# ここから下はDB未設定（ローカル開発・テスト）のときだけ通るCSV実装。
# 本番は get_store() が必ずDBストアを返すので使われない。
# ---------------------------------------------------------------------------


def report_csv(
    csv_path: str | Path, userId, repoIndex: str, modifi: int, userName: str
) -> int:
    """従来のCSV保存（DBが使えないとき。開発専用）。"""
    reports = pd.read_csv(csv_path, index_col=0)

    if repoIndex not in reports.columns:
        reports[repoIndex] = 0
        reports.to_csv(
            csv_path, index=True, index_label="ユーザーID", float_format="%.0f"
        )
        logger.info(f"新たな列を作成しました: {repoIndex}")

    # 指定されたユーザーIDが既に存在する場合はその行を参照し、そうでなければ新しい行を作成する
    if userId in reports.index:
        row = reports.loc[userId]
    else:
        row = pd.DataFrame(
            [[0] * len(reports.columns)], columns=reports.columns, index=[userId]
        )
        reports = pd.concat([reports, row], ignore_index=False)

        reports.loc[userId, "ユーザー名"] = userName
        reports.loc[userId, "クジびきけん"] = 1  # レポートに新しい行を追加
        logger.info("新たなレポートを作成しました")

    if repoIndex not in ["ユーザーID", "ユーザー名"] and modifi != 0:
        reports.loc[userId, repoIndex] += modifi
        reports.to_csv(
            csv_path, index=True, index_label="ユーザーID", float_format="%.0f"
        )
        logger.info("レポートに書き込みました")

    return reports.loc[userId, repoIndex]


def import_report_csv(store: PostgresSaveStore, csv_path: str | Path) -> int:
    """従来のreport.csvをDBへ取り込む（値をそのまま入れる）。"""
    frame = pd.read_csv(csv_path, dtype=str)
    if "ユーザーID" not in frame.columns:
        raise ValueError(f"ユーザーID列がありません: {csv_path}")
    count = 0
    for row in frame.to_dict("records"):
        raw_id = row.get("ユーザーID")
        if raw_id is None or pd.isna(raw_id):
            continue
        try:
            user_id = int(str(raw_id))
        except ValueError:
            logger.warning(f"ユーザーIDを読み飛ばしました: {raw_id}")
            continue
        store.set_user(user_id, row.get("ユーザー名") or "unknown")
        for key, value in row.items():
            if key in ("ユーザーID", "ユーザー名") or pd.isna(value):
                continue
            store.set_value(user_id, key, int(float(value)))
            count += 1
    return count


def _read_report(csv_path) -> pd.DataFrame:
    return pd.read_csv(csv_path, dtype={"ユーザーID": str})


def ranking_csv(csv_path, key: str, limit: int = 5) -> list:
    """CSVから (user_id, value, rank) を作る（DBが無い開発用）。"""
    frame = _read_report(csv_path)
    if key not in frame.columns:
        return []
    frame = frame[["ユーザーID", key]].sort_values(
        by=key, ascending=False).reset_index(drop=True)
    result = []
    previous = None
    rank = 0
    for index, row in frame.iterrows():
        value = row[key]
        if value != previous:
            rank = index + 1
            previous = value
        result.append((row["ユーザーID"], int(value), rank))
        if len(result) >= limit:
            break
    return result


def rank_csv(csv_path, user_id, key: str) -> int:
    frame = _read_report(csv_path)
    if key not in frame.columns:
        return 0
    frame = frame[["ユーザーID", key]].sort_values(
        by=key, ascending=False).reset_index(drop=True)
    target = str(user_id)
    previous = None
    rank = 0
    for index, row in frame.iterrows():
        value = row[key]
        if value != previous:
            rank = index + 1
            previous = value
        if row["ユーザーID"] == target:
            return rank
    return 0


def top_value_csv(csv_path, key: str) -> int:
    frame = _read_report(csv_path)
    if key not in frame.columns or frame.empty:
        return 0
    return int(frame[key].max())


def reset_value_csv(csv_path, key: str, value: int) -> None:
    frame = pd.read_csv(csv_path)
    frame[key] = value
    frame.to_csv(csv_path, index=False)


class SaveError(Exception):
    """セーブデータの読み書きに失敗した。"""


_STORE: PostgresSaveStore | None = None


def get_store() -> PostgresSaveStore | None:
    """設定済みならDBストア。未設定ならNone（CSVを使う）。"""
    global _STORE
    if _STORE is None:
        config = _db_config()
        if config is None:
            return None
        _STORE = PostgresSaveStore(config)
    return _STORE


def reset_store() -> None:
    global _STORE
    if _STORE is not None:
        _STORE.close()
    _STORE = None


def get_guild_setting(guild_id, key: str) -> int | None:
    """ギルド設定をDBから読む。DB未設定・失敗時はNone（既定値を使う）。"""
    store = get_store()
    if store is None:
        return None
    try:
        return store.get_guild_setting(int(guild_id), key)
    except Exception as error:
        logger.error(f"ギルド設定の読み込みに失敗しました\n{error}")
        reset_store()
        return None


def set_guild_setting(guild_id, key: str, value: int) -> bool:
    """ギルド設定をDBへ保存する。DB未設定ならFalse、失敗時はSaveError。"""
    store = get_store()
    if store is None:
        return False
    try:
        store.set_guild_setting(int(guild_id), key, int(value))
        return True
    except Exception as error:
        logger.error(f"ギルド設定の保存に失敗しました\n{error}")
        reset_store()
        raise SaveError("ギルド設定の保存に失敗しました") from error


def report(
    userId, repoIndex: str, modifi: int, userName: str,
    csv_path: str | Path
) -> int:
    """レポート（おこづかい・クジびきけん・戦績）を1項目更新する。

    DBが未設定（手元での実行）のときだけCSVを使う。DBが設定されていて
    失敗したときは、どこにも書かずSaveErrorにする。
    """
    store = get_store()
    if store is None:
        return report_csv(csv_path, userId, repoIndex, modifi, userName)
    try:
        return store.report(int(userId), repoIndex, modifi, userName)
    except Exception as error:
        logger.error(f"セーブDBへの書き込みに失敗しました\n{error}")
        reset_store()
        raise SaveError("セーブデータの保存に失敗しました") from error


def ranking(key: str, limit: int = 5, csv_path=None) -> list:
    """値の大きい順の (user_id, value, rank)。DBが無ければCSV。"""
    store = get_store()
    if store is None:
        return ranking_csv(csv_path, key, limit)
    try:
        return store.ranking(key, limit)
    except Exception as error:
        logger.error(f"ランキングの読み込みに失敗しました\n{error}")
        reset_store()
        return []


def rank(user_id, key: str, csv_path=None) -> int:
    """ユーザーの順位。記録が無ければ0。"""
    store = get_store()
    if store is None:
        return rank_csv(csv_path, user_id, key)
    try:
        return store.rank(int(user_id), key)
    except Exception as error:
        logger.error(f"順位の読み込みに失敗しました\n{error}")
        reset_store()
        return 0


def top_value(key: str, csv_path=None) -> int:
    """いちばん高い値。記録が無ければ0。"""
    store = get_store()
    if store is None:
        return top_value_csv(csv_path, key)
    try:
        return store.top_value(key)
    except Exception as error:
        logger.error(f"最高額の読み込みに失敗しました\n{error}")
        reset_store()
        return 0


def reset_value(key: str, value: int, csv_path=None) -> None:
    """全員の値を同じ値にする（クジびきけんのリセット）。"""
    store = get_store()
    if store is None:
        reset_value_csv(csv_path, key, value)
        return
    try:
        store.reset_value(key, value)
    except Exception as error:
        logger.error(f"値のリセットに失敗しました\n{error}")
        reset_store()


def main() -> None:
    """report.csvをDBへ取り込む: python -m bot_module.save save/report.csv"""
    import argparse

    parser = argparse.ArgumentParser(description="report.csvをubsleepy DBへ取り込む")
    parser.add_argument("csv", help="取り込むreport.csv")
    args = parser.parse_args()
    store = get_store()
    if store is None:
        raise SystemExit("UBSLEEPY_DB_PASSWORD が未設定です")
    count = import_report_csv(store, args.csv)
    print(f"imported {count} values")


if __name__ == "__main__":
    main()
