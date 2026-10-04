# -*- coding: utf-8 -*-
# save.py
"""セーブデータ（おこづかい・クジびきけん・クイズ戦績）の保存。

pkdbサーバーの `ubsleepy` DB へ1件ずつupsertする。CSVのような
「読んで全部書き直す」をやめ、同時更新でも壊れないようにする。
`UBSLEEPY_DB_PASSWORD` が無いときは従来どおりCSVを使う。
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
    user_id BIGINT PRIMARY KEY,
    user_name TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS save_value (
    user_id BIGINT NOT NULL REFERENCES save_user(user_id) ON DELETE CASCADE,
    save_key TEXT NOT NULL,
    value BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, save_key)
)
"""

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
        return self._connection

    def set_user(self, user_id: int, user_name: str) -> None:
        self._connection_or_connect().execute(
            "INSERT INTO save_user (user_id, user_name) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO UPDATE "
            "SET user_name = EXCLUDED.user_name, updated_at = now()",
            (user_id, user_name),
        )

    def set_value(self, user_id: int, key: str, value: int) -> None:
        """移行用。増減ではなく値をそのまま入れる。"""
        self._connection_or_connect().execute(
            "INSERT INTO save_value (user_id, save_key, value) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id, save_key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_at = now()",
            (user_id, key, value),
        )

    def report(self, user_id: int, key: str, delta: int, user_name: str) -> int:
        """1項目をdeltaだけ増減し、増減後の値を返す。"""
        connection = self._connection_or_connect()
        with connection.transaction():
            self.set_user(user_id, user_name)
            row = connection.execute(
                "INSERT INTO save_value (user_id, save_key, value) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, save_key) DO UPDATE "
                "SET value = save_value.value + %s, updated_at = now() "
                "RETURNING value",
                (user_id, key, initial_value(key) + delta, delta),
            ).fetchone()
        return int(row[0])

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def report_csv(
    csv_path: str | Path, userId, repoIndex: str, modifi: int, userName: str
) -> int:
    """従来のCSV保存（DBが使えないとき）。"""
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


def report(
    userId, repoIndex: str, modifi: int, userName: str, csv_path: str | Path
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
