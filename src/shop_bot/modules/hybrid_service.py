"""Сервис гибридных пар (Этап 2 ТЗ).

saga: последовательное создание primary + hybrid в Remnawave с компенсационным
удалением primary при неудаче второго. Инварианты: один telegramId у обоих,
wifi -> primary, lte -> hybrid, пользователю показывается только primary URL.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from shop_bot.data_manager import remnawave_repository as rw_repo
from shop_bot.data_manager import traffic_repository as tr_repo
from shop_bot.modules import remnawave_api
from shop_bot.modules import utils_common as uc
from shop_bot.modules import domain_constants as const

logger = logging.getLogger(__name__)

# Допущение 2: отдельный безопасный домен для email гибрида
HYBRID_EMAIL_MARKER = "hybrid"
HYBRID_EMAIL_DOMAIN = "hybrid.bot.local"

SUFFIX_RE = re.compile(r"^[A-Za-z0-9_]+$")
USERNAME_ALLOWED_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_USERNAME_LEN = 36


class InvalidSuffixError(ValueError):
    """Неверная конфигурация suffix гибрида."""


class HybridCreationError(RuntimeError):
    """Ошибка создания гибридной пары (после saga rollback)."""


def validate_suffix(suffix: str | None) -> str:
    """Валидация suffix: [A-Za-z0-9_]+, длина 1-20, итог <= 36 символов."""
    s = (suffix or "").strip()
    if not s:
        raise InvalidSuffixError("suffix обязателен при включённом гибриде")
    if not (1 <= len(s) <= 20):
        raise InvalidSuffixError("suffix должен иметь длину 1-20")
    if not SUFFIX_RE.match(s):
        raise InvalidSuffixError("suffix может содержать только латиницу, цифры и _")
    return s


def build_remnawave_usernames(telegram_username: str | None, telegram_id: int,
                              suffix: str | None) -> tuple[str, str]:
    """Детерминированные primary/hybrid usernames (Этап 2, п.2).

    - латиница, цифры, _, -
    - Telegram username только если валиден и base+suffix <= 36
    - иначе user_{telegram_id}
    - user_{id}+suffix > 36 -> InvalidSuffixError (не обрезаем молча)
    """
    suffix_v = validate_suffix(suffix)

    base: str | None = None
    raw = (telegram_username or "").strip()
    if raw:
        candidate = re.sub(r"[^A-Za-z0-9_\-]", "_", raw).strip("_-")
        if candidate and USERNAME_ALLOWED_RE.match(candidate) and len(candidate) + len(suffix_v) <= MAX_USERNAME_LEN:
            base = candidate
    if not base:
        fallback = f"user_{telegram_id}"
        if len(fallback) + len(suffix_v) > MAX_USERNAME_LEN:
            raise InvalidSuffixError(
                f"suffix '{suffix_v}' слишком длинный: user id + suffix превышает {MAX_USERNAME_LEN}")
        base = fallback

    return base, base + suffix_v


def hybrid_enabled_for_host(host_name: str) -> bool:
    host = tr_repo.get_host_hybrid_settings(host_name)
    return bool(host and int(host.get("hybrid_enabled") or 0) == 1)


def build_hybrid_email(base_username: str) -> str:
    return f"{base_username}_{HYBRID_EMAIL_MARKER}@{HYBRID_EMAIL_DOMAIN}"


async def is_host_available(host_name: str) -> bool:
    """health-check хоста перед критической операцией (Этап 2, п.1)."""
    try:
        await remnawave_api._request_for_host(host_name, "GET", "/api/users", params={"page": 0, "size": 1})
        return True
    except Exception as exc:
        logger.warning("hybrid_service: health-check хоста %s не прошёл: %s", host_name, exc)
        return False


async def _create_panel_user(
    *,
    host_name: str,
    email: str,
    username: str,
    squad_uuid: str,
    expire_at,
    traffic_limit_bytes: int | None,
    traffic_limit_strategy: str | None,
    telegram_id: int,
    hwid_limit: int | None,
    tag: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Создание panel user с обязательной проверкой telegramId в ответе."""
    payload = await remnawave_api.ensure_user(
        host_name=host_name,
        email=email,
        squad_uuid=squad_uuid,
        expire_at=expire_at,
        traffic_limit_bytes=traffic_limit_bytes,
        traffic_limit_strategy=traffic_limit_strategy,
        description=description,
        tag=tag,
        username=username,
        telegram_id=telegram_id,
        force_expiry=True,
        hwid_limit=hwid_limit,
    )
    remote_tg = payload.get("telegramId")
    if remote_tg is None or int(remote_tg) != int(telegram_id):
        raise HybridCreationError(
            f"Remnawave вернул telegramId={remote_tg}, ожидался {telegram_id} для {email}")
    return payload


