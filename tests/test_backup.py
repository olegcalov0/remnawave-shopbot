"""Тесты backup snapshots и restore политики (Этап 8 ТЗ + обновление политики приёма)."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tests.test_migrations import test_db  # noqa: F401

from shop_bot.data_manager import traffic_repository as tr_repo  # noqa: E402


def test_backup_run_lifecycle(test_db):
    run_id = tr_repo.create_backup_run("scheduled")
    assert run_id is not None
    tr_repo.update_backup_run(run_id, snapshot_status="complete", archive_name="a.zip", completed=True)
    run = tr_repo.get_backup_run(run_id)
    assert run["snapshot_status"] == "complete"
    assert run["archive_name"] == "a.zip"
    assert run["completed_at"]


def test_snapshot_records(test_db):
    run_id = tr_repo.create_backup_run("manual", requested_by=42)
    tr_repo.record_state_snapshot({
        "backup_run_id": run_id, "key_id": 1, "pair_id": None,
        "target_role": "primary", "remnawave_user_id": "9",
        "traffic_limit_bytes": 100, "used_traffic_bytes": 10,
        "status": "ACTIVE", "payload": {"x": 1},
    })
    tr_repo.record_state_snapshot({
        "backup_run_id": run_id, "key_id": 2, "pair_id": None,
        "target_role": "primary", "remnawave_user_id": "10",
        "collection_error": "user not found",
    })
    with sqlite3.connect(test_db) as conn:
        rows = conn.execute(
            "SELECT key_id, collection_error FROM remnawave_state_snapshots WHERE backup_run_id = ?",
            (run_id,)).fetchall()
    assert len(rows) == 2
    assert {r[0] for r in rows} == {1, 2}


def _make_legacy_db(db_path: Path):
    """БД старой версии: core-таблицы есть, schema_version нет, новых таблиц нет."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE users (telegram_id INTEGER, username TEXT)")
        conn.execute("INSERT INTO users VALUES (111, 'alice')")
        conn.execute("CREATE TABLE vpn_keys (key_id INTEGER PRIMARY KEY, user_id INTEGER)")
        conn.execute("CREATE TABLE transactions (transaction_id INTEGER PRIMARY KEY, payment_id TEXT)")
        conn.execute("CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE xui_hosts (host_name TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE plans (plan_id INTEGER PRIMARY KEY, plan_name TEXT, price REAL)")
        conn.execute("INSERT INTO plans VALUES (1, 'Old', 100.0)")
        conn.commit()


def test_validate_legacy_db_is_accepted_with_warning(tmp_path):
    """Старая БД валидна со статусом legacy (принимается, не отклоняется)."""
    from shop_bot.data_manager import backup_manager
    old_db = tmp_path / "legacy.db"
    _make_legacy_db(old_db)
    ok, status, message = backup_manager.validate_db_file(old_db)
    assert ok is True
    assert status == "legacy"
    assert "СТАРОЙ" not in message  # message lowercase для журнала
    assert "мигрирована" in message or "миграция" in message


def test_validate_invalid_db_rejected(tmp_path):
    """Битый файл (нет core-таблиц) отклоняется."""
    from shop_bot.data_manager import backup_manager
    bad_db = tmp_path / "bad.db"
    with sqlite3.connect(bad_db) as conn:
        conn.execute("CREATE TABLE foo (x INTEGER)")
        conn.commit()
    ok, status, message = backup_manager.validate_db_file(bad_db)
    assert ok is False
    assert status == "invalid"


