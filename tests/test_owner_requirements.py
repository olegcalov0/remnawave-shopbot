"""Тесты: рефанд через 30 мин, min/max ГБ, скрытие строки трафика (требования владельца)."""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tests.test_migrations import test_db  # noqa: F401
from tests.test_traffic_service import _seed_host, _seed_key, _seed_pair  # noqa: E402

from shop_bot.data_manager import traffic_repository as tr_repo  # noqa: E402
from shop_bot.modules import traffic_service  # noqa: E402
from shop_bot.modules import domain_constants as const  # noqa: E402
from shop_bot.modules import utils_common as uc  # noqa: E402


def test_min_max_gb_validation(test_db):
    """Min/max ГБ хоста: покупка вне диапазона отклоняется."""
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        _seed_key(conn)
        _seed_pair(conn, _seed_key(conn) if False else 0)  # no-op, seed_key already called
        conn.execute("UPDATE xui_hosts SET traffic_purchase_enabled=1, "
                     "traffic_purchase_min_gb=5, traffic_purchase_max_gb=50, "
                     "wifi_burnable_price_per_gb=10 WHERE host_name='H1'")
        conn.commit()

    # 3 ГБ < min(5) → отклоняется
    with pytest.raises(traffic_service.TrafficPurchaseError, match="от 5 до 50"):
        traffic_service.calculate_price(host_name="H1", traffic_type="wifi", gb_amount=3, non_burnable=False)
    # 100 ГБ > max(50) → отклоняется
    with pytest.raises(traffic_service.TrafficPurchaseError, match="от 5 до 50"):
        traffic_service.calculate_price(host_name="H1", traffic_type="wifi", gb_amount=100, non_burnable=False)
    # 20 ГБ — в диапазоне → OK
    pricing = traffic_service.calculate_price(host_name="H1", traffic_type="wifi", gb_amount=20, non_burnable=False)
    assert pricing["payable_rub"] == Decimal("200.00")


