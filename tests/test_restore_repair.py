"""Регрессионный тест инцидента: restore старой БД -> все колонки дашборда на месте.

Логи прод-инцидента 2026-10-10:
  sqlite3.OperationalError: no such column: u.registration_date
  no such column: created_date
  no such column: amount_rub
  no such column: p.months
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pytest  # noqa: E402


def _make_old_backup(db_path: Path):
    """Имитация реального старого бэкапа: узкие таблицы без поздних колонок."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT
            );
            CREATE TABLE vpn_keys (
                key_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                host_name TEXT,
                email TEXT,
                key_email TEXT,
                expire_at TIMESTAMP
            );
            CREATE TABLE transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id TEXT,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE xui_hosts (host_name TEXT PRIMARY KEY, host_url TEXT);
            CREATE TABLE plans (
                plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_name TEXT,
                plan_name TEXT,
                price REAL NOT NULL
            );
            INSERT INTO users VALUES (111, 'alice');
            INSERT INTO users VALUES (222, 'bob');
            INSERT INTO vpn_keys (user_id, host_name, key_email) VALUES (111, 'H1', 'trial_alice');
            INSERT INTO transactions (payment_id, user_id, status) VALUES ('p1', 111, 'paid');
            INSERT INTO plans (host_name, plan_name, price) VALUES ('H1', 'Basic', 100.0);
            INSERT INTO bot_settings VALUES ('admin_telegram_id', '111');
        """)
        conn.commit()


@pytest.fixture()
def restored_env(tmp_path, monkeypatch):
    from shop_bot.data_manager import backup_manager, database
    from shop_bot.data_manager import remnawave_repository as rw_repo

    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(database, "DB_FILE", work / "users.db")
    monkeypatch.setattr(rw_repo, "DB_FILE", work / "users.db")
    monkeypatch.setattr(backup_manager, "DB_FILE", work / "users.db")
    monkeypatch.setattr(backup_manager, "BACKUPS_DIR", work / "backups")
    database.initialize_db()

    old_db = tmp_path / "uploaded-old.db"
    _make_old_backup(old_db)

    ok, message = backup_manager.restore_from_file(old_db)
    assert ok, message
    return work / "users.db"


def test_dashboard_queries_after_restore(restored_env):
    """Все запросы дашборда, падавшие в инциденте, работают после restore."""
    with sqlite3.connect(restored_env) as conn:
        # get_paginated_trials: u.registration_date
        rows = conn.execute("""
            SELECT k.key_id, k.key_email, k.expire_at, k.created_at,
                   u.telegram_id, u.username, u.registration_date
            FROM vpn_keys k LEFT JOIN users u ON k.user_id = u.telegram_id
            WHERE k.key_email LIKE 'trial_%' ORDER BY k.created_at DESC LIMIT 10 OFFSET 0
        """).fetchall()
        assert rows is not None

        # transactions: created_date, amount_rub
        conn.execute("SELECT created_date, amount_rub FROM transactions LIMIT 1").fetchall()
        conn.execute("SELECT payment_method, amount_rub FROM transactions LIMIT 1").fetchall()

        # статистика по дням: registration_date / created_date
        conn.execute("SELECT DATE(registration_date) FROM users GROUP BY DATE(registration_date)").fetchall()
        conn.execute("SELECT DATE(created_date) FROM transactions GROUP BY DATE(created_date)").fetchall()

        # метрики покупателей: p.months
        conn.execute("""
            SELECT COUNT(DISTINCT t.user_id) FROM transactions t
            LEFT JOIN plans p ON t.user_id = p.host_name GROUP BY p.months
        """).fetchall()


def test_users_columns_complete_after_restore(restored_env):
    with sqlite3.connect(restored_env) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        for expected in ("registration_date", "balance", "referred_by", "total_spent",
                         "referral_balance", "seller_active", "is_banned"):
            assert expected in cols, f"users.{expected} отсутствует после repair"


def test_transactions_columns_complete_after_restore(restored_env):
    with sqlite3.connect(restored_env) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
        for expected in ("amount_rub", "created_date", "payment_method", "metadata",
                         "amount_currency", "currency_name", "username"):
            assert expected in cols, f"transactions.{expected} отсутствует после repair"


def test_plans_months_after_restore(restored_env):
    with sqlite3.connect(restored_env) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(plans)")}
        assert "months" in cols
        assert "traffic_limit_gb" in cols
        assert "hybrid_traffic_limit_gb" in cols


def test_vpn_keys_columns_after_restore(restored_env):
    with sqlite3.connect(restored_env) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(vpn_keys)")}
        for expected in ("created_at", "expire_at", "traffic_limit_bytes", "comment_key"):
            assert expected in cols


def test_user_data_preserved(restored_env):
    with sqlite3.connect(restored_env) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM vpn_keys").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