def test_restore_legacy_db_accepted_and_migrated(tmp_path, monkeypatch):
    """Главный сценарий из инцидента: старая БД принимается как основная и мигрируется."""
    from shop_bot.data_manager import backup_manager, database
    from shop_bot.data_manager import remnawave_repository as rw_repo

    # рабочая БД проекта во временном каталоге
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(database, "DB_FILE", work / "users.db")
    monkeypatch.setattr(rw_repo, "DB_FILE", work / "users.db")
    monkeypatch.setattr(backup_manager, "DB_FILE", work / "users.db")
    monkeypatch.setattr(backup_manager, "BACKUPS_DIR", work / "backups")
    database.initialize_db()

    # legacy-бэкап
    legacy = tmp_path / "uploaded-legacy.db"
    _make_legacy_db(legacy)

    ok, message = backup_manager.restore_from_file(legacy)
    assert ok is True, message
    assert "СТАРОЙ" in message  # предупреждение администратору

    # проверяем: данные пользователей сохранены, миграция создала новые таблицы
    with sqlite3.connect(work / "users.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"traffic_purchases", "payment_fulfillment_jobs", "hybrid_subscription_pairs"} <= tables
        assert conn.execute(
            "SELECT value FROM bot_settings WHERE key='schema_version'").fetchone()[0] == "2"
        assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 1


def test_restore_incomplete_requires_confirm_then_allowed(tmp_path, monkeypatch):
    """Неполный snapshot: без галочки отказ, с галочкой — принят с предупреждением."""
    import json as _json
    from shop_bot.data_manager import backup_manager, database
    from shop_bot.data_manager import remnawave_repository as rw_repo

    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(database, "DB_FILE", work / "users.db")
    monkeypatch.setattr(rw_repo, "DB_FILE", work / "users.db")
    monkeypatch.setattr(backup_manager, "DB_FILE", work / "users.db")
    monkeypatch.setattr(backup_manager, "BACKUPS_DIR", work / "backups")
    database.initialize_db()

    # свежая совместимая копия как «бэкап»
    db_copy = tmp_path / "bk.db"
    with sqlite3.connect(work / "users.db") as src, sqlite3.connect(db_copy) as dst:
        src.backup(dst)

    archive = tmp_path / "db-backup-test.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(db_copy, "users.db")
    (tmp_path / "db-backup-test.manifest.json").write_text(
        _json.dumps({"snapshot_status": "incomplete"}), encoding="utf-8")

    # без подтверждения — отказ
    ok, message = backup_manager.restore_from_file(archive)
    assert ok is False
    assert "НЕПОЛНЫЙ" in message

    # с явным подтверждением — принят, с предупреждением в сообщении
    ok, message = backup_manager.restore_from_file(archive, allow_incomplete=True)
    assert ok is True
    assert "неполный" in message.lower()


def test_restore_old_schema_version_only(tmp_path, monkeypatch):
    """БД с явной старой schema_version=1: тоже принимается и мигрируется."""
    from shop_bot.data_manager import backup_manager, database
    from shop_bot.data_manager import remnawave_repository as rw_repo

    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(database, "DB_FILE", work / "users.db")
    monkeypatch.setattr(rw_repo, "DB_FILE", work / "users.db")
    monkeypatch.setattr(backup_manager, "DB_FILE", work / "users.db")
    monkeypatch.setattr(backup_manager, "BACKUPS_DIR", work / "backups")
    database.initialize_db()

    old_db = tmp_path / "v1.db"
    with sqlite3.connect(work / "users.db") as src, sqlite3.connect(old_db) as dst:
        src.backup(dst)
    with sqlite3.connect(old_db) as conn:
        conn.execute("UPDATE bot_settings SET value='1' WHERE key='schema_version'")
        for t in ("traffic_purchases", "payment_fulfillment_jobs", "hybrid_subscription_pairs",
                  "traffic_purchase_packages", "traffic_carry_balances", "traffic_operations",
                  "traffic_referral_rewards", "backup_runs", "remnawave_state_snapshots"):
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()

    ok, status, _ = backup_manager.validate_db_file(old_db)
    assert ok is True and status == "legacy"
    ok, message = backup_manager.restore_from_file(old_db)
    assert ok is True
    assert "СТАРОЙ" in message
    with sqlite3.connect(work / "users.db") as conn:
        assert conn.execute(
            "SELECT value FROM bot_settings WHERE key='schema_version'").fetchone()[0] == "2"
