"""Сервис докупки WiFi/LTE трафика (Этап 4 ТЗ).

Единственные публичные операции: доступные типы, target по wifi/lte, расчёт цены,
создание purchase, проверка перед оплатой, применение после оплаты, ручная
корректировка, пересчёт лимита после reset, пользовательская статистика.
Идемпотентность: условные переходы статусов + idempotency_key в traffic_operations.
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta
from decimal import Decimal
from typing import Any

from shop_bot.data_manager import remnawave_repository as rw_repo
from shop_bot.data_manager import traffic_repository as tr_repo
from shop_bot.modules import remnawave_api
from shop_bot.modules import utils_common as uc
from shop_bot.modules import domain_constants as const

logger = logging.getLogger(__name__)

GB_MIN, GB_MAX = 1, 1000


class TrafficPurchaseError(ValueError):
    """Ошибка валидации параметров покупки."""


# =====================================================================
# Доступность и target
# =====================================================================

def available_traffic_types(key_id: int) -> list[str]:
    """Доступные типы докупки для ключа (инварианты 3.2.2-3.2.4)."""
    key = rw_repo.get_key_by_id(key_id)
    if not key or not key.get("host_name"):
        return []
    host = tr_repo.get_host_hybrid_settings(key["host_name"])
    if not host or int(host.get("traffic_purchase_enabled") or 0) != 1:
        return []

    types: list[str] = []
    if int(host.get("hybrid_wifi_enabled") or 1) == 1:
        types.append(const.TRAFFIC_TYPE_WIFI)
    if int(host.get("hybrid_lte_enabled") or 1) == 1 and int(host.get("hybrid_enabled") or 0) == 1:
        pair = tr_repo.get_pair_by_primary_key(key_id)
        if pair and pair.get("status") == const.PAIR_ACTIVE:
            types.append(const.TRAFFIC_TYPE_LTE)
    return types


def resolve_target(key_id: int, traffic_type: str) -> dict | None:
    """target пользователь по wifi/lte: wifi->primary, lte->hybrid."""
    if traffic_type not in const.TRAFFIC_TYPES:
        return None
    key = rw_repo.get_key_by_id(key_id)
    if not key:
        return None
    if traffic_type == const.TRAFFIC_TYPE_WIFI:
        return {
            "role": const.ROLE_PRIMARY,
            "remnawave_user_id": key.get("remnawave_user_uuid") or key.get("xui_client_uuid"),
            "host_name": key.get("host_name"),
        }
    pair = tr_repo.get_pair_by_primary_key(key_id)
    if not pair or pair.get("status") != const.PAIR_ACTIVE:
        return None
    return {
        "role": const.ROLE_HYBRID,
        "remnawave_user_id": pair["hybrid_remnawave_user_id"],
        "host_name": pair["host_name"],
    }


# =====================================================================
# Расчёт цены
# =====================================================================

def _price_per_gb(host: dict, traffic_type: str, non_burnable: bool) -> Decimal | None:
    field = f"{traffic_type}_{'non_' if non_burnable else ''}burnable_price_per_gb"
    value = host.get(field)
    if value is None or str(value).strip() == "":
        return None
    return uc.to_decimal(value)


def calculate_price(*, host_name: str, traffic_type: str, gb_amount: int,
                    non_burnable: bool, package: dict | None = None,
                    referral_discount_percent: Decimal = Decimal("0"),
                    referral_discount_applies: bool = False) -> dict:
    """Расчёт цены с фиксацией всех параметров до оплаты (Этап 4, п.2)."""
    if traffic_type not in const.TRAFFIC_TYPES:
        raise TrafficPurchaseError("invalid traffic_type")
    gb = int(gb_amount)
    if not (GB_MIN <= gb <= GB_MAX):
        raise TrafficPurchaseError(f"gb_amount must be {GB_MIN}..{GB_MAX}")

    host = tr_repo.get_host_hybrid_settings(host_name)
    if not host:
        raise TrafficPurchaseError("host not found")

    if package:
        if package.get("traffic_type") != traffic_type or package.get("host_name") != host_name:
            raise TrafficPurchaseError("package mismatch")
        if int(package.get("gb_amount") or 0) != gb:
            raise TrafficPurchaseError("package gb mismatch")
        total = uc.to_decimal(package.get("price_rub"))
        unit = total / gb
    else:
        unit = _price_per_gb(host, traffic_type, non_burnable)
        if unit is None or unit <= 0:
            raise TrafficPurchaseError(f"цена за 1 ГБ для {traffic_type} не настроена")
        total = uc.round_money(unit * gb)

    discount = Decimal("0")
    if referral_discount_applies and referral_discount_percent > 0:
        discount = uc.round_money(total * referral_discount_percent / 100)
    payable = uc.round_money(max(Decimal("0"), total - discount))

    return {
        "unit_price_rub": unit,
        "total_price_rub": total,
        "discount_rub": discount,
        "payable_rub": payable,
    }


# =====================================================================
# Предоплатные проверки и создание purchase
# =====================================================================

async def validate_before_payment(*, user_id: int, key_id: int, traffic_type: str,
                                  gb_amount: int, non_burnable: bool) -> dict:
    """Проверки перед созданием внешнего счёта (Этап 4, п.3)."""
    key = rw_repo.get_key_by_id(key_id)
    if not key:
        raise TrafficPurchaseError("ключ не найден")
    if int(key.get("user_id") or 0) != int(user_id):
        raise TrafficPurchaseError("ключ не принадлежит пользователю")

    expire = uc.parse_iso_or_none(key.get("expire_at") or key.get("expiry_date"))
    if expire:
        # БД хранит naive datetime; get_msk_time() — aware. Нормализуем.
        if expire.tzinfo is None:
            expire = expire.replace(tzinfo=uc.MSK_TZ)
        if expire <= uc.get_msk_time():
            raise TrafficPurchaseError("подписка истекла")

    host = tr_repo.get_host_hybrid_settings(key["host_name"])
    if not host or int(host.get("traffic_purchase_enabled") or 0) != 1:
        raise TrafficPurchaseError("докупка трафика на этом сервере недоступна")
    if traffic_type not in available_traffic_types(key_id):
        raise TrafficPurchaseError("этот тип трафика недоступен для этой подписки")

    target = resolve_target(key_id, traffic_type)
    if not target or not target.get("remnawave_user_id"):
        raise TrafficPurchaseError("не найден получатель трафика")

    usage = await remnawave_api.get_user_traffic_usage(
        target["remnawave_user_id"], host_name=target["host_name"])
    if usage is None:
        raise TrafficPurchaseError("не удалось прочитать данные пользователя из панели")

    return {"key": key, "host": host, "target": target, "usage": usage}


def create_purchase_draft(*, payment_id: str, user_id: int, key_id: int, traffic_type: str,
                          gb_amount: int, non_burnable: bool, source_kind: str,
                          package: dict | None = None, pricing: dict) -> int | None:
    """Атомарное создание purchase со зафиксированной ценой до оплаты."""
    logger.info("TRAFFIC purchase draft: payment=%s user=%s key=%s type=%s gb=%s burnable=%s price=%s",
                payment_id, user_id, key_id, traffic_type, gb_amount,
                "non" if non_burnable else "burn", pricing.get("payable_rub"))
    target = resolve_target(key_id, traffic_type)
    if not target:
        raise TrafficPurchaseError("не найден получатель трафика")
    pair = tr_repo.get_pair_by_primary_key(key_id)
    key = rw_repo.get_key_by_id(key_id)

    purchase_id = tr_repo.create_traffic_purchase({
        "payment_id": payment_id,
        "user_id": user_id,
        "key_id": key_id,
        "pair_id": pair["pair_id"] if pair else None,
        "host_name": key["host_name"],
        "target_role": target["role"],
        "target_remnawave_user_id": target["remnawave_user_id"],
        "traffic_type": traffic_type,
        "gb_amount": int(gb_amount),
        "is_non_burnable": bool(non_burnable),
        "source_kind": source_kind,
        "package_id": package.get("package_id") if package else None,
        "unit_price_rub": pricing.get("unit_price_rub"),
        "total_price_rub": pricing["payable_rub"],
        "discount_rub": pricing.get("discount_rub", 0),
    })
    return purchase_id


# =====================================================================
# Fulfillment: применение после оплаты
# =====================================================================

async def fulfill_traffic_purchase(bot, metadata: dict) -> bool:
    """Применение оплаченной докупки: увеличить лимит, обновить carry, аудит.

    Идемпотентно: условный переход purchase paid/fulfilling -> fulfilling
    гарантирует единственное применение даже при повторном job/retry.
    """
    payment_id = str(metadata.get("payment_id") or "")
    logger.info("TRAFFIC fulfill: payment=%s", payment_id)
    purchase = tr_repo.get_traffic_purchase(payment_id)
    if not purchase:
        logger.error("traffic_service: purchase для %s не найден", payment_id)
        return False

    if purchase["status"] == const.PURCHASE_FULFILLED:
        return True  # уже применено (дубль)

    # блокируем purchase для исполнения
    if not tr_repo.transition_purchase_status(
            payment_id,
            (const.PURCHASE_PAID, const.PURCHASE_PAYMENT_PENDING, const.PURCHASE_CREATED,
             const.PURCHASE_RETRYABLE_FAILURE),
            const.PURCHASE_FULFILLING,
            extra_sets={"paid_at": purchase.get("paid_at") or uc.now_str()}):
        # другой обработчик выиграл гонку
        current = tr_repo.get_traffic_purchase(payment_id)
        return bool(current and current["status"] == const.PURCHASE_FULFILLED)

    key_id = int(purchase["key_id"])
    gb = int(purchase["gb_amount"])
    traffic_type = purchase["traffic_type"]
    role = purchase["target_role"]
    target_uid = purchase["target_remnawave_user_id"]
    host_name = purchase["host_name"]

    try:
        usage = await remnawave_api.get_user_traffic_usage(target_uid, host_name=host_name)
        if usage is None:
            raise RuntimeError(f"target user {target_uid} not found in panel")
        current_limit = int(usage.get("limit_bytes") or 0)
        new_limit = current_limit + uc.gb_to_bytes(gb)
        ok = await remnawave_api.update_user_traffic_limit(
            target_uid, new_limit, host_name=host_name)
        if not ok:
            raise RuntimeError("failed to update trafficLimitBytes")

        # несгораемая покупка: carry в одной SQLite-транзакции
        if int(purchase["is_non_burnable"] or 0) == 1:
            balance = tr_repo.get_carry_balance(key_id, role, traffic_type)
            next_reset = (uc.get_msk_time() + timedelta(days=31)).strftime("%Y-%m-%d")
            if balance:
                tr_repo.add_carry_gb(key_id, role, traffic_type, gb)
            else:
                tr_repo.ensure_carry_balance(key_id, role, traffic_type, next_reset)
                tr_repo.add_carry_gb(key_id, role, traffic_type, gb)

        tr_repo.record_traffic_operation(
            idempotency_key=f"purchase_credit:{payment_id}",
            operation_type=const.OP_PURCHASE_CREDIT,
            purchase_id=purchase["purchase_id"], key_id=key_id,
            pair_id=purchase.get("pair_id"), target_role=role,
            target_remnawave_user_id=target_uid, traffic_type=traffic_type,
            gb_delta=gb, is_non_burnable=int(purchase["is_non_burnable"] or 0),
            actor_type=const.ACTOR_USER, actor_id=int(purchase["user_id"]),
            result=const.OP_RESULT_SUCCESS,
            details={"new_limit_bytes": new_limit},
        )
        tr_repo.transition_purchase_status(
            payment_id, (const.PURCHASE_FULFILLING,), const.PURCHASE_FULFILLED,
            extra_sets={"fulfilled_at": uc.now_str()})
        logger.info("TRAFFIC fulfill: payment=%s OK — +%d GB %s → user %s (new_limit=%d bytes, carry=%s)",
                     payment_id, gb, traffic_type, purchase["user_id"], new_limit,
                     "updated" if int(purchase["is_non_burnable"] or 0) else "burnable")

        # уведомление пользователя
        try:
            uid = int(purchase["user_id"])
            if bot and uid and not str(uid).startswith("999"):
                host = tr_repo.get_host_hybrid_settings(host_name) or {}
                name = (host.get(f"{traffic_type}_traffic_name") or traffic_type)
                await bot.send_message(
                    uid, f"✅ <b>Трафик начислен</b>\n{name}: +{gb} ГБ\n"
                         f"Подписка активна, остаток обновлён.", parse_mode="HTML")
        except Exception:
            pass

        # реферальная ГБ-награда (Этап 6)
        try:
            await process_referral_traffic_reward(bot, purchase)
        except Exception:
            logger.exception("traffic_service: ошибка реферальной ГБ-награды для %s", payment_id)

        return True
    except Exception as exc:
        logger.error("traffic_service: ошибка применения докупки %s: %s", payment_id, exc)
        tr_repo.transition_purchase_status(
            payment_id, (const.PURCHASE_FULFILLING,), const.PURCHASE_RETRYABLE_FAILURE)
        tr_repo.increment_purchase_attempt(payment_id, str(exc))
        tr_repo.record_traffic_operation(
            idempotency_key=f"purchase_credit:{payment_id}:fail:{int((purchase.get('sync_attempts') or 0) + 1)}",
            operation_type=const.OP_PURCHASE_CREDIT,
            purchase_id=purchase["purchase_id"], key_id=key_id,
            pair_id=purchase.get("pair_id"), target_role=role,
            target_remnawave_user_id=target_uid, traffic_type=traffic_type,
            gb_delta=gb, actor_type=const.ACTOR_USER, actor_id=int(purchase["user_id"]),
            result=const.OP_RESULT_FAILED, error_text=str(exc)[:500],
        )
        return False


# =====================================================================
# Referral GB reward (Этап 6 ТЗ)
# =====================================================================

async def process_referral_traffic_reward(bot, purchase: dict) -> None:
    """ГБ-награда рефереру за докупку трафика рефералом."""
    enabled = (rw_repo.get_setting("referral_traffic_purchases_enabled") or "0").strip() == "1"
    if not enabled:
        return

    buyer = rw_repo.get_user(int(purchase["user_id"])) or {}
    ref_id = buyer.get("referred_by")
    if not ref_id:
        return
    referrer = rw_repo.get_user(int(ref_id))
    if not referrer or referrer.get("is_banned"):
        return

    # процентная ставка (fixed не конвертируется в ГБ)
    percent = uc.to_decimal(rw_repo.get_setting("referral_percentage") or "0")
    if percent <= 0:
        return

    gb = int(purchase["gb_amount"])
    raw_gb = gb * percent / 100
    reward_gb = max(1, math.ceil(raw_gb))
    traffic_type = purchase["traffic_type"]
    non_burnable = bool(int(purchase["is_non_burnable"] or 0))

    # подходящая активная подписка реферера (допущение 6)
    recipient = _find_referral_recipient(int(ref_id), purchase["host_name"], traffic_type)
    if not recipient:
        tr_repo.create_referral_reward({
            "source_purchase_id": purchase["purchase_id"],
            "referrer_user_id": int(ref_id),
            "recipient_key_id": 0,
            "traffic_type": traffic_type,
            "target_role": const.role_for_traffic_type(traffic_type),
            "gb_amount": reward_gb,
            "is_non_burnable": non_burnable,
            "percent_snapshot": percent,
            "status": const.REWARD_MANUAL_REVIEW,
        })
        await _notify_admins_manual_review(bot, purchase, ref_id, reward_gb)
        return

    role = const.role_for_traffic_type(traffic_type)
    reward_id = tr_repo.create_referral_reward({
        "source_purchase_id": purchase["purchase_id"],
        "referrer_user_id": int(ref_id),
        "recipient_key_id": recipient["key_id"],
        "traffic_type": traffic_type,
        "target_role": role,
        "gb_amount": reward_gb,
        "is_non_burnable": non_burnable,
        "percent_snapshot": percent,
        "status": const.REWARD_PENDING,
    })
    if reward_id is None:
        return  # дубликат

    # начисление через общий механизм credit
    ok = await credit_gb(
        key_id=recipient["key_id"], traffic_type=traffic_type, gb=reward_gb,
        non_burnable=non_burnable, operation_type=const.OP_REFERRAL_CREDIT,
        idempotency_key=f"referral_credit:{purchase['purchase_id']}",
        actor_type=const.ACTOR_SYSTEM, actor_id=int(ref_id),
        purchase_id=purchase["purchase_id"],
    )
    tr_repo.update_referral_reward_status(
        reward_id, const.REWARD_FULFILLED if ok else const.REWARD_FAILED)
    if ok:
        try:
            if bot:
                host = tr_repo.get_host_hybrid_settings(purchase["host_name"]) or {}
                name = host.get(f"{traffic_type}_traffic_name") or traffic_type
                await bot.send_message(
                    int(ref_id),
                    f"🎁 <b>Реферальный бонус</b>\nВаш реферал купил трафик.\n"
                    f"Вам начислено: <b>{reward_gb} ГБ</b> ({name})", parse_mode="HTML")
        except Exception:
            pass


def _find_referral_recipient(referrer_user_id: int, host_name: str, traffic_type: str) -> dict | None:
    """Активный ключ реферера: expire_at DESC, key_id ASC (допущение 6)."""
    with_prefix = "SELECT key_id, remnawave_user_uuid, expire_at FROM vpn_keys WHERE user_id = ? AND host_name = ?"
    rows = []
    from shop_bot.data_manager import database as db
    raw = db._fetch_list(
        with_prefix + " ORDER BY datetime(expire_at) DESC, key_id ASC",
        (referrer_user_id, host_name), "")
    now = uc.get_msk_time().replace(tzinfo=None)
    for row in raw:
        expire = uc.parse_iso_or_none(row.get("expire_at"))
        if expire is None or expire <= now:
            continue
        rows.append(row)
    if not rows:
        return None
    if traffic_type == const.TRAFFIC_TYPE_LTE:
        for row in rows:
            pair = tr_repo.get_pair_by_primary_key(row["key_id"])
            if pair and pair.get("status") == const.PAIR_ACTIVE:
                return {"key_id": row["key_id"],
                        "remnawave_user_id": pair["hybrid_remnawave_user_id"]}
        return None
    return {"key_id": rows[0]["key_id"], "remnawave_user_id": rows[0].get("remnawave_user_uuid")}


async def _notify_admins_manual_review(bot, purchase: dict, ref_id: int, reward_gb: int) -> None:
    try:
        admin_ids = list(rw_repo.get_admin_ids() or [])
    except Exception:
        admin_ids = []
    text = (f"⚠️ <b>Реферальная ГБ-награда: manual review</b>\n"
            f"Реферер <code>{ref_id}</code> не имеет подходящей активной подписки "
            f"(host <code>{purchase['host_name']}</code>, тип {purchase['traffic_type']}). "
            f"Награда {reward_gb} ГБ сохранена и требует ручной обработки.")
    for admin_id in admin_ids:
        try:
            await bot.send_message(int(admin_id), text, parse_mode="HTML")
        except Exception:
            continue


# =====================================================================
# Общее начисление (используется покупками, рефералкой, ручной корректировкой)
# =====================================================================

async def credit_gb(*, key_id: int, traffic_type: str, gb: int, non_burnable: bool,
                    operation_type: str, idempotency_key: str, actor_type: str,
                    actor_id: int | None = None, purchase_id: int | None = None,
                    allow_negative: bool = False) -> bool:
    """Начислить/списать ГБ через Remnawave с аудитом и carry. gb<0 — списание."""
    gb = int(gb)
    target = resolve_target(key_id, traffic_type)
    if not target:
        return False
    if gb < 0 and not allow_negative:
        return False

    if tr_repo.operation_exists(idempotency_key):
        return True  # уже применено

    role = target["role"]
    try:
        usage = await remnawave_api.get_user_traffic_usage(
            target["remnawave_user_id"], host_name=target["host_name"])
        if usage is None:
            raise RuntimeError("target user not found")
        current_limit = int(usage.get("limit_bytes") or 0)
        new_limit = max(0, current_limit + uc.gb_to_bytes(gb))
        ok = await remnawave_api.update_user_traffic_limit(
            target["remnawave_user_id"], new_limit, host_name=target["host_name"])
        if not ok:
            raise RuntimeError("failed to update limit")

        if non_burnable and gb > 0:
            balance = tr_repo.get_carry_balance(key_id, role, traffic_type)
            next_reset = (uc.get_msk_time() + timedelta(days=31)).strftime("%Y-%m-%d")
            if not balance:
                tr_repo.ensure_carry_balance(key_id, role, traffic_type, next_reset)
            tr_repo.add_carry_gb(key_id, role, traffic_type, gb)
        elif non_burnable and gb < 0:
            tr_repo.add_carry_gb(key_id, role, traffic_type, max(0, gb))  # списание carry не ниже 0
            # для списания уменьшаем carry напрямую ниже
            bal = tr_repo.get_carry_balance(key_id, role, traffic_type)
            if bal:
                new_remaining = max(0, int(bal["remaining_gb"]) + gb)
                tr_repo.set_carry_state(key_id, role, traffic_type, new_remaining,
                                        bal.get("last_reset_date"), bal.get("next_reset_date"))

        tr_repo.record_traffic_operation(
            idempotency_key=idempotency_key, operation_type=operation_type,
            purchase_id=purchase_id, key_id=key_id, target_role=role,
            target_remnawave_user_id=str(target["remnawave_user_id"]),
            traffic_type=traffic_type, gb_delta=gb,
            is_non_burnable=1 if non_burnable else 0,
            actor_type=actor_type, actor_id=actor_id,
            result=const.OP_RESULT_SUCCESS,
            details={"new_limit_bytes": new_limit},
        )
        return True
    except Exception as exc:
        logger.error("traffic_service.credit_gb %s: %s", idempotency_key, exc)
        tr_repo.record_traffic_operation(
            idempotency_key=f"{idempotency_key}:fail", operation_type=operation_type,
            purchase_id=purchase_id, key_id=key_id, target_role=role,
            traffic_type=traffic_type, gb_delta=gb,
            actor_type=actor_type, actor_id=actor_id,
            result=const.OP_RESULT_FAILED, error_text=str(exc)[:500],
        )
        return False


async def manual_adjustment(*, key_id: int, traffic_type: str, gb: int, non_burnable: bool,
                            admin_id: int, reason: str) -> bool:
    """Ручная корректировка админом: обязательная причина, через credit_gb + аудит."""
    if not (reason or "").strip():
        raise TrafficPurchaseError("причина корректировки обязательна")
    op_key = f"manual_adjustment:{key_id}:{traffic_type}:{uc.get_msk_time().strftime('%Y%m%d%H%M%S')}"
    ok = await credit_gb(
        key_id=key_id, traffic_type=traffic_type, gb=gb, non_burnable=non_burnable,
        operation_type=const.OP_MANUAL_ADJUSTMENT, idempotency_key=op_key,
        actor_type=const.ACTOR_ADMIN, actor_id=admin_id, allow_negative=True,
    )
    return ok


# =====================================================================
# Reset / carry / expiry
# =====================================================================

def compute_carry_after(*, base_gb: int, carry_before_gb: int, limit_before_gb: int,
                        used_before_gb: int) -> int:
    """Формула остатка переноса (раздел 9 ТЗ, «Алгоритм вычисления остатка»).

    carry_after = max(0, min(carry_before, limit_before - max(base, used)))
    """
    return max(0, min(carry_before_gb, limit_before_gb - max(base_gb, used_before_gb)))


async def perform_reset(key_id: int, role: str, traffic_type: str, reset_date) -> dict:
    """Индивидуальный reset: свежие usage/limit, пересчёт carry, новый лимит.

    Идемотентность: ключ вида reset:{key}:{role}:{YYYY-MM-DD}.
    """
    reset_date_str = reset_date.strftime("%Y-%m-%d") if hasattr(reset_date, "strftime") else str(reset_date)
    idem_key = f"reset:{key_id}:{role}:{reset_date_str}"
    logger.info("TRAFFIC reset: key=%s role=%s type=%s date=%s", key_id, role, traffic_type, reset_date_str)
    if tr_repo.operation_exists(idem_key):
        logger.info("TRAFFIC reset: key=%s date=%s — уже выполнен (skip)", key_id, reset_date_str)
        return {"skipped": True, "reason": "already reset"}

    target = resolve_target(key_id, traffic_type)
    if not target:
        return {"skipped": True, "reason": "no target"}

    balance = tr_repo.get_carry_balance(key_id, role, traffic_type)
    if not balance:
        return {"skipped": True, "reason": "no balance row"}

    key = rw_repo.get_key_by_id(key_id)
    base_gb = _base_plan_gb(key, role)
    if base_gb is None:
        # не угадываем: manual review (Этап 4, п.7)
        tr_repo.record_traffic_operation(
            idempotency_key=idem_key + ":manual", operation_type=const.OP_MONTHLY_RESET,
            key_id=key_id, target_role=role, traffic_type=traffic_type,
            actor_type=const.ACTOR_AUTOMATION, result=const.OP_RESULT_FAILED,
            error_text="base plan snapshot missing")
        return {"manual_review": True}

    try:
        usage = await remnawave_api.get_user_traffic_usage(
            target["remnawave_user_id"], host_name=target["host_name"])
        if usage is None:
            raise RuntimeError("target user not found")
    except Exception as exc:
        return {"error": str(exc)}

    limit_before_gb = uc.bytes_to_gb_floor(int(usage.get("limit_bytes") or 0))
    # округляем вниз байты до целых ГБ только в момент сохранения carry
    used_before_gb_exact = int(usage.get("used_bytes") or 0) / uc.GB_IN_BYTES
    used_before_gb = int(used_before_gb_exact)

    carry_before_gb = int(balance.get("remaining_gb") or 0)
    carry_after = compute_carry_after(
        base_gb=base_gb, carry_before_gb=carry_before_gb,
        limit_before_gb=limit_before_gb, used_before_gb=used_before_gb)

    new_limit_gb = base_gb + carry_after
    new_limit_bytes = uc.gb_to_bytes(new_limit_gb)

    # проверка несовместимых данных: лимит в панели не может быть меньше базы при carry=0
    if limit_before_gb < base_gb and carry_before_gb == 0:
        tr_repo.record_traffic_operation(
            idempotency_key=idem_key + ":manual", operation_type=const.OP_MONTHLY_RESET,
            key_id=key_id, target_role=role, traffic_type=traffic_type,
            actor_type=const.ACTOR_AUTOMATION, result=const.OP_RESULT_FAILED,
            error_text=f"panel limit {limit_before_gb} < base {base_gb}",
            details={"limit_before_gb": limit_before_gb, "base_gb": base_gb,
                     "used_before_gb": used_before_gb})
        return {"manual_review": True,
                "details": {"limit_before_gb": limit_before_gb, "base_gb": base_gb}}

    try:
        ok = await remnawave_api.update_user_traffic_limit(
            target["remnawave_user_id"], new_limit_bytes, host_name=target["host_name"])
        if not ok:
            raise RuntimeError("failed to set new limit")
    except Exception as exc:
        return {"error": str(exc)}

    next_reset = uc.next_reset_date(reset_date).strftime("%Y-%m-%d")
    tr_repo.set_carry_state(key_id, role, traffic_type, carry_after, reset_date_str, next_reset)
    tr_repo.record_traffic_operation(
        idempotency_key=idem_key, operation_type=const.OP_MONTHLY_RESET,
        key_id=key_id, target_role=role, traffic_type=traffic_type,
        target_remnawave_user_id=str(target["remnawave_user_id"]),
        gb_delta=carry_after - carry_before_gb, actor_type=const.ACTOR_AUTOMATION,
        result=const.OP_RESULT_SUCCESS,
        details={"base_gb": base_gb, "carry_before": carry_before_gb,
                 "carry_after": carry_after, "new_limit_gb": new_limit_gb,
                 "limit_before_gb": limit_before_gb, "used_before_gb": used_before_gb},
    )
    return {"ok": True, "carry_after": carry_after, "new_limit_gb": new_limit_gb}


def _base_plan_gb(key: dict | None, role: str) -> int | None:
    """Базовый лимит тарифа из сохранённого контекста ключа/пары."""
    if not key:
        return None
    limit_bytes = key.get("traffic_limit_bytes")
    if limit_bytes is None:
        return None
    return uc.bytes_to_gb_floor(int(limit_bytes or 0))


async def burn_expired_carry(key_id: int, role: str, traffic_type: str) -> bool:
    """Истечение подписки: несгораемые остатки сгорают (инвариант 3.2.6)."""
    balance = tr_repo.get_carry_balance(key_id, role, traffic_type)
    if not balance or int(balance.get("remaining_gb") or 0) == 0:
        return False
    burned = int(balance["remaining_gb"])
    tr_repo.zero_carry_gb(key_id, role, traffic_type)
    tr_repo.record_traffic_operation(
        idempotency_key=f"expiry_burn:{key_id}:{role}:{uc.today_date_str()}",
        operation_type=const.OP_EXPIRY_BURN, key_id=key_id, target_role=role,
        traffic_type=traffic_type, gb_delta=-burned, actor_type=const.ACTOR_SYSTEM,
        result=const.OP_RESULT_SUCCESS, details={"burned_gb": burned},
    )
    return True


async def run_daily_resets() -> int:
    """Догоняющая обработка reset-дат по возрастанию (Этап 4, «Правило сброса»)."""
    today = uc.today_date_str()
    processed = 0
    for balance in tr_repo.list_due_resets(today):
        key_id = int(balance["key_id"])
        role = balance["target_role"]
        traffic_type = balance["traffic_type"]
        # все пропущенные reset-даты последовательно
        last_reset = uc.parse_iso_or_none(balance.get("last_reset_date")) or uc.get_msk_time()
        for missed in uc.missing_reset_dates(last_reset):
            if missed.strftime("%Y-%m-%d") > today:
                break
            result = await perform_reset(key_id, role, traffic_type, missed)
            if result.get("ok") or result.get("skipped"):
                processed += 1
            if result.get("manual_review"):
                break
    return processed


# =====================================================================
# Пользовательская статистика
# =====================================================================

async def get_key_traffic_stats(key_id: int) -> dict:
    """Статистика трафика ключа для карточки: WiFi и (для гибрида) LTE."""
    key = rw_repo.get_key_by_id(key_id)
    if not key:
        return {"available": False}
    host_name = key.get("host_name")
    host = tr_repo.get_host_hybrid_settings(host_name) if host_name else None
    if not host:
        return {"available": False}

    wifi_name = host.get("wifi_traffic_name") or "WiFi гигабайты"
    lte_name = host.get("lte_traffic_name") or "LTE гигабайты"
    purchase_enabled = int(host.get("traffic_purchase_enabled") or 0) == 1

    stats: dict[str, Any] = {
        "available": True,
        "purchase_enabled": purchase_enabled,
        "wifi_name": wifi_name,
        "lte_name": lte_name,
        "wifi": None,
        "lte": None,
        "total_remaining_gb": 0.0,
        "available_types": available_traffic_types(key_id),
    }

    # WiFi (primary) — только если hybrid_wifi_enabled
    if int(host.get("hybrid_wifi_enabled") or 1) == 1:
        usage = await remnawave_api.get_user_traffic_usage(
            key.get("remnawave_user_uuid") or key.get("xui_client_uuid"), host_name=host_name)
        if usage:
            limit = int(usage.get("limit_bytes") or 0)
            used = int(usage.get("used_bytes") or 0)
            stats["wifi"] = {
                "limit_bytes": limit, "used_bytes": used,
                "remaining_bytes": max(0, limit - used),
                "remaining_gb": uc.bytes_to_gb_display(max(0, limit - used)),
                "limit_gb": uc.bytes_to_gb_display(limit),
                "used_gb": uc.bytes_to_gb_display(used),
            }
            stats["total_remaining_gb"] += uc.bytes_to_gb_display(max(0, limit - used))

    # LTE (hybrid) — только для активной пары, без упоминания гибрида в UI
    pair = tr_repo.get_pair_by_primary_key(key_id)
    if pair and pair.get("status") == const.PAIR_ACTIVE and int(host.get("hybrid_enabled") or 0) == 1 \
            and int(host.get("hybrid_lte_enabled") or 1) == 1:
        usage = await remnawave_api.get_user_traffic_usage(
            pair["hybrid_remnawave_user_id"], host_name=host_name)
        if usage:
            limit = int(usage.get("limit_bytes") or 0)
            used = int(usage.get("used_bytes") or 0)
            stats["lte"] = {
                "limit_bytes": limit, "used_bytes": used,
                "remaining_bytes": max(0, limit - used),
                "remaining_gb": uc.bytes_to_gb_display(max(0, limit - used)),
                "limit_gb": uc.bytes_to_gb_display(limit),
                "used_gb": uc.bytes_to_gb_display(used),
            }
            stats["total_remaining_gb"] += uc.bytes_to_gb_display(max(0, limit - used))

    # переносимые остатки (человеческие строки)
    carry = tr_repo.get_carry_balance(key_id, const.ROLE_PRIMARY, const.TRAFFIC_TYPE_WIFI)
    stats["wifi_carry_gb"] = int((carry or {}).get("remaining_gb") or 0)
    if pair:
        lte_carry = tr_repo.get_carry_balance(key_id, const.ROLE_HYBRID, const.TRAFFIC_TYPE_LTE)
        stats["lte_carry_gb"] = int((lte_carry or {}).get("remaining_gb") or 0)
    return stats