async def create_hybrid_subscription(
    *,
    host_name: str,
    user_id: int,
    telegram_id: int,
    telegram_username: str | None,
    expire_at,
    base_traffic_limit_bytes: int | None,
    hybrid_traffic_limit_bytes: int | None,
    base_hwid_limit: int | None,
    hybrid_hwid_limit: int | None,
    traffic_limit_strategy: str | None,
    primary_email: str,
    tag: str | None = None,
    description: str | None = None,
) -> dict[str, Any] | None:
    """Создать primary + hybrid saga-ой, записать vpn_keys (primary) и пару.

    Возвращает данные primary ключа (payload для record_key) или None при ошибке.
    """
    host = tr_repo.get_host_hybrid_settings(host_name)
    if not host:
        logger.error("hybrid_service: хост %s не найден", host_name)
        return None
    suffix = validate_suffix(host.get("hybrid_suffix"))
    hybrid_squad = (host.get("hybrid_squad_uuid") or "").strip()
    if not hybrid_squad:
        raise InvalidSuffixError("hybrid_squad_uuid не задан при включённом гибриде")

    base_username, hybrid_username = build_remnawave_usernames(telegram_username, telegram_id, suffix)
    hybrid_email = build_hybrid_email(base_username)

    primary_squad = (host.get("squad_uuid") or "").strip()

    # --- primary ---
    primary_payload = await _create_panel_user(
        host_name=host_name, email=primary_email, username=base_username, squad_uuid=primary_squad,
        expire_at=expire_at, traffic_limit_bytes=base_traffic_limit_bytes,
        traffic_limit_strategy=traffic_limit_strategy, telegram_id=telegram_id,
        hwid_limit=base_hwid_limit, tag=tag, description=description,
    )

    # --- hybrid (saga: при ошибке удаляем primary) ---
    try:
        hybrid_payload = await _create_panel_user(
            host_name=host_name, email=hybrid_email, username=hybrid_username, squad_uuid=hybrid_squad,
            expire_at=expire_at, traffic_limit_bytes=hybrid_traffic_limit_bytes,
            traffic_limit_strategy=traffic_limit_strategy, telegram_id=telegram_id,
            hwid_limit=hybrid_hwid_limit, tag=tag, description=description,
        )
    except Exception as exc:
        logger.error("hybrid_service: создание hybrid не удалось (%s); компенсационное удаление primary", exc)
        rollback_ok = False
        try:
            primary_id = primary_payload.get("id")
            rollback_ok = await remnawave_api.delete_user_on_host(host_name, primary_id)
        except Exception as del_exc:
            logger.error("hybrid_service: компенсационное удаление primary не удалось: %s", del_exc)
        if not rollback_ok:
            # repair_required: уведомить админа через журнал операций
            tr_repo.record_traffic_operation(
                idempotency_key=f"hybrid_rollback_failed:{primary_payload.get('id')}",
                operation_type=const.OP_HYBRID_REPAIR, key_id=0, actor_type=const.ACTOR_SYSTEM,
                result=const.OP_RESULT_FAILED, error_text=f"primary {primary_payload.get('id')} остался без hybrid, удаление не удалось",
            )
        raise HybridCreationError(f"hybrid creation failed, primary rollback {'ok' if rollback_ok else 'FAILED'}") from exc

    # --- успех: записать локальные данные ---
    key_id = rw_repo.record_key_from_payload(
        user_id=user_id, payload=dict(primary_payload, host_name=host_name, squad_uuid=primary_squad),
        host_name=host_name, description=description, tag=tag,
    )
    if not key_id:
        logger.error("hybrid_service: не удалось записать primary ключ в БД")
        raise HybridCreationError("failed to record primary key")

    tr_repo.create_pair({
        "primary_key_id": key_id,
        "user_id": user_id,
        "host_name": host_name,
        "telegram_id": telegram_id,
        "base_username": base_username,
        "hybrid_username": hybrid_username,
        "primary_remnawave_user_id": primary_payload.get("id"),
        "hybrid_remnawave_user_id": hybrid_payload.get("id"),
        "primary_email": primary_email,
        "hybrid_email": hybrid_email,
        "primary_squad_uuid": primary_squad,
        "hybrid_squad_uuid": hybrid_squad,
    })

    # carry-строки
    next_reset = uc.next_reset_date(uc.get_msk_time()).strftime("%Y-%m-%d")
    tr_repo.ensure_carry_balance(key_id, const.ROLE_PRIMARY, const.TRAFFIC_TYPE_WIFI, next_reset)
    tr_repo.ensure_carry_balance(key_id, const.ROLE_HYBRID, const.TRAFFIC_TYPE_LTE, next_reset)

    return dict(primary_payload)


