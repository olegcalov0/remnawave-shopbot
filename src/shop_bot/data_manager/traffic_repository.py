"""Репозиторий нового домена: трафик, гибридные пары, fulfillment jobs, snapshots.

Этап 1 ТЗ, п.3. Все переходы статусов — условные (атомарные) UPDATE,
операции оплаты/начисления — короткие SQLite-транзакции BEGIN IMMEDIATE.
Запрещено INSERT OR REPLACE для денег/платежей/purchase/jobs/balances.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Any

from shop_bot.data_manager import database
from shop_bot.modules import utils_common as uc
from shop_bot.modules import domain_constants as const

logger = logging.getLogger(__name__)

DB_FILE = database.DB_FILE


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(database.DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    return uc.now_str()


# =====================================================================
# Хост-настройки гибрида и докупки
# =====================================================================

HOST_HYBRID_FIELDS = (
    "hybrid_enabled", "hybrid_suffix", "hybrid_squad_uuid",
    "hybrid_wifi_enabled", "hybrid_lte_enabled",
    "traffic_purchase_enabled", "wifi_traffic_name", "lte_traffic_name",
    "wifi_burnable_price_per_gb", "wifi_non_burnable_price_per_gb",
    "lte_burnable_price_per_gb", "lte_non_burnable_price_per_gb",
    "low_traffic_threshold_percent",
    "traffic_purchase_min_gb", "traffic_purchase_max_gb",
)


def get_host_hybrid_settings(host_name: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT host_name, squad_uuid, hybrid_enabled, hybrid_suffix, hybrid_squad_uuid, "
            "hybrid_wifi_enabled, hybrid_lte_enabled, traffic_purchase_enabled, "
            "wifi_traffic_name, lte_traffic_name, "
            "wifi_burnable_price_per_gb, wifi_non_burnable_price_per_gb, "
            "lte_burnable_price_per_gb, lte_non_burnable_price_per_gb, "
            "low_traffic_threshold_percent, traffic_purchase_min_gb, traffic_purchase_max_gb, "
            "is_active "
            "FROM xui_hosts WHERE TRIM(host_name) = TRIM(?)",
            (host_name,),
        ).fetchone()
        return dict(row) if row else None


def update_host_hybrid_settings(host_name: str, values: dict[str, Any]) -> bool:
    allowed = set(HOST_HYBRID_FIELDS)
    sets, params = [], []
    for key, value in values.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return False
    params.append(host_name)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE xui_hosts SET {', '.join(sets)} WHERE TRIM(host_name) = TRIM(?)", params)
        conn.commit()
        return cur.rowcount > 0


# =====================================================================
# Пакеты докупки (CRUD)
# =====================================================================

def list_traffic_packages(host_name: str, traffic_type: str | None = None, active_only: bool = True) -> list[dict]:
    query = "SELECT * FROM traffic_purchase_packages WHERE host_name = ?"
    params: list[Any] = [host_name]
    if traffic_type:
        if traffic_type not in const.TRAFFIC_TYPES:
            raise ValueError("invalid traffic_type")
        query += " AND traffic_type = ?"
        params.append(traffic_type)
    if active_only:
        query += " AND is_active = 1"
    query += " ORDER BY sort_order ASC, gb_amount ASC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_traffic_package(package_id: int, host_name: str | None = None) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM traffic_purchase_packages WHERE package_id = ?", (package_id,)
        ).fetchone()
        if row and host_name and row["host_name"] != host_name:
            return None
        return dict(row) if row else None


def add_traffic_package(host_name: str, traffic_type: str, gb_amount: int, price_rub, sort_order: int = 0) -> int | None:
    if traffic_type not in const.TRAFFIC_TYPES:
        raise ValueError("invalid traffic_type")
    gb = int(gb_amount)
    if not (1 <= gb <= 1000):
        raise ValueError("gb_amount must be 1..1000")
    price = uc.round_money(price_rub)
    if price <= 0:
        raise ValueError("price must be positive")
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO traffic_purchase_packages
               (host_name, traffic_type, gb_amount, price_rub, sort_order)
               VALUES (?, ?, ?, ?, ?)""",
            (host_name, traffic_type, gb, str(price), int(sort_order)),
        )
        conn.commit()
        return cur.lastrowid


