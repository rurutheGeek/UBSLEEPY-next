# -*- coding: utf-8 -*-
# tests/test_logging.py
import logging

import bot_module.func as ub
from bot_module.logging_setup import DiscordLogHandler, logger


def test_output_log_is_info(caplog):
    with caplog.at_level(logging.INFO, logger="ubsleepy"):
        ub.output_log("テストINFO")
    assert ("ubsleepy", logging.INFO, "テストINFO") in [
        (record.name, record.levelno, record.message) for record in caplog.records
    ]


def test_output_warning_and_error_levels(caplog):
    with caplog.at_level(logging.INFO, logger="ubsleepy"):
        ub.output_warning("テストWARN")
        ub.output_error("テストERROR")
    levels = {record.message: record.levelno for record in caplog.records}
    assert levels["テストWARN"] == logging.WARNING
    assert levels["テストERROR"] == logging.ERROR


def _record(level, message):
    return logging.LogRecord("ubsleepy", level, "", 0, message, None, None)


def test_discord_handler_collects_warning_and_above():
    handler = DiscordLogHandler()
    handler.handle(_record(logging.INFO, "info"))
    handler.handle(_record(logging.WARNING, "warn"))
    handler.handle(_record(logging.ERROR, "err"))

    assert handler.drain() == ["[WARNING] warn", "[ERROR] err"]
    assert handler.drain() == []


def test_discord_handler_keeps_only_latest():
    handler = DiscordLogHandler(maxlen=2)
    for i in range(3):
        handler.handle(_record(logging.WARNING, f"m{i}"))

    assert handler.drain() == ["[WARNING] m1", "[WARNING] m2"]


def test_discord_handler_requeue_keeps_order():
    handler = DiscordLogHandler()
    handler.handle(_record(logging.WARNING, "first"))
    handler.handle(_record(logging.WARNING, "second"))

    lines = handler.drain()
    handler.requeue(lines)
    assert handler.drain() == ["[WARNING] first", "[WARNING] second"]


def test_logger_name_matches():
    assert logger.name == "ubsleepy"