# ===== жизненный цикл пары =====

async def extend_pair(pair: dict, expire_at, *, base_traffic_limit_bytes=None,
                      hybrid_traffic_limit_bytes=None) -> bool:
    """Продление обеих сторон до одинакового срока."""
    ok = True
    for email, rid, limit in (
        (pair["primary_email"], pair["primary_remnawave_user_id"], base_traffic_limit_bytes),
        (pair["hybrid_email"], pair["hybrid_remnawave_user_id"], hybrid_traffic_limit_bytes),
    ):
        try:
            payload = {
                "id": int(rid), "status": "ACTIVE",
                "expireAt": remnawave_api._to_iso(expire_at),
                "email": email,
            }
            if limit is not None:
                payload["trafficLimitBytes"] = limit
            await remnawave_api._request_for_host(
                pair["host_name"], "PATCH", "/api/users", json_payload=payload)
        except Exception as exc:
            logger.error("hybrid_service.extend_pair: %s user %s: %s", pair["host_name"], rid, exc)
            ok = False
    if not ok:
        tr_repo.update_pair_status(pair["pair_id"], const.PAIR_REPAIR_REQUIRED, error="extend failed")
    return ok


async def set_pair_status(pair: dict, active: bool) -> bool:
    """Блокировка/разблокировка обеих сторон."""
    ok = True
    for rid in (pair["primary_remnawave_user_id"], pair["hybrid_remnawave_user_id"]):
        try:
            action = "enable" if active else "disable"
            await remnawave_api._request_for_host(
                pair["host_name"], "POST", f"/api/users/{rid}/actions/{action}")
        except Exception as exc:
            logger.error("hybrid_service.set_pair_status: %s: %s", rid, exc)
            ok = False
    return ok


async def delete_pair_users(pair: dict) -> bool:
    """Удаление обоих пользователей пары из панели."""
    ok = True
    for rid in (pair["primary_remnawave_user_id"], pair["hybrid_remnawave_user_id"]):
        try:
            await remnawave_api.delete_user_on_host(pair["host_name"], rid)
        except Exception as exc:
            logger.error("hybrid_service.delete_pair_users: %s: %s", rid, exc)
            ok = False
    tr_repo.update_pair_status(pair["pair_id"], const.PAIR_DELETED)
    return ok


async def repair_pair(pair: dict, *, expire_at=None, base_traffic_limit_bytes=None,
                      hybrid_traffic_limit_bytes=None, telegram_id=None,
                      base_hwid_limit=None, hybrid_hwid_limit=None,
                      traffic_limit_strategy=None) -> bool:
    """Восстановление отсутствующей стороны пары из сохранённых параметров."""
    host = tr_repo.get_host_hybrid_settings(pair["host_name"])
    if not host:
        return False
    telegram_id = telegram_id or pair["telegram_id"]
    try:
        # проверяем, какие стороны живы
        primary_alive = await remnawave_api.get_user_by_id(pair["primary_remnawave_user_id"], host_name=pair["host_name"])
        hybrid_alive = await remnawave_api.get_user_by_id(pair["hybrid_remnawave_user_id"], host_name=pair["host_name"])

        if primary_alive is None:
            # восстановить primary
            await _create_panel_user(
                host_name=pair["host_name"], email=pair["primary_email"],
                username=pair["base_username"], squad_uuid=pair["primary_squad_uuid"],
                expire_at=expire_at or uc.get_msk_time(), traffic_limit_bytes=base_traffic_limit_bytes,
                traffic_limit_strategy=traffic_limit_strategy, telegram_id=telegram_id,
                hwid_limit=base_hwid_limit,
            )
        if hybrid_alive is None:
            await _create_panel_user(
                host_name=pair["host_name"], email=pair["hybrid_email"],
                username=pair["hybrid_username"], squad_uuid=pair["hybrid_squad_uuid"],
                expire_at=expire_at or uc.get_msk_time(), traffic_limit_bytes=hybrid_traffic_limit_bytes,
                traffic_limit_strategy=traffic_limit_strategy, telegram_id=telegram_id,
                hwid_limit=hybrid_hwid_limit,
            )
        tr_repo.update_pair_status(pair["pair_id"], const.PAIR_ACTIVE)
        tr_repo.mark_pair_sync(pair["pair_id"], True)
        tr_repo.record_traffic_operation(
            idempotency_key=f"hybrid_repair:{pair['pair_id']}:{uc.today_date_str()}",
            operation_type=const.OP_HYBRID_REPAIR, key_id=pair["primary_key_id"],
            pair_id=pair["pair_id"], actor_type=const.ACTOR_AUTOMATION, result=const.OP_RESULT_SUCCESS,
        )
        return True
    except Exception as exc:
        logger.error("hybrid_service.repair_pair: %s", exc)
        tr_repo.mark_pair_sync(pair["pair_id"], False, error=str(exc))
        return False