def update_traffic_package(package_id: int, **fields) -> bool:
    allowed = {"traffic_type", "gb_amount", "price_rub", "is_active", "sort_order"}
    sets, params = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "traffic_type" and value not in const.TRAFFIC_TYPES:
            raise ValueError("invalid traffic_type")
        if key == "price_rub":
            value = str(uc.round_money(value))
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(package_id)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE traffic_purchase_packages SET {', '.join(sets)} WHERE package_id = ?", params)
        conn.commit()
        return cur.rowcount > 0


def delete_traffic_package(package_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE traffic_purchase_packages SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE package_id = ?",
            (package_id,))
        conn.commit()
        return cur.rowcount > 0


# =====================================================================
# Гибридные пары
# =====================================================================

def create_pair(row: dict) -> int | None:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO hybrid_subscription_pairs
               (primary_key_id, user_id, host_name, telegram_id, base_username, hybrid_username,
                primary_remnawave_user_id, hybrid_remnawave_user_id, primary_email, hybrid_email,
                primary_squad_uuid, hybrid_squad_uuid, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                row["primary_key_id"], row["user_id"], row["host_name"], row["telegram_id"],
                row["base_username"], row["hybrid_username"],
                str(row["primary_remnawave_user_id"]), str(row["hybrid_remnawave_user_id"]),
                row["primary_email"], row["hybrid_email"],
                row["primary_squad_uuid"], row["hybrid_squad_uuid"],
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_pair_by_primary_key(key_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM hybrid_subscription_pairs WHERE primary_key_id = ?", (key_id,)
        ).fetchone()
        return dict(row) if row else None


def get_pair_by_id(pair_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM hybrid_subscription_pairs WHERE pair_id = ?", (pair_id,)
        ).fetchone()
        return dict(row) if row else None


def get_pair_by_hybrid_user_id(remnawave_user_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM hybrid_subscription_pairs WHERE hybrid_remnawave_user_id = ? AND status != 'deleted'",
            (str(remnawave_user_id),)).fetchone()
        return dict(row) if row else None


def get_pair_by_primary_user_id(remnawave_user_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM hybrid_subscription_pairs WHERE primary_remnawave_user_id = ? AND status != 'deleted'",
            (str(remnawave_user_id),)).fetchone()
        return dict(row) if row else None


def update_pair_status(pair_id: int, status: str, *, error: str | None = None) -> bool:
    if status not in (const.PAIR_ACTIVE, const.PAIR_REPAIR_REQUIRED, const.PAIR_BROKEN,
                      const.PAIR_DETACHED, const.PAIR_DELETED):
        raise ValueError("invalid pair status")
    sets = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
    params: list[Any] = [status]
    if error is not None:
        sets.append("last_sync_error = ?")
        params.append(error)
    if status == const.PAIR_DETACHED:
        sets.append("detached_at = CURRENT_TIMESTAMP")
    params.append(pair_id)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE hybrid_subscription_pairs SET {', '.join(sets)} WHERE pair_id = ?", params)
        conn.commit()
        return cur.rowcount > 0


def mark_pair_sync(pair_id: int, ok: bool, error: str | None = None) -> bool:
    with _connect() as conn:
        conn.execute(
            "UPDATE hybrid_subscription_pairs SET last_sync_status = ?, last_sync_error = ?, updated_at = CURRENT_TIMESTAMP WHERE pair_id = ?",
            ("ok" if ok else "error", error, pair_id))
        conn.commit()
        return True


def detach_pair(pair_id: int, detached_by: int) -> bool:
    with _connect() as conn:
        conn.execute(
            "UPDATE hybrid_subscription_pairs SET status = 'detached', detached_at = CURRENT_TIMESTAMP, detached_by = ?, updated_at = CURRENT_TIMESTAMP WHERE pair_id = ?",
            (detached_by, pair_id))
        conn.commit()
        return True


def list_active_pairs(host_name: str | None = None) -> list[dict]:
    query = "SELECT * FROM hybrid_subscription_pairs WHERE status IN ('active', 'repair_required')"
    params: list[Any] = []
    if host_name:
        query += " AND host_name = ?"
        params.append(host_name)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# =====================================================================
# Carry balances
# =====================================================================

def get_carry_balance(key_id: int, target_role: str, traffic_type: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM traffic_carry_balances WHERE key_id = ? AND target_role = ? AND traffic_type = ?",
            (key_id, target_role, traffic_type)).fetchone()
        return dict(row) if row else None


def ensure_carry_balance(key_id: int, target_role: str, traffic_type: str, next_reset_date: str) -> int | None:
    """Создать (если нет) carry-строку с next_reset_date; возвращает balance_id."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO traffic_carry_balances
               (key_id, target_role, traffic_type, remaining_gb, next_reset_date)
               VALUES (?, ?, ?, 0, ?)""",
            (key_id, target_role, traffic_type, next_reset_date))
        conn.commit()
        row = conn.execute(
            "SELECT balance_id FROM traffic_carry_balances WHERE key_id = ? AND target_role = ? AND traffic_type = ?",
            (key_id, target_role, traffic_type)).fetchone()
        return row["balance_id"] if row else None


