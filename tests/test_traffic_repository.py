"""Тесты репозитория: условные переходы статусов, идемпотентность (Этап 1/3 ТЗ)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tests.test_migrations import test_db  # noqa: F401  (fixture reuse)

from shop_bot.data_manager import traffic_repository as tr_repo  # noqa: E402
from shop_bot.modules import domain_constants as const  # noqa: E402


def _seed_key(conn, key_id=None, user_id=1, email="u1@bot.local"):
    cur = conn.execute(
        "INSERT INTO vpn_keys (user_id, host_name, email) VALUES (?, ?, ?)",
        (user_id, "H1", email))
    return cur.lastrowid


FUTURE = "2200-01-01 00:00:00"


def test_job_claim_only_one_wins(test_db, monkeypatch):
    """Условный transition job: только один конкурентный обработчик становится processing."""
    tr_repo.upsert_fulfillment_job("pay-race", "test", "top_up", {"user_id": 1})
    jobs_a = tr_repo.claim_due_job("tokenA", FUTURE)
    jobs_b = tr_repo.claim_due_job("tokenB", FUTURE)
    assert len(jobs_a) == 1 and jobs_a[0]["payment_id"] == "pay-race"
    assert jobs_b == [], "second claim must not win an already-processing job"


def test_duplicate_webhook_creates_one_job(test_db):
    """Повторный webhook создаёт максимум одну job (UNIQUE payment_id)."""
    assert tr_repo.upsert_fulfillment_job("pay-dup", "YooKassa", "new", {"a": 1}) is not None
    assert tr_repo.upsert_fulfillment_job("pay-dup", "YooKassa", "new", {"a": 1}) is None


def test_mark_pending_paid_once(test_db):
    """pending->paid атомарно один раз."""
    from shop_bot.data_manager import database as db
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO pending_transactions (payment_id, user_id, amount_rub, metadata, status) VALUES (?,?,?,?,?)",
            ("pay-once", 1, 100.0, '{"action": "top_up", "price": 100}', 'pending'))
        conn.commit()
    first = tr_repo.mark_pending_paid_once("pay-once")
    assert first is not None and first.get("action") == "top_up"
    second = tr_repo.mark_pending_paid_once("pay-once")
    assert second is None, "повторная обработка должна быть отклонена"


def test_purchase_status_transition_once(test_db):
    """Условный переход purchase: fulfilling выигрывает один обработчик."""
    with sqlite3.connect(test_db) as conn:
        key_id = _seed_key(conn)
        conn.execute(
            "INSERT INTO traffic_purchases (payment_id, user_id, key_id, host_name, target_role, target_remnawave_user_id, traffic_type, gb_amount, is_non_burnable, source_kind, total_price_rub, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("pay-tr", 1, key_id, "H1", "primary", "7", "wifi", 5, 0, "custom", 100, "paid"))
        conn.commit()
    ok1 = tr_repo.transition_purchase_status(
        "pay-tr", (const.PURCHASE_PAID,), const.PURCHASE_FULFILLING)
    ok2 = tr_repo.transition_purchase_status(
        "pay-tr", (const.PURCHASE_PAID,), const.PURCHASE_FULFILLING)
    assert ok1 and not ok2


def test_carry_balance_unique_and_add(test_db):
    with sqlite3.connect(test_db) as conn:
        key_id = _seed_key(conn)
        conn.commit()
    tr_repo.ensure_carry_balance(key_id, "primary", "wifi", "2030-01-01")
    # повторный ensure — no-op
    tr_repo.ensure_carry_balance(key_id, "primary", "wifi", "2030-01-01")
    assert tr_repo.add_carry_gb(key_id, "primary", "wifi", 25)
    bal = tr_repo.get_carry_balance(key_id, "primary", "wifi")
    assert bal["remaining_gb"] == 25
    tr_repo.add_carry_gb(key_id, "primary", "wifi", 10)
    assert tr_repo.get_carry_balance(key_id, "primary", "wifi")["remaining_gb"] == 35
    # UNIQUE
    with pytest.raises(sqlite3.IntegrityError):
        with sqlite3.connect(test_db) as conn:
            conn.execute(
                "INSERT INTO traffic_carry_balances (key_id, target_role, traffic_type, remaining_gb, next_reset_date) VALUES (?,?,?,?,?)",
                (key_id, "primary", "wifi", 1, "2030-01-01"))


def test_operations_idempotency_key(test_db):
    with sqlite3.connect(test_db) as conn:
        key_id = _seed_key(conn)
        conn.commit()
    op1 = tr_repo.record_traffic_operation(
        idempotency_key="purchase_credit:pay-x", operation_type="purchase_credit",
        key_id=key_id, actor_type="user", result="success", gb_delta=5)
    op2 = tr_repo.record_traffic_operation(
        idempotency_key="purchase_credit:pay-x", operation_type="purchase_credit",
        key_id=key_id, actor_type="user", result="success", gb_delta=5)
    assert op1 is not None and op2 is None
    assert tr_repo.operation_exists("purchase_credit:pay-x")


def test_retry_then_manual_review(test_db):
    tr_repo.upsert_fulfillment_job("pay-retry", "test", "top_up", {})
    job = tr_repo.claim_due_job("tok", FUTURE)[0]
    for i in range(1, 11):
        # после 10 неудачных попыток job попадает в manual_review
        tr_repo.fail_job_retryable(job["job_id"], f"err{i}", FUTURE, max_attempts=10)
        if i < 10:
            job = tr_repo.claim_due_job(f"tok{i}", FUTURE)[0]
    final = tr_repo.get_fulfillment_job("pay-retry")
    assert final["status"] == "manual_review"
    assert final["attempts"] == 10


def test_release_stale_processing(test_db):
    tr_repo.upsert_fulfillment_job("pay-stale", "t", "top_up", {})
    tr_repo.claim_due_job("tok", FUTURE)
    released = tr_repo.release_stale_jobs("2300-01-01 00:00:00")
    assert released == 1
    job = tr_repo.get_fulfillment_job("pay-stale")
    assert job["status"] == "retryable_failure"
