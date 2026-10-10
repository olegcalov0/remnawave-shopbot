"""Тесты чистых функций helpers (Этап 0 ТЗ)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shop_bot.modules import utils_common as uc  # noqa: E402


def test_gb_bytes_roundtrip():
    assert uc.gb_to_bytes(1) == 1024 * 1024 * 1024
    assert uc.gb_to_bytes(0) == 0
    assert uc.gb_to_bytes(50) == 50 * 1024 * 1024 * 1024
    assert uc.bytes_to_gb_floor(uc.gb_to_bytes(65)) == 65
    # floor, не round
    assert uc.bytes_to_gb_floor(uc.gb_to_bytes(5) + 1024 * 1024 * 1024 - 1) == 5


def test_bytes_to_gb_display_never_rounds_up():
    # остаток не должен стать отрицательным из-за округления вверх
    used = 10 * uc.GB_IN_BYTES + 1  # чуть больше 10 ГБ
    assert uc.bytes_to_gb_display(used) <= 10.0 + 1 / uc.GB_IN_BYTES
    assert uc.bytes_to_gb_display(10 * uc.GB_IN_BYTES - 1) < 10.0


def test_money_rounding():
    from decimal import Decimal
    assert uc.round_money(Decimal("10.005")) == Decimal("10.01")
    assert uc.round_money("10.004") == Decimal("10.00")
    assert uc.money_to_str(10) == "10.00"


def test_compute_reset_date_day_clamp():
    # 31 января + 1 месяц -> 28/29 февраля (последний день)
    base = datetime(2026, 1, 31)
    nxt = uc.compute_reset_date(base, 1)
    assert (nxt.year, nxt.month, nxt.day) == (2026, 2, 28)
    # 29-31 января -> 31 марта? нет: следующий месяц — февраль (последний день)
    nxt2 = uc.compute_reset_date(datetime(2026, 3, 31), 1)
    assert (nxt2.year, nxt2.month, nxt2.day) == (2026, 4, 30)
    # обычный случай
    nxt3 = uc.compute_reset_date(datetime(2026, 5, 15), 1)
    assert (nxt3.year, nxt3.month, nxt3.day) == (2026, 6, 15)


def test_missing_reset_dates_chronological():
    base = datetime(2025, 10, 10, 12, 0, 0)
    until = datetime(2026, 1, 15, 12, 0, 0)
    dates = uc.missing_reset_dates(base, until)
    assert [(d.year, d.month) for d in dates] == [(2025, 11), (2025, 12), (2026, 1)]
    assert dates == sorted(dates)


def test_next_reset_date_skips_past():
    from shop_bot.modules.utils_common import MSK_TZ
    base = datetime(2026, 1, 10, tzinfo=MSK_TZ)
    nxt = uc.next_reset_date(base)
    assert nxt > uc.get_msk_time() or nxt == base


def test_username_builder_rules():
    # imported lazily to avoid module init issues in clean env
    from shop_bot.modules.hybrid_service import build_remnawave_usernames, InvalidSuffixError
    # валидный username + suffix
    base, hybrid = build_remnawave_usernames("Alice", 12345, "_h")
    assert base.lower() == "alice"
    assert hybrid.lower() == "alice_h"
    # username длинный -> fallback user_{id}
    base2, hybrid2 = build_remnawave_usernames("a" * 50, 999, "_h")
    assert base2 == "user_999"
    assert hybrid2 == "user_999_h"
    # невалидные символы -> fallback
    base3, hybrid3 = build_remnawave_usernames("Ваня!!!", 777, "_x")
    assert base3 == "user_777"
    assert hybrid3 == "user_777_x"
    # suffix делает имя > 36 -> ошибка конфигурации
    import pytest
    with pytest.raises(InvalidSuffixError):
        build_remnawave_usernames("user", 1, "_" + "b" * 40)
    # пустой suffix -> ошибка
    with pytest.raises(InvalidSuffixError):
        build_remnawave_usernames("user", 1, "")
    # невалидные символы в suffix
    with pytest.raises(InvalidSuffixError):
        build_remnawave_usernames("user", 1, "-abc!")
