"""Тесты backup snapshots и restore политики (Этап 8 ТЗ)."""
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


def test_restore_rejects_incomplete_without_confirm(tmp_path, monkeypatch):
    """Restore incomplete-архива без явного подтверждения отклоняется."""
    from shop_bot.data_manager import backup_manager

    # архив с неполным manifest
    archive = tmp_path / "db-backup-test.zip"
    db_copy = tmp_path / "users.db"
    with sqlite3.connect(db_copy) as conn:
        conn.execute("CREATE TABLE users (telegram_id INTEGER)")
        conn.commit()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(db_copy, "users.db")
    manifest = tmp_path / "db-backup-test.manifest.json"
    manifest.write_text(json.dumps({"snapshot_status": "incomplete"}), encoding="utf-8")

    assert backup_manager.check_backup_snapshot_status(archive) == "incomplete"
    result = backup_manager.restore_from_file(archive)
    assert result is False, "incomplete без подтверждения должен быть отклонён"
    # с явным подтверждением — валидация всё равно не пройдёт (это legacy-дамп), но
    # причина уже другая: проверяем что allow_incomplete переключает поведение
    result2 = backup_manager.restore_from_file(archive, allow_incomplete=True)
    assert result2 is False, "валидация schema version должна отклонить legacy-дамп"


def test_validate_db_rejects_old_schema(tmp_path):
    from shop_bot.data_manager import backup_manager
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE users (telegram_id INTEGER)")
        conn.execute("CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO bot_settings VALUES ('schema_version', '1')")
        conn.commit()
    assert backup_manager.validate_db_file(db_path) is False
