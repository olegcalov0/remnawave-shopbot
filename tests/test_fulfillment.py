"""Интеграционные тесты fulfillment потока и traffic fulfillment (Этап 3/4 ТЗ)."""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tests.test_migrations import test_db  # noqa: F401

from shop_bot.data_manager import traffic_repository as tr_repo  # noqa: E402
from shop_bot.modules import fulfillment as ff  # noqa: E402
from shop_bot.modules import domain_constants as const  # noqa: E402
from tests.test_traffic_service import _seed_host, _seed_key, _seed_pair  # noqa: E402


def test_confirm_payment_and_enqueue_idempotent(test_db):
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO pending_transactions (payment_id, user_id, amount_rub, metadata, status) VALUES (?,?,?,?,?)",
            ("pay-ff", 7, 50.0, '{"action": "top_up", "user_id": 7, "price": 50}', 'pending'))
        conn.commit()
    assert ff.confirm_payment_and_enqueue("Heleket", "pay-ff")
    job = tr_repo.get_fulfillment_job("pay-ff")
    assert job is not None and job["status"] == "paid"
    # повторный webhook — job уже существует, pending уже paid: идемпотентно
    assert ff.confirm_payment_and_enqueue("Heleket", "pay-ff")
    # ровно одна job
    with sqlite3.connect(test_db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM payment_fulfillment_jobs WHERE payment_id='pay-ff'").fetchone()[0]
    assert n == 1


def test_fulfill_traffic_purchase_double_apply(test_db):
    """Повтор одного payment/job не увеличивает лимит второй раз."""
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        key_id = _seed_key(conn)
        conn.commit()

    # мокаем Remnawave API
    from shop_bot.modules import remnawave_api
    limits = []
    state = {"limit": 10 * 1024**3, "used": 0}

    async def fake_usage(uid, host_name=None):
        return {"limit_bytes": state["limit"], "used_bytes": state["used"],
                "status": "ACTIVE", "expire_at": None}

    async def fake_limit(uid, b, host_name=None, traffic_limit_strategy=None):
        limits.append(b)
        state["limit"] = b
        return True

    remnawave_api.get_user_traffic_usage = fake_usage
    remnawave_api.update_user_traffic_limit = fake_limit

    purchase_id = tr_repo.create_traffic_purchase({
        "payment_id": "pay-tp", "user_id": 1, "key_id": key_id, "host_name": "H1",
        "target_role": "primary", "target_remnawave_user_id": "101",
        "traffic_type": "wifi", "gb_amount": 5, "is_non_burnable": True,
        "source_kind": "custom", "unit_price_rub": "10", "total_price_rub": "50",
    })
    assert purchase_id is not None
    tr_repo.transition_purchase_status("pay-tp", (const.PURCHASE_CREATED,), const.PURCHASE_PAID)

    meta = {"payment_id": "pay-tp", "action": "traffic_purchase", "user_id": 1}
    ok1 = asyncio.run(ff._fulfill_only(meta))
    ok2 = asyncio.run(ff._fulfill_only(meta))
    assert ok1 and ok2
    # лимит обновлён только один раз: 10 + 5 = 15 GB
    assert len(limits) == 1
    assert limits[0] == 15 * 1024**3
    purchase = tr_repo.get_traffic_purchase("pay-tp")
    assert purchase["status"] == const.PURCHASE_FULFILLED
    # carry = 5
    bal = tr_repo.get_carry_balance(key_id, "primary", "wifi")
    assert bal["remaining_gb"] == 5


def test_fulfill_failure_leaves_purchase_retryable(test_db):
    """При API-ошибке оплата не откатывается, purchase -> retryable_failure."""
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        key_id = _seed_key(conn)
        conn.commit()

    from shop_bot.modules import remnawave_api

    async def broken_usage(uid, host_name=None):
        raise RuntimeError("panel down")

    remnawave_api.get_user_traffic_usage = broken_usage

    tr_repo.create_traffic_purchase({
        "payment_id": "pay-fail", "user_id": 1, "key_id": key_id, "host_name": "H1",
        "target_role": "primary", "target_remnawave_user_id": "101",
        "traffic_type": "wifi", "gb_amount": 5, "is_non_burnable": False,
        "source_kind": "custom", "unit_price_rub": "10", "total_price_rub": "50",
    })
    tr_repo.transition_purchase_status("pay-fail", (const.PURCHASE_CREATED,), const.PURCHASE_PAID)

    ok = asyncio.run(ff._fulfill_only({"payment_id": "pay-fail", "action": "traffic_purchase", "user_id": 1}))
    assert ok is False
    purchase = tr_repo.get_traffic_purchase("pay-fail")
    assert purchase["status"] == const.PURCHASE_RETRYABLE_FAILURE
    assert purchase["sync_attempts"] == 1