def add_carry_gb(key_id: int, target_role: str, traffic_type: str, gb: int) -> bool:
    """Атомарное увеличение переносимого остатка. gb >= 0."""
    if int(gb) < 0:
        raise ValueError("gb must be non-negative")
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE traffic_carry_balances
               SET remaining_gb = remaining_gb + ?, updated_at = CURRENT_TIMESTAMP
               WHERE key_id = ? AND target_role = ? AND traffic_type = ?""",
            (int(gb), key_id, target_role, traffic_type))
        conn.commit()
        return cur.rowcount > 0


def set_carry_state(key_id: int, target_role: str, traffic_type: str,
                    remaining_gb: int, last_reset_date: str | None, next_reset_date: str) -> bool:
    if int(remaining_gb) < 0:
        raise ValueError("remaining_gb must be >= 0")
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE traffic_carry_balances
               SET remaining_gb = ?, last_reset_date = ?, next_reset_date = ?, updated_at = CURRENT_TIMESTAMP
               WHERE key_id = ? AND target_role = ? AND traffic_type = ?""",
            (int(remaining_gb), last_reset_date, next_reset_date, key_id, target_role, traffic_type))
        conn.commit()
        return cur.rowcount > 0


def zero_carry_gb(key_id: int, target_role: str, traffic_type: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE traffic_carry_balances SET remaining_gb = 0, updated_at = CURRENT_TIMESTAMP
               WHERE key_id = ? AND target_role = ? AND traffic_type = ?""",
            (key_id, target_role, traffic_type))
        conn.commit()
        return cur.rowcount > 0


def list_due_resets(today: str) -> list[dict]:
    """Balances с next_reset_date <= today (догоняющая обработка)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM traffic_carry_balances WHERE next_reset_date <= ? ORDER BY next_reset_date ASC",
            (today,)).fetchall()
        return [dict(r) for r in rows]


def list_users_with_carry() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT b.*, u.telegram_id FROM traffic_carry_balances b "
            "JOIN vpn_keys k ON k.key_id = b.key_id "
            "LEFT JOIN users u ON u.telegram_id = k.user_id "
            "WHERE b.remaining_gb > 0").fetchall()
        return [dict(r) for r in rows]


# =====================================================================
# Traffic purchases
# =====================================================================

