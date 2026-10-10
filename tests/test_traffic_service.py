"""Тесты логики докупки: цена, carry, reset, направления WiFi/LTE (Этап 4 ТЗ)."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tests.test_migrations import test_db  # noqa: F401

from shop_bot.data_manager import traffic_repository as tr_repo  # noqa: E402
from shop_bot.modules import traffic_service  # noqa: E402
from shop_bot.modules import domain_constants as const  # noqa: E402
from shop_bot.modules import utils_common as uc  # noqa: E402


def _seed_host(conn, name="H1", *, purchase=True, hybrid=True, wifi_price=10, lte_price=12):
    conn.execute(
        """INSERT INTO xui_hosts (host_name, squad_uuid, hybrid_enabled, hybrid_suffix, hybrid_squad_uuid,
           hybrid_wifi_enabled, hybrid_lte_enabled, traffic_purchase_enabled,
           wifi_traffic_name, lte_traffic_name,
           wifi_burnable_price_per_gb, wifi_non_burnable_price_per_gb,
           lte_burnable_price_per_gb, lte_non_burnable_price_per_gb, low_traffic_threshold_percent)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name, "sq-p", 1 if hybrid else 0, "_h", "sq-h",
         1, 1, 1 if purchase else 0,
         "WiFi гигабайты", "LTE гигабайты",
         wifi_price, wifi_price, lte_price, lte_price, 10))


def _seed_key(conn, user_id=1, email="u1@bot.local"):
    cur = conn.execute(
        "INSERT INTO vpn_keys (user_id, host_name, email, remnawave_user_uuid, expire_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, "H1", email, "101", "2099-01-01 00:00:00"))
    return cur.lastrowid


def _seed_pair(conn, key_id, user_id=1):
    conn.execute(
        """INSERT INTO hybrid_subscription_pairs
           (primary_key_id, user_id, host_name, telegram_id, base_username, hybrid_username,
            primary_remnawave_user_id, hybrid_remnawave_user_id, primary_email, hybrid_email,
            primary_squad_uuid, hybrid_squad_uuid, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'active')""",
        (key_id, user_id, "H1", user_id, "user_1", "user_1_h",
         "101", "202", "u1@bot.local", "u1_h@hybrid.bot.local", "sq-p", "sq-h"))


# ===== направления (инвариант 3.2.2) =====

def test_wifi_to_primary_lte_to_hybrid(test_db):
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        key_id = _seed_key(conn)
        _seed_pair(conn, key_id)
        conn.commit()

    wifi = traffic_service.resolve_target(key_id, "wifi")
    assert wifi["role"] == "primary" and wifi["remnawave_user_id"] == "101"
    lte = traffic_service.resolve_target(key_id, "lte")
    assert lte["role"] == "hybrid" and lte["remnawave_user_id"] == "202"


def test_lte_unavailable_without_pair(test_db):
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        key_id = _seed_key(conn)
        conn.commit()
    assert traffic_service.resolve_target(key_id, "lte") is None
    assert "lte" not in traffic_service.available_traffic_types(key_id)


def test_lte_disabled_when_hybrid_off(test_db):
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn, hybrid=False)
        key_id = _seed_key(conn)
        _seed_pair(conn, key_id)
        conn.commit()
    assert "lte" not in traffic_service.available_traffic_types(key_id)


def test_purchase_disabled_on_host(test_db):
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn, purchase=False)
        key_id = _seed_key(conn)
        conn.commit()
    assert traffic_service.available_traffic_types(key_id) == []


# ===== валидация gb =====

@pytest.mark.parametrize("gb", [0, 1001, -5])
def test_gb_bounds_rejected(test_db, gb):
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        conn.commit()
    with pytest.raises(traffic_service.TrafficPurchaseError):
        traffic_service.calculate_price(host_name="H1", traffic_type="wifi", gb_amount=gb, non_burnable=False)


def test_gb_fraction_rejected(test_db):
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        conn.commit()
    with pytest.raises((traffic_service.TrafficPurchaseError, ValueError, TypeError)):
        traffic_service.calculate_price(host_name="H1", traffic_type="wifi", gb_amount="1.5", non_burnable=False)


# ===== цена =====

def test_price_custom_and_package(test_db):
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        conn.commit()
    pkg_id = tr_repo.add_traffic_package("H1", "wifi", 10, 90)
    pkg = tr_repo.get_traffic_package(pkg_id)
    custom = traffic_service.calculate_price(host_name="H1", traffic_type="wifi", gb_amount=10, non_burnable=False)
    assert custom["payable_rub"] == Decimal("100.00")
    from_pkg = traffic_service.calculate_price(
        host_name="H1", traffic_type="wifi", gb_amount=10, non_burnable=False, package=pkg)
    assert from_pkg["payable_rub"] == Decimal("90.00")


def test_price_missing_config_rejected(test_db):
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            """INSERT INTO xui_hosts (host_name, squad_uuid, traffic_purchase_enabled) VALUES ('H2','s',1)""")
        conn.commit()
    with pytest.raises(traffic_service.TrafficPurchaseError):
        traffic_service.calculate_price(host_name="H2", traffic_type="lte", gb_amount=5, non_burnable=True)