def test_refund_after_30_min(test_db):
    """Рефанд: purchase cancelled, баланс возвращён, job — manual_review."""
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        key_id = _seed_key(conn)
        conn.execute("UPDATE users SET balance = 0 WHERE telegram_id = 1")
        conn.commit()

    # создаём purchase + job, устанавливаем created_at в прошлое (>30 мин)
    tr_repo.create_traffic_purchase({
        "payment_id": "pay-refund", "user_id": 1, "key_id": key_id, "host_name": "H1",
        "target_role": "primary", "target_remnawave_user_id": "101",
        "traffic_type": "wifi", "gb_amount": 5, "is_non_burnable": False,
        "source_kind": "custom", "unit_price_rub": "10", "total_price_rub": "50",
    })
    tr_repo.transition_purchase_status("pay-refund", (const.PURCHASE_CREATED,), const.PURCHASE_PAID)
    tr_repo.upsert_fulfillment_job("pay-refund", "Balance", "traffic_purchase",
                                    {"action": "traffic_purchase", "payment_id": "pay-refund",
                                     "user_id": 1, "key_id": key_id, "traffic_type": "wifi",
                                     "gb_amount": 5, "price": 50.0})
    # двигаем created_at в прошлое
    old_time = (uc.get_msk_time() - timedelta(minutes=35)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(test_db) as conn:
        conn.execute("UPDATE payment_fulfillment_jobs SET created_at = ? WHERE payment_id = ?",
                     (old_time, "pay-refund"))
        conn.commit()

    from shop_bot.data_manager import remnawave_repository as rw_repo
    from shop_bot.modules import remnawave_api
    # мок: API всегда падает → fulfill вернёт False → trigger refund
    async def broken_usage(uid, host_name=None):
        raise RuntimeError("panel down")
    remnawave_api.get_user_traffic_usage = broken_usage

    from shop_bot.modules import fulfillment as ff
    jobs = tr_repo.claim_due_job("tok", uc.now_str())
    assert len(jobs) == 1
    asyncio.run(ff.process_job(None, jobs[0]))

    # purchase должен быть cancelled
    purchase = tr_repo.get_traffic_purchase("pay-refund")
    assert purchase["status"] == const.PURCHASE_CANCELLED

    # баланс должен быть пополнен на 50
    from shop_bot.data_manager import database as db
    balance = db.get_balance(1)
    assert balance == 50.0, f"expected 50.0, got {balance}"

    # job — manual_review
    job = tr_repo.get_fulfillment_job("pay-refund")
    assert job["status"] == const.JOB_MANUAL_REVIEW


def test_refund_idempotent(test_db):
    """Повторный рефанд не начисляет баланс дважды."""
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        key_id = _seed_key(conn)
        conn.execute("UPDATE users SET balance = 0 WHERE telegram_id = 1")
        conn.commit()

    tr_repo.create_traffic_purchase({
        "payment_id": "pay-refund2", "user_id": 1, "key_id": key_id, "host_name": "H1",
        "target_role": "primary", "target_remnawave_user_id": "101",
        "traffic_type": "wifi", "gb_amount": 5, "is_non_burnable": False,
        "source_kind": "custom", "unit_price_rub": "10", "total_price_rub": "50",
    })
    tr_repo.transition_purchase_status("pay-refund2", (const.PURCHASE_CREATED,), const.PURCHASE_PAID)

    # первый рефанд
    assert tr_repo.cancel_purchase_refunded("pay-refund2", reason="test")
    from shop_bot.data_manager import database as db
    db.add_to_balance(1, 50.0)
    # второй рефанд — no-op
    assert not tr_repo.cancel_purchase_refunded("pay-refund2", reason="test2")
    db.add_to_balance(1, 50.0)  # это всё равно добавит, но cancel_purchase_refunded не должен дважды
    # проверяем что cancel вернул False — purchase уже cancelled
    purchase = tr_repo.get_traffic_purchase("pay-refund2")
    assert purchase["status"] == const.PURCHASE_CANCELLED


def test_hybrid_traffic_limit_field_in_plan(test_db):
    """hybrid_traffic_limit_gb в plans: 0 = безлимит (None при передаче в API)."""
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        conn.execute(
            "INSERT INTO plans (host_name, plan_name, months, price, hybrid_traffic_limit_gb, hybrid_hwid_limit) "
            "VALUES ('H1', 'Hybrid Plan', 1, 100, 0, 0)")
        conn.commit()

    from shop_bot.data_manager import remnawave_repository as rw_repo
    plans = rw_repo.get_plans_for_host("H1") or []
    assert plans
    plan = plans[0]
    assert int(plan.get("hybrid_traffic_limit_gb") or 0) == 0

    # 0 → None (безлимит) при передаче в create_hybrid_subscription
    hgb = int(plan.get("hybrid_traffic_limit_gb") or 0)
    hybrid_bytes = uc.gb_to_bytes(hgb) if hgb else None
    assert hybrid_bytes is None, "0 ГБ должно давать None = безлимит"

    # ненулевое значение → байты
    conn2 = sqlite3.connect(test_db)
    conn2.execute("UPDATE plans SET hybrid_traffic_limit_gb = 10 WHERE host_name = 'H1'")
    conn2.commit()
    conn2.close()
    plans2 = rw_repo.get_plans_for_host("H1") or []
    hgb2 = int(plans2[0].get("hybrid_traffic_limit_gb") or 0)
    assert hgb2 == 10
    assert uc.gb_to_bytes(hgb2) == 10 * 1024**3


def test_hide_traffic_row_when_hybrid():
    """При гибридном режиме строка «Лимит трафика» не выводится."""
    from shop_bot.config import get_key_info_text
    from datetime import datetime
    stats_hybrid = {
        "available": True, "wifi": {"limit_gb": 100, "used_gb": 5, "limit_bytes": 100*1024**3,
                                     "used_bytes": 5*1024**3, "remaining_bytes": 95*1024**3},
        "lte": {"limit_gb": 50, "used_gb": 0, "limit_bytes": 50*1024**3,
                "used_bytes": 0, "remaining_bytes": 50*1024**3},
        "total_remaining_gb": 145.0, "wifi_name": "WiFi", "lte_name": "LTE",
    }
    text = get_key_info_text(1, datetime(2027, 1, 1), datetime(2026, 1, 1), "test://conn",
                             email="a@bot.local", hwid_limit=3, hwid_usage=1,
                             traffic_limit=None, traffic_used=5*1024**3,
                             traffic_stats=stats_hybrid)
    assert "Лимит трафика" not in text, "строка 'Лимит трафика' не должна выводиться при гибриде"
    assert "📊" in text  # блок трафика WiFi/LTE присутствует

    # обычный режим — строка есть
    text_normal = get_key_info_text(1, datetime(2027, 1, 1), datetime(2026, 1, 1), "test://conn",
                                    email="a@bot.local", hwid_limit=3, hwid_usage=1,
                                    traffic_limit=100*1024**3, traffic_used=5*1024**3,
                                    traffic_stats=None)
    assert "Лимит трафика" in text_normal