def create_traffic_purchase(row: dict) -> int | None:
    """Атомарное создание purchase с UNIQUE(payment_id)."""
    with _connect() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO traffic_purchases
                   (payment_id, user_id, key_id, pair_id, host_name, target_role,
                    target_remnawave_user_id, traffic_type, gb_amount, is_non_burnable,
                    source_kind, package_id, unit_price_rub, total_price_rub, discount_rub, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created')""",
                (
                    row["payment_id"], row["user_id"], row["key_id"], row.get("pair_id"),
                    row["host_name"], row["target_role"], str(row["target_remnawave_user_id"]),
                    row["traffic_type"], int(row["gb_amount"]), 1 if row["is_non_burnable"] else 0,
                    row["source_kind"], row.get("package_id"),
                    str(row["unit_price_rub"]) if row.get("unit_price_rub") is not None else None,
                    str(row["total_price_rub"]), str(row.get("discount_rub", 0)),
                ),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None  # дубликат payment_id


def get_traffic_purchase(payment_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM traffic_purchases WHERE payment_id = ?", (payment_id,)).fetchone()
        return dict(row) if row else None


def get_traffic_purchase_by_id(purchase_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM traffic_purchases WHERE purchase_id = ?", (purchase_id,)).fetchone()
        return dict(row) if row else None


def transition_purchase_status(payment_id: str, from_statuses: tuple[str, ...], to_status: str,
                              *, extra_sets: dict[str, Any] | None = None) -> bool:
    """Условный переход статуса покупки: только один конкурентный обработчик выигрывает."""
    sets = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
    params: list[Any] = [to_status]
    for key, value in (extra_sets or {}).items():
        sets.append(f"{key} = ?")
        params.append(value)
    placeholders = ", ".join("?" for _ in from_statuses)
    params.append(payment_id)
    params.extend(from_statuses)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                f"UPDATE traffic_purchases SET {', '.join(sets)} "
                f"WHERE payment_id = ? AND status IN ({placeholders})", params)
            conn.commit()
            return cur.rowcount > 0
        except Exception:
            conn.rollback()
            raise


def increment_purchase_attempt(payment_id: str, error: str) -> bool:
    with _connect() as conn:
        conn.execute(
            "UPDATE traffic_purchases SET sync_attempts = sync_attempts + 1, last_sync_error = ?, updated_at = CURRENT_TIMESTAMP WHERE payment_id = ?",
            (error, payment_id))
        conn.commit()
        return True


def cancel_purchase_refunded(payment_id: str, *, reason: str) -> bool:
    """Перевод purchase в cancelled (возврат средств). Идемпотентен."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE traffic_purchases SET status = 'cancelled', last_sync_error = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE payment_id = ? AND status NOT IN ('fulfilled', 'cancelled')",
            (reason, payment_id))
        conn.commit()
        return cur.rowcount > 0


def list_purchases_for_key(key_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM traffic_purchases WHERE key_id = ? ORDER BY created_at DESC", (key_id,)).fetchall()
        return [dict(r) for r in rows]


def list_purchases_for_user(user_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM traffic_purchases WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]


# =====================================================================
# Audit operations (журнал)
# =====================================================================

def record_traffic_operation(
    *,
    idempotency_key: str,
    operation_type: str,
    key_id: int,
    actor_type: str,
    result: str,
    purchase_id: int | None = None,
    pair_id: int | None = None,
    target_role: str | None = None,
    target_remnawave_user_id: str | None = None,
    traffic_type: str | None = None,
    gb_delta: int = 0,
    is_non_burnable: int | None = None,
    actor_id: int | None = None,
    details: dict | None = None,
    error_text: str | None = None,
    completed: bool = True,
) -> int | None:
    """Запись в неизменяемый журнал. Повтор с тем же idempotency_key — no-op (возврат None)."""
    with _connect() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO traffic_operations
                   (idempotency_key, operation_type, purchase_id, key_id, pair_id, target_role,
                    target_remnawave_user_id, traffic_type, gb_delta, is_non_burnable,
                    actor_type, actor_id, result, details_json, error_text, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    idempotency_key, operation_type, purchase_id, key_id, pair_id, target_role,
                    target_remnawave_user_id, traffic_type, int(gb_delta), is_non_burnable,
                    actor_type, actor_id, result,
                    json.dumps(details, ensure_ascii=False) if details else None,
                    error_text,
                    _now() if completed else None,
                ),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            logger.info("traffic_operations: duplicate idempotency_key %s skipped", idempotency_key)
            return None


def operation_exists(idempotency_key: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM traffic_operations WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        return row is not None


def list_operations_for_key(key_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM traffic_operations WHERE key_id = ? ORDER BY created_at DESC", (key_id,)).fetchall()
        return [dict(r) for r in rows]


# =====================================================================
# Fulfillment jobs
# =====================================================================

def upsert_fulfillment_job(payment_id: str, provider: str, action: str, payload: dict) -> int | None:
    """Создать job при первом подтверждении оплаты; дубликат webhook — no-op."""
    with _connect() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO payment_fulfillment_jobs (payment_id, provider, action, payload_json, status)
                   VALUES (?, ?, ?, ?, 'paid')""",
                (payment_id, provider, action, json.dumps(payload, ensure_ascii=False)))
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def get_fulfillment_job(payment_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM payment_fulfillment_jobs WHERE payment_id = ?", (payment_id,)).fetchone()
        return dict(row) if row else None


def claim_due_job(lock_token: str, now_iso: str, limit: int = 5) -> list[dict]:
    """Захват due jobs условным update (только один конкурентный обработчик)."""
    claimed: list[dict] = []
    with _connect() as conn:
        rows = conn.execute(
            """SELECT job_id, payment_id, attempts FROM payment_fulfillment_jobs
               WHERE status IN ('paid', 'retryable_failure') AND next_attempt_at <= ?
               ORDER BY next_attempt_at ASC LIMIT ?""",
            (now_iso, limit)).fetchall()
        for row in rows:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    """UPDATE payment_fulfillment_jobs
                       SET status = 'processing', locked_at = ?, lock_token = ?, attempts = attempts + 1
                       WHERE job_id = ? AND status IN ('paid', 'retryable_failure')""",
                    (now_iso, lock_token, row["job_id"]))
                conn.commit()
                if cur.rowcount:
                    full = conn.execute(
                        "SELECT * FROM payment_fulfillment_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
                    if full:
                        claimed.append(dict(full))
            except Exception:
                conn.rollback()
    return claimed


def complete_job(job_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE payment_fulfillment_jobs
               SET status = 'fulfilled', completed_at = ?, last_error = NULL
               WHERE job_id = ? AND status = 'processing'""",
            (_now(), job_id))
        conn.commit()
        return cur.rowcount > 0


def fail_job_retryable(job_id: int, error: str, next_attempt_at: str, max_attempts: int = 10) -> bool:
    """retryable_failure с экспоненциальной задержкой; после max_attempts — manual_review."""
    with _connect() as conn:
        row = conn.execute("SELECT attempts, max_attempts FROM payment_fulfillment_jobs WHERE job_id = ?",
                           (job_id,)).fetchone()
        if not row:
            return False
        if row["attempts"] >= max(max_attempts, row["max_attempts"] or 10):
            conn.execute(
                "UPDATE payment_fulfillment_jobs SET status = 'manual_review', last_error = ?, completed_at = ? WHERE job_id = ?",
                (error, _now(), job_id))
            conn.commit()
            return True
        conn.execute(
            "UPDATE payment_fulfillment_jobs SET status = 'retryable_failure', last_error = ?, next_attempt_at = ? WHERE job_id = ?",
            (error, next_attempt_at, job_id))
        conn.commit()
        return True


def fail_job_manual_review(job_id: int, error: str) -> bool:
    with _connect() as conn:
        conn.execute(
            "UPDATE payment_fulfillment_jobs SET status = 'manual_review', last_error = ?, completed_at = ? WHERE job_id = ?",
            (error, _now(), job_id))
        conn.commit()
        return True


def release_stale_jobs(older_than_iso: str) -> int:
    """Сброс зависших processing-задач (после рестарта)."""
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE payment_fulfillment_jobs
               SET status = 'retryable_failure', locked_at = NULL, lock_token = NULL
               WHERE status = 'processing' AND locked_at < ?""",
            (older_than_iso,))
        conn.commit()
        return cur.rowcount


# =====================================================================
# Pending transactions (единый безопасный поток)
# =====================================================================

def mark_pending_paid_once(payment_id: str) -> dict | None:
    """Атомарно pending->paid только один раз; возвращает metadata или None."""
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT metadata, user_id, amount_rub FROM pending_transactions WHERE payment_id = ?",
                (payment_id,)).fetchone()
            if not row:
                conn.rollback()
                return None
            cur = conn.execute(
                "UPDATE pending_transactions SET status = 'paid', updated_at = ? WHERE payment_id = ? AND status = 'pending'",
                (_now(), payment_id))
            conn.commit()
            if cur.rowcount == 0:
                return None  # уже обработан повторным webhook
            try:
                meta = json.loads(row["metadata"] or "{}")
            except Exception:
                meta = {}
            meta.setdefault("payment_id", payment_id)
            meta.setdefault("user_id", row["user_id"])
            if row["amount_rub"] is not None:
                meta.setdefault("price", row["amount_rub"])
            return meta
        except Exception:
            conn.rollback()
            raise


# =====================================================================
# Referral rewards
# =====================================================================

def create_referral_reward(row: dict) -> int | None:
    with _connect() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO traffic_referral_rewards
                   (source_purchase_id, referrer_user_id, recipient_key_id, traffic_type, target_role,
                    gb_amount, is_non_burnable, percent_snapshot, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["source_purchase_id"], row["referrer_user_id"], row["recipient_key_id"],
                    row["traffic_type"], row["target_role"], int(row["gb_amount"]),
                    1 if row["is_non_burnable"] else 0, str(row["percent_snapshot"]),
                    row.get("status", const.REWARD_PENDING),
                ),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def update_referral_reward_status(reward_id: int, status: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE traffic_referral_rewards SET status = ?, fulfilled_at = ? WHERE reward_id = ?",
            (status, _now() if status == const.REWARD_FULFILLED else None, reward_id))
        conn.commit()
        return cur.rowcount > 0


def list_pending_referral_rewards() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM traffic_referral_rewards WHERE status IN ('pending', 'failed')").fetchall()
        return [dict(r) for r in rows]


# =====================================================================
# Backup runs / snapshots
# =====================================================================

def create_backup_run(source: str, requested_by: int | None = None) -> int | None:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO backup_runs (source, requested_by, snapshot_status) VALUES (?, ?, 'running')",
            (source, requested_by))
        conn.commit()
        return cur.lastrowid