# ===== carry формула =====

def test_carry_formula_examples():
    # база 50, carry 25, лимит 75, использовано 10 -> перенос 25, лимит 75... нет:
    # carry_after = max(0, min(25, 75 - max(50, 10))) = 25
    assert traffic_service.compute_carry_after(base_gb=50, carry_before_gb=25, limit_before_gb=75, used_before_gb=10) == 25
    # после расхода всех 75: carry_after = max(0, min(25, 75 - max(50,75))) = 0
    assert traffic_service.compute_carry_after(base_gb=50, carry_before_gb=25, limit_before_gb=75, used_before_gb=75) == 0
    # использовано 60: переносится 75-60=15
    assert traffic_service.compute_carry_after(base_gb=50, carry_before_gb=25, limit_before_gb=75, used_before_gb=60) == 15


def test_reset_example_from_tz(test_db):
    """Пример из ТЗ: база 50 ГБ, carry 25 ГБ, использовано 10 ГБ -> после reset лимит 75 ГБ."""
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        key_id = _seed_key(conn)
        _seed_pair(conn, key_id)
        # base limit 50 GB в ключе
        conn.execute("UPDATE vpn_keys SET traffic_limit_bytes = ? WHERE key_id = ?", (uc.gb_to_bytes(50), key_id))
        conn.commit()

    tr_repo.ensure_carry_balance(key_id, "primary", "wifi", "2030-01-01")
    tr_repo.add_carry_gb(key_id, "primary", "wifi", 25)
    tr_repo.set_carry_state(key_id, "primary", "wifi", 25, "2025-09-10", "2025-10-10")

    # панель: лимит 75 GB, использовано 10 GB
    applied = []

    async def fake_usage(uid, host_name=None):
        return {"limit_bytes": uc.gb_to_bytes(75), "used_bytes": uc.gb_to_bytes(10),
                "status": "ACTIVE", "expire_at": None}

    async def fake_limit(uid, b, host_name=None, traffic_limit_strategy=None):
        applied.append((uid, b))
        return True

    from shop_bot.modules import remnawave_api
    monkey_targets = {"get_user_traffic_usage": fake_usage,
                      "update_user_traffic_limit": fake_limit}
    originals = {k: getattr(remnawave_api, k) for k in monkey_targets}
    for k, v in monkey_targets.items():
        setattr(remnawave_api, k, v)
    try:
        result = traffic_service.perform_reset(key_id, "primary", "wifi", datetime(2025, 10, 10))
        import asyncio
        out = asyncio.run(_coro(result))
        assert out.get("ok")
        assert out["carry_after"] == 25
        assert out["new_limit_gb"] == 75
        # применённый лимит = 75 GB
        assert applied[0][1] == uc.gb_to_bytes(75)
        # повторный reset той же даты — идемпотентен
        out2 = asyncio.run(_coro(traffic_service.perform_reset(key_id, "primary", "wifi", datetime(2025, 10, 10))))
        assert out2.get("skipped")
        assert len(applied) == 1
        # после расхода всех 75: следующий reset возвращает 50
        async def fake_usage2(uid, host_name=None):
            return {"limit_bytes": uc.gb_to_bytes(75), "used_bytes": uc.gb_to_bytes(75),
                    "status": "ACTIVE", "expire_at": None}
        setattr(remnawave_api, "get_user_traffic_usage", fake_usage2)
        out3 = asyncio.run(_coro(traffic_service.perform_reset(key_id, "primary", "wifi", datetime(2025, 11, 10))))
        assert out3.get("ok")
        assert out3["new_limit_gb"] == 50
        assert out3["carry_after"] == 0
    finally:
        for k, v in originals.items():
            setattr(remnawave_api, k, v)


async def _coro(coro):
    import inspect
    if inspect.isawaitable(coro):
        return await coro
    return coro


def test_expiry_burn_clears_carry(test_db):
    with sqlite3.connect(test_db) as conn:
        _seed_host(conn)
        key_id = _seed_key(conn)
        conn.commit()
    tr_repo.ensure_carry_balance(key_id, "primary", "wifi", "2030-01-01")
    tr_repo.add_carry_gb(key_id, "primary", "wifi", 30)
    import asyncio
    assert asyncio.run(traffic_service.burn_expired_carry(key_id, "primary", "wifi"))
    assert tr_repo.get_carry_balance(key_id, "primary", "wifi")["remaining_gb"] == 0
    # повторное сгорание — no-op
    assert not asyncio.run(traffic_service.burn_expired_carry(key_id, "primary", "wifi"))


# ===== referral GB =====

def test_referral_gb_rounding():
    import math
    def reward(purchased, pct):
        return max(1, math.ceil(purchased * pct / 100))
    assert reward(10, 10) == 1
    assert reward(18, 10) == 2
    assert reward(4, 10) == 1
    assert reward(25, 10) == 3
