"""Ручная миграция существующих активных ключей в гибридный режим (Этап 9 ТЗ).

Только после полного завершения предыдущих этапов; запускается администратором
из админки; обрабатывает ограниченное число ключей за проход с pause/resume.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from shop_bot.data_manager import remnawave_repository as rw_repo
from shop_bot.data_manager import traffic_repository as tr_repo
from shop_bot.modules import remnawave_api
from shop_bot.modules import hybrid_service
from shop_bot.modules import utils_common as uc
from shop_bot.modules import domain_constants as const

logger = logging.getLogger(__name__)

MIGRATION_STATE_KEY = "hybrid_migration_state"  # json: {host, offset, paused}
BATCH_SIZE = 10


def get_migration_state() -> dict:
    import json
    raw = rw_repo.get_setting(MIGRATION_STATE_KEY) or "{}"
    try:
        return json.loads(raw)
    except Exception:
        return {"host": None, "offset": 0, "paused": False}


def set_migration_state(state: dict) -> None:
    import json
    rw_repo.update_setting(MIGRATION_STATE_KEY, json.dumps(state))


def start_migration(host_name: str) -> dict:
    set_migration_state({"host": host_name, "offset": 0, "paused": False})
    return {"started": True, "host": host_name}


def pause_migration() -> dict:
    state = get_migration_state()
    state["paused"] = True
    set_migration_state(state)
    return state


def resume_migration() -> dict:
    state = get_migration_state()
    state["paused"] = False
    set_migration_state(state)
    return state


def _plan_snapshot_for_key(key: dict) -> tuple[int, int]:
    """LTE лимит/HWID из тарифа, привязанного к хосту ключа."""
    plans = rw_repo.get_plans_for_host(key.get("host_name")) or []
    if plans:
        plan = plans[0]
        return int(plan.get("hybrid_traffic_limit_gb") or 0), int(plan.get("hybrid_hwid_limit") or 0)
    return 0, 0


async def run_migration_batch() -> dict:
    """Обработать ограниченное число ключей за проход. Не блокирует Flask request."""
    state = get_migration_state()
    host_name = state.get("host")
    if not host_name or state.get("paused"):
        return {"done": False, "reason": "no active migration" if not host_name else "paused"}

    host = tr_repo.get_host_hybrid_settings(host_name)
    if not host or int(host.get("hybrid_enabled") or 0) != 1:
        return {"done": True, "reason": "host is not hybrid-enabled"}

    keys = rw_repo.get_keys_for_host(host_name) or []
    offset = int(state.get("offset") or 0)
    batch = keys[offset:offset + BATCH_SIZE]

    migrated = skipped = errors = 0
    for key in batch:
        key_id = int(key.get("key_id") or 0)
        if not key_id or tr_repo.get_pair_by_primary_key(key_id):
            skipped += 1
            continue
        try:
            # сверить primary panel user
            primary = await remnawave_api.get_user_by_id(
                key.get("remnawave_user_uuid"), host_name=host_name)
            if not primary:
                errors += 1
                continue
            telegram_id = primary.get("telegramId") or key.get("user_id")
            if not telegram_id:
                # отсутствие telegramId: не создаём hybrid, skip/error
                tr_repo.record_traffic_operation(
                    idempotency_key=f"hybrid_migration_skip:{key_id}",
                    operation_type=const.OP_HYBRID_REPAIR, key_id=key_id,
                    actor_type=const.ACTOR_ADMIN, result=const.OP_RESULT_SKIPPED,
                    error_text="no telegramId on primary panel user")
                skipped += 1
                continue

            base_username, hybrid_username = hybrid_service.build_remnawave_usernames(
                None, int(telegram_id), host.get("hybrid_suffix"))
            hybrid_email = hybrid_service.build_hybrid_email(base_username)
            expire_iso = primary.get("expireAt") or (uc.get_msk_time() + timedelta(days=30)).isoformat()
            expire_dt = uc.parse_iso_or_none(expire_iso) or (uc.get_msk_time() + timedelta(days=30))

            lte_gb, lte_hwid = _plan_snapshot_for_key(key)
            await remnawave_api.ensure_user(
                host_name=host_name, email=hybrid_email, squad_uuid=host.get("hybrid_squad_uuid"),
                expire_at=expire_dt, traffic_limit_bytes=uc.gb_to_bytes(lte_gb) if lte_gb else None,
                traffic_limit_strategy="NO_RESET", username=hybrid_username,
                telegram_id=int(telegram_id), hwid_limit=lte_hwid or None)

            tr_repo.create_pair({
                "primary_key_id": key_id, "user_id": int(key.get("user_id") or 0),
                "host_name": host_name, "telegram_id": int(telegram_id),
                "base_username": base_username, "hybrid_username": hybrid_username,
                "primary_remnawave_user_id": primary.get("id"),
                "hybrid_remnawave_user_id": primary.get("id"),  # будет заменён ниже
                "primary_email": key.get("key_email") or key.get("email"),
                "hybrid_email": hybrid_email,
                "primary_squad_uuid": host.get("squad_uuid") or "",
                "hybrid_squad_uuid": host.get("hybrid_squad_uuid") or "",
            })
            # уточнить hybrid id
            hybrid_user = await remnawave_api.get_user_by_email(hybrid_email, host_name=host_name)
            if hybrid_user:
                with tr_repo._connect() as conn:
                    conn.execute(
                        "UPDATE hybrid_subscription_pairs SET hybrid_remnawave_user_id = ? WHERE primary_key_id = ?",
                        (str(hybrid_user.get("id")), key_id))
                    conn.commit()

            next_reset = uc.next_reset_date(uc.get_msk_time()).strftime("%Y-%m-%d")
            tr_repo.ensure_carry_balance(key_id, const.ROLE_PRIMARY, const.TRAFFIC_TYPE_WIFI, next_reset)
            tr_repo.ensure_carry_balance(key_id, const.ROLE_HYBRID, const.TRAFFIC_TYPE_LTE, next_reset)
            tr_repo.record_traffic_operation(
                idempotency_key=f"hybrid_migration:{key_id}",
                operation_type=const.OP_HYBRID_REPAIR, key_id=key_id,
                actor_type=const.ACTOR_ADMIN, result=const.OP_RESULT_SUCCESS)
            migrated += 1
        except Exception as exc:
            # конфликт/ошибка оставляют ключ обычным, не удаляют и не ухудшают доступ
            logger.error("hybrid_migration: key %s: %s", key_id, exc)
            tr_repo.record_traffic_operation(
                idempotency_key=f"hybrid_migration_error:{key_id}:{uc.today_date_str()}",
                operation_type=const.OP_HYBRID_REPAIR, key_id=key_id,
                actor_type=const.ACTOR_ADMIN, result=const.OP_RESULT_FAILED,
                error_text=str(exc)[:500])
            errors += 1

    new_offset = offset + len(batch)
    done = new_offset >= len(keys)
    state["offset"] = new_offset
    if done:
        state["host"] = None
    set_migration_state(state)
    return {"done": done, "migrated": migrated, "skipped": skipped,
            "errors": errors, "offset": new_offset, "total": len(keys)}
