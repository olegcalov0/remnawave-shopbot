"""Единые helpers для байтов/ГБ, округления цены и безопасного времени MSK.

Требование ТЗ (раздел 5, п.4): не размазывать одинаковые формулы
по handlers, scheduler и Flask routes.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

MSK_TZ = timezone(timedelta(hours=3))

GB_IN_BYTES = 1024 * 1024 * 1024


def get_msk_time() -> datetime:
    """Текущее время MSK с таймзоной."""
    return datetime.now(MSK_TZ)


def now_str() -> str:
    """Строка времени MSK формата YYYY-MM-DD HH:MM:SS."""
    return get_msk_time().strftime("%Y-%m-%d %H:%M:%S")


def today_date_str() -> str:
    return get_msk_time().strftime("%Y-%m-%d")


def gb_to_bytes(gb: int) -> int:
    """Единственное место пересчёта ГБ в байты. Только целые ГБ."""
    if gb is None:
        return 0
    gb_i = int(gb)
    if gb_i < 0:
        raise ValueError("gb must be non-negative")
    return gb_i * GB_IN_BYTES


def bytes_to_gb_floor(value_bytes: int | float | None) -> int:
    """Округление байтов вниз до целых ГБ (используется только при сохранении carry)."""
    if not value_bytes:
        return 0
    return int(value_bytes) // GB_IN_BYTES


def bytes_to_gb_display(value_bytes: int | float | None, digits: int = 2) -> float:
    """Отображение трафика в ГБ; остаток никогда не округляется вверх (допущение 9)."""
    if not value_bytes:
        return 0.0
    gb = int(value_bytes) / GB_IN_BYTES
    # floor до digits знаков, чтобы остаток не стал отрицательным
    factor = 10 ** digits
    return math.floor(gb * factor) / factor


def format_gb(value_bytes: int | float | None, digits: int = 2) -> str:
    return f"{bytes_to_gb_display(value_bytes, digits):.{digits}f}"


def to_decimal(value) -> Decimal:
    """Конвертация в Decimal для всех денежных вычислений."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_money(value: Decimal | float | int | str, digits: int = 2) -> Decimal:
    """Денежное округление до копеек."""
    q = Decimal("1").scaleb(-digits)
    return to_decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def money_to_str(value: Decimal | float | int | str) -> str:
    return f"{round_money(value):.2f}"


def compute_reset_date(base: datetime, months: int = 1) -> datetime:
    """Индивидуальная дата reset: через месяц от base, день стремится к исходному.

    Для дней 29-31 в коротком месяце — последний день месяца (допущение 3).
    """
    y, m, d = base.year, base.month, base.day
    total = y * 12 + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    # последний день целевого месяца
    if nm == 12:
        last_day = 31
    else:
        last_day = (datetime(ny if nm < 12 else ny + 1, nm + 1 if nm < 12 else 1, 1) - timedelta(days=1)).day
    nd = min(d, last_day)
    result = base.replace(year=ny, month=nm, day=nd)
    return result


def next_reset_date(last_reset: datetime | str) -> datetime:
    """Следующая дата reset от последней выдачи/продления."""
    if isinstance(last_reset, str):
        last_reset = datetime.fromisoformat(last_reset.replace("Z", "+00:00"))
    if last_reset.tzinfo is None:
        last_reset = last_reset.replace(tzinfo=MSK_TZ)
    now = get_msk_time()
    candidate = compute_reset_date(last_reset, months=1)
    # если пропущено несколько периодов — догоняем по одному
    while candidate <= now:
        candidate = compute_reset_date(candidate, months=1)
    return candidate


def missing_reset_dates(last_reset: datetime, until: datetime | None = None) -> list[datetime]:
    """Все пропущенные reset-даты по возрастанию от last_reset до until (включительно)."""
    if isinstance(last_reset, str):
        last_reset = datetime.fromisoformat(last_reset.replace("Z", "+00:00"))
    if last_reset.tzinfo is None:
        last_reset = last_reset.replace(tzinfo=MSK_TZ)
    end = until or get_msk_time()
    if end.tzinfo is None:
        end = end.replace(tzinfo=MSK_TZ)
    dates: list[datetime] = []
    cursor = last_reset
    while True:
        nxt = compute_reset_date(cursor, months=1)
        if nxt > end:
            break
        dates.append(nxt)
        cursor = nxt
    return dates


def parse_iso_or_none(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
