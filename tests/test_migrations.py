"""Тестовая инфраструктура: отдельная временная тестовая БД (Этап 0 ТЗ).

Все тесты работают во временной БД; тестовый хост Remnawave не используется
в unit-тестах — для API-операций применяются fakes/mocks.
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Создать чистую тестовую БД и переопределить database.DB_FILE."""
    db_path = tmp_path / "test_users.db"

    from shop_bot.data_manager import database

    saved = database.DB_FILE
    monkeypatch.setattr(database, "DB_FILE", db_path)

    import shop_bot.data_manager.remnawave_repository as rw_repo

    monkeypatch.setattr(rw_repo, "DB_FILE", db_path)

    # fresh module-level references are read at call time via database.DB_FILE
    database.initialize_db()
    yield db_path

    # restore
    monkeypatch.setattr(database, "DB_FILE", saved)
    monkeypatch.setattr(rw_repo, "DB_FILE", saved)


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in cur.fetchall()}


def _column_names(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cur.fetchall()}


def test_initialize_creates_core_tables(test_db):
    tables = _table_names(test_db)
    for required in ("users", "vpn_keys", "transactions", "pending_transactions",
                     "plans", "xui_hosts", "bot_settings"):
        assert required in tables, f"missing table {required}"


def test_new_domain_tables_created(test_db):
    tables = _table_names(test_db)
    for required in (
        "traffic_purchase_packages",
        "hybrid_subscription_pairs",
        "traffic_carry_balances",
        "traffic_purchases",
        "traffic_operations",
        "traffic_referral_rewards",
        "payment_fulfillment_jobs",
        "backup_runs",
        "remnawave_state_snapshots",
    ):
        assert required in tables, f"missing new-domain table {required}"


def test_hosts_hybrid_columns(test_db):
    cols = _column_names(test_db, "xui_hosts")
    for required in (
        "hybrid_enabled", "hybrid_suffix", "hybrid_squad_uuid",
        "hybrid_wifi_enabled", "hybrid_lte_enabled",
        "traffic_purchase_enabled", "wifi_traffic_name", "lte_traffic_name",
        "wifi_burnable_price_per_gb", "wifi_non_burnable_price_per_gb",
        "lte_burnable_price_per_gb", "lte_non_burnable_price_per_gb",
        "low_traffic_threshold_percent",
    ):
        assert required in cols, f"missing xui_hosts column {required}"


def test_plans_hybrid_columns(test_db):
    cols = _column_names(test_db, "plans")
    assert "hybrid_traffic_limit_gb" in cols
    assert "hybrid_hwid_limit" in cols


def test_migration_idempotent(test_db):
    from shop_bot.data_manager import database

    database.run_migration()
    database.run_migration()
    # core tables still present
    tables = _table_names(test_db)
    assert {"users", "vpn_keys", "transactions", "plans", "xui_hosts"} <= tables


def test_existing_db_migration_preserves_data(tmp_path, monkeypatch):
    """Существующая БД: миграция не удаляет legacy-таблицы и данные."""
    from shop_bot.data_manager import database

    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(database, "DB_FILE", db_path)
    import shop_bot.data_manager.remnawave_repository as rw_repo
    monkeypatch.setattr(rw_repo, "DB_FILE", db_path)

    database.initialize_db()
    # insert a legacy row
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (telegram_id, username) VALUES (?, ?)", (111, "alice"))
        conn.execute(
            "INSERT INTO xui_hosts (host_name, squad_uuid) VALUES (?, ?)",
            ("Host A", "sq-1"))
        conn.execute(
            "INSERT INTO plans (host_name, plan_name, price) VALUES (?, ?, ?)",
            ("Host A", "Plan X", 100.0))
        conn.commit()

    database.run_migration()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 1
        host = conn.execute(
            "SELECT hybrid_enabled, traffic_purchase_enabled FROM xui_hosts WHERE host_name='Host A'"
        ).fetchone()
        assert host == (0, 0), "defaults must keep existing hosts in legacy mode"


def test_unique_constraints(test_db):
    """UNIQUE(payment_id), UNIQUE(primary_key_id), уникальность carry balance."""
    from shop_bot.data_manager.database import get_msk_time
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO vpn_keys (user_id, host_name, email) VALUES (1, 'h', 'a@bot.local')")
        key_id = conn.execute("SELECT key_id FROM vpn_keys").fetchone()[0]
        conn.execute(
            "INSERT INTO hybrid_subscription_pairs (primary_key_id, user_id, host_name, telegram_id, base_username, hybrid_username, primary_remnawave_user_id, hybrid_remnawave_user_id, primary_email, hybrid_email, primary_squad_uuid, hybrid_squad_uuid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (key_id, 1, 'h', 111, 'u1', 'u1sfx', '1', '2', 'a@bot.local', 'a_h@bot.local', 'sq1', 'sq2'))
        conn.execute(
            "INSERT INTO traffic_carry_balances (key_id, target_role, traffic_type, remaining_gb, next_reset_date) VALUES (?,?,?,?,?)",
            (key_id, 'primary', 'wifi', 0, '2030-01-01'))
        conn.commit()

        # UNIQUE(primary_key_id)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO hybrid_subscription_pairs (primary_key_id, user_id, host_name, telegram_id, base_username, hybrid_username, primary_remnawave_user_id, hybrid_remnawave_user_id, primary_email, hybrid_email, primary_squad_uuid, hybrid_squad_uuid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (key_id, 1, 'h', 111, 'u1', 'u1sfx', '1', '2', 'a@bot.local', 'a_h@bot.local', 'sq1', 'sq2'))
        # UNIQUE carry balance (key, role, type)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO traffic_carry_balances (key_id, target_role, traffic_type, remaining_gb, next_reset_date) VALUES (?,?,?,?,?)",
                (key_id, 'primary', 'wifi', 5, '2030-01-01'))
        # traffic_purchases UNIQUE(payment_id)
        conn.execute(
            "INSERT INTO traffic_purchases (payment_id, user_id, key_id, host_name, target_role, target_remnawave_user_id, traffic_type, gb_amount, is_non_burnable, source_kind, total_price_rub, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ('pay-1', 1, key_id, 'h', 'primary', '1', 'wifi', 5, 1, 'custom', 100, 'created'))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO traffic_purchases (payment_id, user_id, key_id, host_name, target_role, target_remnawave_user_id, traffic_type, gb_amount, is_non_burnable, source_kind, total_price_rub, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ('pay-1', 1, key_id, 'h', 'primary', '1', 'wifi', 5, 1, 'custom', 100, 'created'))


def test_schema_version_recorded(test_db):
    from shop_bot.data_manager import database
    from shop_bot.modules.domain_constants import SCHEMA_VERSION_CURRENT
    value = database.get_setting("schema_version")
    assert value == SCHEMA_VERSION_CURRENT
