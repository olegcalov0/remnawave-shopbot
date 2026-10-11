"""Тест: отзыв ключа удаляет обоих пользователей гибридной пары."""
import asyncio
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tests.test_migrations import test_db  # noqa: F401
from tests.test_traffic_service import _seed_host, _seed_key, _seed_pair  # noqa: E402
from shop_bot.data_manager import traffic_repository as tr_repo  # noqa: E402
from shop_bot.modules import hybrid_service  # noqa: E402
from shop_bot.modules import domain_constants as const  # noqa: E402


def test_delete_pair_users_called_on_key_delete(test_db):
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        key_id = _seed_key(conn)
        _seed_pair(conn, key_id)
        conn.commit()

    deleted = []

    from shop_bot.modules import remnawave_api
    async def fake_delete(host, uid):
        deleted.append((host, str(uid)))
        return True

    remnawave_api.delete_user_on_host = fake_delete

    pair = tr_repo.get_pair_by_primary_key(key_id)
    assert pair is not None
    assert pair["status"] == const.PAIR_ACTIVE

    ok = asyncio.run(hybrid_service.delete_pair_users(pair))
    assert ok is True
    # Оба пользователя удалены из панели: primary (101) и hybrid (202)
    assert ("H1", "101") in deleted
    assert ("H1", "202") in deleted
    assert len(deleted) == 2

    # Статус пары переведён в deleted
    pair_after = tr_repo.get_pair_by_primary_key(key_id)
    assert pair_after["status"] == const.PAIR_DELETED