def update_backup_run(backup_run_id: int, *, snapshot_status: str, snapshot_error: str | None = None,
                      archive_name: str | None = None, completed: bool = False) -> bool:
    sets = ["snapshot_status = ?", "snapshot_error = ?"]
    params: list[Any] = [snapshot_status, snapshot_error]
    if archive_name is not None:
        sets.append("archive_name = ?")
        params.append(archive_name)
    if completed:
        sets.append("completed_at = CURRENT_TIMESTAMP")
    params.append(backup_run_id)
    with _connect() as conn:
        conn.execute(f"UPDATE backup_runs SET {', '.join(sets)} WHERE backup_run_id = ?", params)
        conn.commit()
        return True


def record_state_snapshot(row: dict) -> int | None:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO remnawave_state_snapshots
               (backup_run_id, key_id, pair_id, target_role, remnawave_user_id,
                traffic_limit_bytes, used_traffic_bytes, status, expire_at, payload_json, collection_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["backup_run_id"], row["key_id"], row.get("pair_id"), row["target_role"],
                str(row["remnawave_user_id"]), row.get("traffic_limit_bytes"), row.get("used_traffic_bytes"),
                row.get("status"), row.get("expire_at"),
                json.dumps(row.get("payload"), ensure_ascii=False) if row.get("payload") else None,
                row.get("collection_error"),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_backup_run(backup_run_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM backup_runs WHERE backup_run_id = ?", (backup_run_id,)).fetchone()
        return dict(row) if row else None


def latest_backup_run() -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM backup_runs ORDER BY backup_run_id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
