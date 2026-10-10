"""Полное восстановление схемы legacy-БД (schema repair).

При загрузке старого бэкапа таблицы могут существовать, но не иметь колонок,
которые добавлялись версиями проекта (registration_date, amount_rub, months, ...).
run_migration добавляет только часть колонок; repair_schema сверяет каждую
существующую таблицу с каноническим перечнем колонок и добавляет недостающие
(ALTER TABLE ADD COLUMN с безопасным default), не трогая данные.
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# Канонические колонки существующих таблиц (сверяются с initialize_db).
# Порядок не важен; definition — как в DDL.
CANONICAL_COLUMNS: dict[str, dict[str, str]] = {
    "users": {
        "telegram_id": "INTEGER PRIMARY KEY",
        "username": "TEXT",
        "username_manually_set": "BOOLEAN DEFAULT 0",
        "total_spent": "REAL DEFAULT 0",
        "total_months": "INTEGER DEFAULT 0",
        "trial_used": "BOOLEAN DEFAULT 0",
        "agreed_to_terms": "BOOLEAN DEFAULT 0",
        "registration_date": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "is_banned": "BOOLEAN DEFAULT 0",
        "balance": "REAL DEFAULT 0",
        "referred_by": "INTEGER",
        "referral_balance": "REAL DEFAULT 0",
        "referral_balance_all": "REAL DEFAULT 0",
        "referral_start_bonus_received": "BOOLEAN DEFAULT 0",
        "is_pinned": "BOOLEAN DEFAULT 0",
        "seller_active": "INTEGER DEFAULT 0",
        "app_theme": "TEXT DEFAULT 'forest'",
        "auth_token": "TEXT",
        "auth_email": "TEXT",
        "auth_pass": "TEXT",
    },
    "vpn_keys": {
        "key_id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "user_id": "INTEGER NOT NULL",
        "host_name": "TEXT",
        "squad_uuid": "TEXT",
        "remnawave_user_uuid": "TEXT",
        "short_uuid": "TEXT",
        "email": "TEXT",
        "key_email": "TEXT",
        "subscription_url": "TEXT",
        "expire_at": "TIMESTAMP",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "traffic_limit_bytes": "INTEGER",
        "traffic_limit_strategy": "TEXT DEFAULT 'NO_RESET'",
        "hwid_limit": "INTEGER",
        "tag": "TEXT",
        "description": "TEXT",
        "comment_key": "TEXT",
        "is_pinned": "BOOLEAN DEFAULT 0",
    },
    "transactions": {
        "username": "TEXT",
        "transaction_id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "payment_id": "TEXT",
        "user_id": "INTEGER NOT NULL",
        "status": "TEXT NOT NULL",
        "amount_rub": "REAL DEFAULT 0",
        "amount_currency": "REAL",
        "currency_name": "TEXT",
        "payment_method": "TEXT",
        "metadata": "TEXT",
        "created_date": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    },
    "plans": {
        "plan_id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "host_name": "TEXT",
        "squad_uuid": "TEXT",
        "plan_name": "TEXT",
        "months": "INTEGER DEFAULT 0",
        "duration_days": "INTEGER",
        "price": "REAL NOT NULL",
        "traffic_limit_bytes": "INTEGER",
        "traffic_limit_strategy": "TEXT DEFAULT 'NO_RESET'",
        "is_active": "INTEGER DEFAULT 1",
        "sort_order": "INTEGER DEFAULT 0",
        "metadata": "TEXT",
        "hwid_limit": "INTEGER DEFAULT 0",
        "traffic_limit_gb": "INTEGER DEFAULT 0",
        "button_style": "TEXT DEFAULT NULL",
        "icon_emoji_id": "TEXT DEFAULT NULL",
        "hybrid_traffic_limit_gb": "INTEGER NOT NULL DEFAULT 0",
        "hybrid_hwid_limit": "INTEGER NOT NULL DEFAULT 0",
    },
    "xui_hosts": {
        "host_name": "TEXT PRIMARY KEY",
        "squad_uuid": "TEXT",
        "description": "TEXT",
        "default_traffic_limit_bytes": "INTEGER",
        "default_traffic_strategy": "TEXT DEFAULT 'NO_RESET'",
        "default_traffic_reset_at": "TEXT",
        "host_url": "TEXT",
        "host_username": "TEXT",
        "host_pass": "TEXT",
        "host_inbound_id": "INTEGER",
        "subscription_url": "TEXT",
        "ssh_host": "TEXT",
        "ssh_port": "INTEGER",
        "ssh_user": "TEXT",
        "ssh_password": "TEXT",
        "ssh_key_path": "TEXT",
        "is_active": "INTEGER DEFAULT 1",
        "sort_order": "INTEGER DEFAULT 0",
        "metadata": "TEXT",
        "see": "INTEGER DEFAULT 1",
        "remnawave_base_url": "TEXT",
        "remnawave_api_token": "TEXT",
        "traffic_limit_strategy": "TEXT DEFAULT 'NO_RESET'",
        "device_mode": "TEXT DEFAULT 'plan'",
        "tier_lock_extend": "INTEGER DEFAULT 0",
        "button_style": "TEXT DEFAULT NULL",
        "icon_emoji_id": "TEXT DEFAULT NULL",
        # гибрид и докупка
        "hybrid_enabled": "INTEGER NOT NULL DEFAULT 0",
        "hybrid_suffix": "TEXT",
        "hybrid_squad_uuid": "TEXT",
        "hybrid_wifi_enabled": "INTEGER NOT NULL DEFAULT 1",
        "hybrid_lte_enabled": "INTEGER NOT NULL DEFAULT 1",
        "traffic_purchase_enabled": "INTEGER NOT NULL DEFAULT 0",
        "wifi_traffic_name": "TEXT DEFAULT 'WiFi гигабайты'",
        "lte_traffic_name": "TEXT DEFAULT 'LTE гигабайты'",
        "wifi_burnable_price_per_gb": "NUMERIC",
        "wifi_non_burnable_price_per_gb": "NUMERIC",
        "lte_burnable_price_per_gb": "NUMERIC",
        "lte_non_burnable_price_per_gb": "NUMERIC",
        "low_traffic_threshold_percent": "INTEGER NOT NULL DEFAULT 10",
    },
    "pending_transactions": {
        "payment_id": "TEXT PRIMARY KEY",
        "user_id": "INTEGER NOT NULL",
        "amount_rub": "REAL",
        "metadata": "TEXT",
        "status": "TEXT DEFAULT 'pending'",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    },
    "bot_settings": {
        "key": "TEXT PRIMARY KEY",
        "value": "TEXT",
    },
}

# Колонки, которые нельзя добавлять ALTER'ом (они меняют PK/UNIQUE) —
# для них repair невозможен; такие таблицы должны создаваться с нуля.
_SKIP_COLUMNS = {
    ("users", "telegram_id"),
    ("vpn_keys", "key_id"),
    ("transactions", "transaction_id"),
    ("plans", "plan_id"),
    ("xui_hosts", "host_name"),
    ("pending_transactions", "payment_id"),
    ("bot_settings", "key"),
    ("vpn_keys", "email"),
    ("vpn_keys", "key_email"),
    ("transactions", "payment_id"),
}


def repair_schema(conn: sqlite3.Connection) -> list[str]:
    """Добавить недостающие колонки в существующие таблицы. Возвращает список добавленных.

    SQLite не позволяет ALTER ADD COLUMN с неконстантным default (CURRENT_TIMESTAMP):
    такие колонки добавляются с TEXT-типом и NULL-значениями.
    """
    added: list[str] = []
    cursor = conn.cursor()
    for table, columns in CANONICAL_COLUMNS.items():
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cursor.fetchone():
                continue  # таблицы нет — её создаст initialize_db/run_migration
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cursor.fetchall()}
        except sqlite3.Error as e:
            logger.warning("repair_schema: не удалось прочитать таблицу %s: %s", table, e)
            continue
        for column, definition in columns.items():
            if column in existing:
                continue
            if (table, column) in _SKIP_COLUMNS:
                continue
            # ALTER ADD COLUMN допускает только константные default
            safe_definition = _constant_default(definition)
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {safe_definition}")
                added.append(f"{table}.{column}")
                logger.info("repair_schema: добавлена колонка %s.%s", table, column)
            except sqlite3.Error as e:
                logger.warning("repair_schema: не удалось добавить %s.%s: %s", table, column, e)
    conn.commit()
    return added


def _constant_default(definition: str) -> str:
    """Заменить CURRENT_TIMESTAMP- default на допустимый для ALTER (TEXT DEFAULT '')."""
    if "CURRENT_TIMESTAMP" in definition.upper():
        # TIMESTAMP DEFAULT CURRENT_TIMESTAMP -> TEXT DEFAULT '' (значения NULL,
        # но колонка существует и запросы работают)
        return "TEXT DEFAULT ''"
    return definition
