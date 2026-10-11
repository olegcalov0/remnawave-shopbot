"""Перенос ключей между хостами Remnawave (server migration).

Поддерживаемые сценарии:
- Перенос всех ключей с исходного хоста на целевой.
- Перенос конкретного пользователя (по telegram_id или username) — одна или
  несколько его подписок на исходном хосте.
- При включённом гибриде на целевом хосте — создание hybrid-пользователя и пары.
- Перенос использованного трафика и лимита: базовый лимит целевого хоста
  берётся за основу; если старый лимит больше — излишек становится
  несгораемым carry-балансом; если меньше — лимит повышается до старого.
- Перенос срока действия: expire_at старого ключа переносится на новый.
- Удаление старого ключа из панели Remnawave перед созданием нового.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from shop_bot.data_manager import remnawave_repository as rw_repo
from shop_bot.data_manager import traffic_repository as tr_repo
from shop_bot.modules import remnawave_api
from shop_bot.modules import hybrid_service
from shop_bot.modules import utils_common as uc
from shop_bot.modules import domain_constants as const

logger = logging.getLogger(__name__)

MIGRATION_STATE_KEY = "server_migration_state"
BATCH_SIZE = 10


def get_state() -> dict:
    import json
    raw = rw_repo.get_setting(MIGRATION_STATE_KEY) or "{}"
    try:
        return json.loads(raw)
    except Exception:
        return {"source_host": None, "target_host": None, "mode": "all",
                "telegram_id": None, "key_ids": [], "role": "wifi",
                "offset": 0, "paused": False}


def set_state(state: dict) -> None:
    import json
    rw_repo.update_setting(MIGRATION_STATE_KEY, json.dumps(state))


def start_migration(source_host: str, target_host: str, mode: str = "all",
                     telegram_id: int | None = None,
                     key_ids: list[int] | None = None,
                     role: str = "wifi") -> dict:
    state = {
        "source_host": source_host, "target_host": target_host,
        "mode": mode, "telegram_id": telegram_id,
        "key_ids": key_ids or [], "role": role,
        "offset": 0, "paused": False,
    }
    set_state(state)
    logger.info("SERVER MIGRATION start: %s -> %s mode=%s role=%s",
                source_host, target_host, mode, role)
    return {"started": True, **state}


def pause_migration() -> dict:
    s = get_state()
    s["paused"] = True
    set_state(s)
    return s


def resume_migration() -> dict:
    s = get_state()
    s["paused"] = False
    set_state(s)
    return s


def _collect_target_keys(state: dict) -> list[dict]:
    """Собрать список ключей для переноса с исходного хоста."""
    source = state.get("source_host")
    if not source:
        return []
    all_keys = rw_repo.get_keys_for_host(source) or []
    mode = state.get("mode", "all")
    if mode == "all":
        return all_keys
    elif mode == "user":
        tid = state.get("telegram_id")
        if tid:
            return [k for k in all_keys if int(k.get("user_id") or 0) == int(tid)]
        return []
    elif mode == "specific":
        kid_set = set(int(x) for x in (state.get("key_ids") or []))
        return [k for k in all_keys if int(k.get("key_id") or 0) in kid_set]
    return all_keys


async def _get_traffic_from_panel(host_name: str, remnawave_user_id: str) -> dict:
    """Получить limit/used traffic из панели для пользователя."""
    try:
        user_data = await remnawave_api.get_user_by_id(remnawave_user_id, host_name=host_name)
        if not user_data:
            return {"limit_bytes": 0, "used_bytes": 0}
        return {
            "limit_bytes": int(user_data.get("trafficLimitBytes") or 0),
            "used_bytes": int(user_data.get("usedTrafficBytes") or 0),
        }
    except Exception as exc:
        logger.error("server_migration: get traffic for %s: %s", remnawave_user_id, exc)
        return {"limit_bytes": 0, "used_bytes": 0}


def _get_base_limit_bytes_for_target(target_host: str) -> int:
    """Базовый лимит целевого хоста: из первого тарифа или 0."""
    plans = rw_repo.get_plans_for_host(target_host) or []
    if plans:
        gb = int(plans[0].get("traffic_limit_gb") or 0)
        return uc.gb_to_bytes(gb) if gb else 0
    return 0


async def run_migration_batch() -> dict:
    """Обработать батч ключей для переноса между хостами."""
    state = get_state()
    source = state.get("source_host")
    target = state.get("target_host")
    if not source or not target or state.get("paused"):
        return {"done": False, "reason": "no active migration" if not source else "paused"}

    target_hybrid = tr_repo.get_host_hybrid_settings(target) or {}
    target_hybrid_on = int(target_hybrid.get("hybrid_enabled") or 0) == 1
    role = state.get("role", "wifi")

    keys = _collect_target_keys(state)
    offset = int(state.get("offset") or 0)
    batch = keys[offset:offset + BATCH_SIZE]

    migrated = skipped = errors = 0
    for key in batch:
        key_id = int(key.get("key_id") or 0)
        user_id = int(key.get("user_id") or 0)
        try:
            # 1. Читать данные из панели старого хоста
            old_rw_id = key.get("remnawave_user_uuid") or key.get("xui_client_uuid")
            if not old_rw_id:
                skipped += 1
                continue
            traffic = await _get_traffic_from_panel(source, str(old_rw_id))
            old_limit = traffic["limit_bytes"]
            old_used = traffic["used_bytes"]

            # expire_at старого ключа
            expire_raw = key.get("expire_at") or key.get("expiry_date")
            expire_dt = None
            if expire_raw:
                try:
                    expire_dt = datetime.fromisoformat(str(expire_raw).replace("Z", "+00:00"))
                except Exception:
                    expire_dt = None
            if not expire_dt or expire_dt < uc.get_msk_time():
                expire_dt = uc.get_msk_time() + timedelta(days=30)

            # 2. Удалить старого пользователя из панели
            try:
                await remnawave_api.delete_user_on_host(source, str(old_rw_id))
            except Exception as exc:
                logger.warning("server_migration: delete old user %s: %s", old_rw_id, exc)

            # 3. Вычислить лимит для нового хоста
            target_base = _get_base_limit_bytes_for_target(target)
            new_limit = target_base
            extra_carry_gb = 0
            if old_limit > 0:
                if old_limit > target_base and target_base > 0:
                    # старый лимит больше базы нового хоста: излишек → несгораемый carry
                    new_limit = old_limit
                    extra_bytes = old_limit - target_base
                    extra_carry_gb = uc.bytes_to_gb_floor(extra_bytes)
                elif old_limit > target_base:
                    new_limit = old_limit
                # если old_limit < target_base — лимит повышается до target_base (new_limit уже = target_base)

            # 4. Создать нового пользователя на целевом хосте
            email = key.get("email") or key.get("key_email") or f"user_{user_id}@bot.local"
            user_data = rw_repo.get_user(user_id) or {}
            tg_username = user_data.get("username")

            if target_hybrid_on:
                # гибрид: создать пару
                plan_hybrid_gb = 0
                plan_hybrid_hwid = 0
                plans = rw_repo.get_plans_for_host(target) or []
                if plans:
                    plan_hybrid_gb = int(plans[0].get("hybrid_traffic_limit_gb") or 0)
                    plan_hybrid_hwid = int(plans[0].get("hybrid_hwid_limit") or 0)

                try:
                    payload = await hybrid_service.create_hybrid_subscription(
                        host_name=target, user_id=user_id, telegram_id=user_id,
                        telegram_username=tg_username,
                        expire_at=expire_dt,
                        base_traffic_limit_bytes=new_limit if new_limit > 0 else None,
                        hybrid_traffic_limit_bytes=uc.gb_to_bytes(plan_hybrid_gb) if plan_hybrid_gb else None,
                        base_hwid_limit=None,
                        hybrid_hwid_limit=plan_hybrid_hwid if plan_hybrid_hwid else None,
                        traffic_limit_strategy="NO_RESET",
                        primary_email=email,
                    )
                except hybrid_service.HybridCreationError as exc:
                    logger.error("server_migration: hybrid create failed for key %s: %s", key_id, exc)
                    payload = None
            else:
                # обычный режим
                limit_gb = int(new_limit // (1024**3)) if new_limit > 0 else 0
                payload = await remnawave_api.create_or_update_key_on_host(
                    host_name=target, email=email,
                    days_to_add=max(1, int((expire_dt - uc.get_msk_time()).total_seconds() / 86400)),
                    telegram_id=user_id,
                    traffic_limit_gb=limit_gb if limit_gb > 0 else None,
                    hwid_limit=None,
                )

            if not payload:
                errors += 1
                logger.error("server_migration: payload is None for key %s", key_id)
                continue

            # 5. Обновить vpn_keys: сменить host_name и remnawave_user_uuid
            new_rw_id = payload.get("id") if isinstance(payload, dict) else None
            new_sub_url = remnawave_api.extract_subscription_url(payload) or ""
            rw_repo.update_key(key_id,
                               host_name=target,
                               remnawave_user_uuid=str(new_rw_id) if new_rw_id else None,
                               subscription_url=new_sub_url,
                               traffic_limit_bytes=new_limit if new_limit > 0 else None)

            # 6. Перенести carry-баланс: излишек → несгораемый
            if extra_carry_gb > 0:
                next_reset = uc.next_reset_date(uc.get_msk_time()).strftime("%Y-%m-%d")
                tr_repo.ensure_carry_balance(key_id, const.ROLE_PRIMARY,
                                             const.TRAFFIC_TYPE_WIFI, next_reset)
                tr_repo.add_carry_gb(key_id, const.ROLE_PRIMARY,
                                     const.TRAFFIC_TYPE_WIFI, extra_carry_gb)
                tr_repo.record_traffic_operation(
                    idempotency_key=f"server_migration_carry:{key_id}:{uc.today_date_str()}",
                    operation_type=const.OP_MANUAL_ADJUSTMENT,
                    key_id=key_id,
                    target_role=const.ROLE_PRIMARY,
                    traffic_type=const.TRAFFIC_TYPE_WIFI,
                    gb_delta=extra_carry_gb,
                    is_non_burnable=1,
                    actor_type=const.ACTOR_ADMIN,
                    result=const.OP_RESULT_SUCCESS,
                    details={"source": "server_migration",
                             "from_host": source, "to_host": target,
                             "old_limit_bytes": old_limit,
                             "target_base_bytes": target_base,
                             "extra_carry_gb": extra_carry_gb},
                )

            tr_repo.record_traffic_operation(
                idempotency_key=f"server_migration:{key_id}:{uc.today_date_str()}",
                operation_type=const.OP_HYBRID_REPAIR,
                key_id=key_id,
                actor_type=const.ACTOR_ADMIN,
                result=const.OP_RESULT_SUCCESS,
                details={"from_host": source, "to_host": target,
                         "old_limit": old_limit, "old_used": old_used,
                         "new_limit": new_limit, "role": role},
            )
            migrated += 1
            logger.info("SERVER MIGRATION: key %s migrated %s -> %s", key_id, source, target)

        except Exception as exc:
            logger.error("server_migration: key %s error: %s", key_id, exc, exc_info=True)
            tr_repo.record_traffic_operation(
                idempotency_key=f"server_migration_error:{key_id}:{uc.today_date_str()}",
                operation_type=const.OP_HYBRID_REPAIR,
                key_id=key_id,
                actor_type=const.ACTOR_ADMIN,
                result=const.OP_RESULT_FAILED,
                error_text=str(exc)[:500],
            )
            errors += 1

    new_offset = offset + len(batch)
    done = new_offset >= len(keys)
    state["offset"] = new_offset
    if done:
        state["source_host"] = None
        state["target_host"] = None
    set_state(state)
    return {"done": done, "migrated": migrated, "skipped": skipped,
            "errors": errors, "offset": new_offset, "total": len(keys)}