async def detach_pair_manually(pair: dict, detached_by: int, *, transfer_carry_to_wifi: bool) -> bool:
    """Ручной разрыв: удалить hybrid, опционально перенести LTE carry -> WiFi carry."""
    try:
        await remnawave_api.delete_user_on_host(pair["host_name"], pair["hybrid_remnawave_user_id"])
    except Exception as exc:
        logger.error("hybrid_service.detach: удаление hybrid не удалось: %s", exc)
        return False

    lte_balance = tr_repo.get_carry_balance(pair["primary_key_id"], const.ROLE_HYBRID, const.TRAFFIC_TYPE_LTE)
    if lte_balance and int(lte_balance.get("remaining_gb") or 0) > 0:
        if transfer_carry_to_wifi:
            tr_repo.add_carry_gb(pair["primary_key_id"], const.ROLE_PRIMARY, const.TRAFFIC_TYPE_WIFI,
                                 int(lte_balance["remaining_gb"]))
        # история не переписывается; LTE carry обнуляется (per договорённости)
        tr_repo.zero_carry_gb(pair["primary_key_id"], const.ROLE_HYBRID, const.TRAFFIC_TYPE_LTE)

    tr_repo.detach_pair(pair["pair_id"], detached_by)
    tr_repo.record_traffic_operation(
        idempotency_key=f"pair_detach:{pair['pair_id']}:{uc.today_date_str()}",
        operation_type=const.OP_MANUAL_ADJUSTMENT, key_id=pair["primary_key_id"],
        pair_id=pair["pair_id"], actor_type=const.ACTOR_ADMIN, actor_id=detached_by,
        gb_delta=0, result=const.OP_RESULT_SUCCESS,
        details={"transfer_carry_to_wifi": transfer_carry_to_wifi,
                 "lte_carry_gb": int((lte_balance or {}).get("remaining_gb") or 0)},
    )
    return True


async def move_pair_squads(pair: dict, primary_squad: str, hybrid_squad: str) -> bool:
    """Перевод обеих сторон на новые squads при смене конфигурации."""
    ok = True
    for rid, squad in ((pair["primary_remnawave_user_id"], primary_squad),
                       (pair["hybrid_remnawave_user_id"], hybrid_squad)):
        try:
            await remnawave_api._request_for_host(
                pair["host_name"], "PATCH", "/api/users",
                json_payload={"id": int(rid), "activeInternalSquads": [squad]})
        except Exception as exc:
            logger.error("hybrid_service.move_pair_squads: %s: %s", rid, exc)
            ok = False
    return ok


async def delete_hwid_for_key(key_id: int, hwid: str) -> dict:
    """Удаление HWID у primary и (если пара есть) hybrid. Возвращает результат сторон."""
    key = rw_repo.get_key_by_id(key_id)
    if not key or not key.get("host_name"):
        return {"primary": False, "hybrid": None}
    host_name = key["host_name"]
    result: dict[str, Any] = {"primary": False, "hybrid": None}
    try:
        result["primary"] = await remnawave_api.delete_user_device(
            key.get("remnawave_user_uuid") or key.get("xui_client_uuid"), hwid, host_name=host_name)
    except Exception as exc:
        logger.error("delete_hwid_for_key primary: %s", exc)

    pair = tr_repo.get_pair_by_primary_key(key_id)
    if pair and pair.get("status") == const.PAIR_ACTIVE:
        try:
            result["hybrid"] = await remnawave_api.delete_user_device(
                pair["hybrid_remnawave_user_id"], hwid, host_name=host_name)
        except Exception as exc:
            logger.error("delete_hwid_for_key hybrid: %s", exc)
        # фиксируем рассинхронизацию аудитом
        if result["primary"] != result["hybrid"]:
            tr_repo.record_traffic_operation(
                idempotency_key=f"hwid_mismatch:{key_id}:{hwid}:{uc.today_date_str()}",
                operation_type=const.OP_HWID_SYNC, key_id=key_id, pair_id=pair["pair_id"],
                actor_type=const.ACTOR_AUTOMATION, result=const.OP_RESULT_FAILED,
                error_text=f"hwid delete mismatch primary={result['primary']} hybrid={result['hybrid']}",
            )
    return result


async def get_pair_traffic_info(pair: dict) -> dict:
    """Статистика WiFi/LTE для карточки ключа: limit/used/remaining по сторонам."""
    from shop_bot.modules import traffic_service
    return await traffic_service.get_key_traffic_stats(pair["primary_key_id"])
