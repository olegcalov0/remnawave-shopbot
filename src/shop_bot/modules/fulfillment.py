"""Надёжный поток успешной оплаты (Этап 3 ТЗ).

Единый flow для всех провайдеров:
1. webhook проверяет подпись/статус;
2. находит внутренний payment_id;
3. атомарно помечает pending как paid один раз (mark_pending_paid_once);
4. создаёт payment_fulfillment_jobs (upsert_fulfillment_job);
5. быстро возвращает HTTP 200;
6. job worker исполняет выдачу и фиксирует результат.

process_successful_payment остаётся точкой входа выдачи, но разделяется
на fulfill_top_up / fulfill_subscription / fulfill_traffic_purchase и защищается
условным переходом статуса job вместо check_transaction_exists.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import timedelta
from typing import Any

from shop_bot.data_manager import remnawave_repository as rw_repo
from shop_bot.data_manager import traffic_repository as tr_repo
from shop_bot.modules import utils_common as uc
from shop_bot.modules import domain_constants as const

logger = logging.getLogger(__name__)


def confirm_payment_and_enqueue(provider: str, payment_id: str, metadata: dict | None = None) -> bool:
    """Общий helper для всех webhook handlers.

    Атомарно pending->paid и создаёт fulfillment job. Возвращает True, если
    операция поставлена в очередь (или уже была поставлена ранее — идемпотентно).
    """
    if not payment_id:
        logger.warning("FULFILLMENT confirm: пустой payment_id от провайдера %s", provider)
        return False

    meta = tr_repo.mark_pending_paid_once(payment_id)
    if meta is None:
        # либо уже обработан, либо нет pending-записи (например, YooKassa передаёт
        # metadata напрямую): тогда используем переданный metadata, но job создаём
        # ровно один раз через UNIQUE(payment_id)
        meta = metadata or {}
        meta.setdefault("payment_id", payment_id)
        logger.info("FULFILLMENT confirm: %s payment=%s — нет pending-записи, используем metadata напрямую",
                    provider, payment_id)
    else:
        logger.info("FULFILLMENT confirm: %s payment=%s — pending→paid", provider, payment_id)

    action = meta.get("action") or "unknown"
    job_id = tr_repo.upsert_fulfillment_job(payment_id, provider, str(action), meta)
    if job_id is None:
        logger.info("fulfillment: job для %s уже существует (дубль webhook)", payment_id)
    else:
        logger.info("FULFILLMENT confirm: %s payment=%s — создан job #%s (action=%s)",
                    provider, payment_id, job_id, action)
    return True


def _delay_for_attempt(attempts: int) -> str:
    """Экспоненциальная задержка: 30s, 60s, 120s, ... cap 30m."""
    seconds = min(30 * (2 ** max(0, attempts - 1)), 1800)
    return (uc.get_msk_time() + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


async def _notify_admins(bot, text: str):
    try:
        admin_ids = list(rw_repo.get_admin_ids() or [])
    except Exception:
        admin_ids = []
    for admin_id in admin_ids:
        try:
            await bot.send_message(int(admin_id), text, parse_mode="HTML")
        except Exception:
            continue


async def _fulfill_only(payload: dict) -> bool:
    """Исполнить traffic purchase по payload (без job-обвязки). Для worker и тестов."""
    from shop_bot.modules import traffic_service
    return await traffic_service.fulfill_traffic_purchase(None, payload)


async def process_job(bot, job: dict) -> bool:
    """Исполнение одного job: диспетчер по action."""
    from shop_bot.bot import handlers as bot_handlers

    payment_id = job.get("payment_id")
    logger.info("FULFILLMENT worker: job #%s payment=%s action=%s attempts=%s",
                job.get("job_id"), payment_id, job.get("action") or "unknown",
                job.get("attempts"))

    payload = {}
    try:
        import json as _json
        payload = _json.loads(job.get("payload_json") or "{}")
    except Exception:
        payload = {}

    payment_id = job.get("payment_id")
    action = payload.get("action")

    try:
        if action == "traffic_purchase":
            from shop_bot.modules import traffic_service
            ok = await traffic_service.fulfill_traffic_purchase(bot, payload)
        else:
            # legacy actions: new / extend / top_up — через существующую логику,
            # но идемпотентность теперь гарантирует условный переход job
            ok = await bot_handlers.process_successful_payment(bot, payload)
    except Exception as exc:
        logger.exception("fulfillment: ошибка исполнения job %s", payment_id)
        ok = False
        job["__error__"] = str(exc)

    if ok:
        tr_repo.complete_job(job["job_id"])
        return True

    error = job.get("__error__") or "fulfillment failed"
    attempts = int(job.get("attempts") or 1)
    max_attempts = int(job.get("max_attempts") or 10)

    # Рефанд для traffic_purchase: если прошло > 30 мин с создания job
    # и гигабайты не начислены — вернуть деньги на баланс, уведомить пользователя
    if action == "traffic_purchase":
        from datetime import datetime as _dt
        try:
            created_raw = job.get("created_at")
            if created_raw:
                created = _dt.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=uc.MSK_TZ)
                age = uc.get_msk_time() - created
                if age.total_seconds() > 30 * 60:
                    return await _refund_traffic_purchase(bot, job, payload, error)
        except Exception:
            pass

    tr_repo.fail_job_retryable(job["job_id"], error, _delay_for_attempt(attempts), max_attempts)

    # уведомления: первая ошибка и переход в manual_review
    if attempts == 1:
        await _notify_admins(
            bot, f"⚠️ <b>Fulfillment retry</b>\nПлатёж <code>{payment_id}</code> (action={action}) "
                 f"не исполнен с первой попытки: <code>{error[:200]}</code>. Будет ретрай.")
    if attempts >= max_attempts:
        await _notify_admins(
            bot, f"🚨 <b>Fulfillment manual review</b>\nПлатёж <code>{payment_id}</code> "
                 f"исчерпал {max_attempts} попыток: <code>{error[:200]}</code>. Требуется ручная проверка.")
        # пользователю понятный итог
        try:
            uid = int(payload.get("user_id") or 0)
            if uid and bot and not str(uid).startswith("999"):
                await bot.send_message(
                    uid, "⏳ Ваша оплата зафиксирована. Начисление выполняется автоматически, "
                        "при задержке свяжитесь с поддержкой.")
        except Exception:
            pass
    return False


async def _refund_traffic_purchase(bot, job: dict, payload: dict, error: str) -> bool:
    """Возврат средств за неудавшуюся докупку: balance +, purchase cancelled, уведомление.

    Идемпотентно: cancel_purchase_refunded переводит статус только один раз,
    повторный вызов не начислит баланс повторно.
    """
    payment_id = job.get("payment_id")
    purchase = tr_repo.get_traffic_purchase(payment_id)
    if not purchase:
        return False

    # условный переход: только один конкурентный обработчик выполнит рефанд
    if not tr_repo.cancel_purchase_refunded(payment_id, reason=f"refund: {error[:300]}"):
        logger.info("REFUND: %s уже обработан (fulfilled/cancelled) — пропускаю", payment_id)
        return False

    amount = float(purchase.get("total_price_rub") or 0)
    user_id = int(purchase.get("user_id") or 0)
    gb = int(purchase.get("gb_amount") or 0)
    refund_ok = rw_repo.add_to_balance(user_id, amount)
    logger.info("REFUND: payment=%s user=%s amount=%.2f gb=%s add_to_balance=%s",
                payment_id, user_id, amount, gb, refund_ok)

    tr_repo.fail_job_manual_review(job["job_id"], f"refunded after 30 min: {error[:200]}")

    if refund_ok:
        await _notify_admins(
            bot, f"💸 <b>Рефанд докупки ГБ</b>\nПлатёж <code>{payment_id}</code>: "
                 f"{gb} ГБ не начислены за 30 минут.\nВозвращено {amount:.2f} ₽ "
                 f"пользователю <code>{user_id}</code>. Причина: <code>{error[:150]}</code>")
        if bot and user_id:
            try:
                await bot.send_message(
                    user_id,
                    f"😔 <b>Не удалось докупить гигабайты</b>\n\n"
                    f"Оплата прошла, но начисление {gb} ГБ не удалось за отведённое время.\n"
                    f"Сумма <b>{amount:.2f} ₽</b> возвращена на ваш баланс.\n\n"
                    f"Попробуйте оформить покупку заново или обратитесь в поддержку.",
                    parse_mode="HTML")
            except Exception:
                pass
    else:
        await _notify_admins(
            bot, f"🚨 <b>Рефанд докупки ГБ НЕ УДАЛСЯ</b>\nПлатёж <code>{payment_id}</code>: "
                 f"не удалось вернуть {amount:.2f} ₽ пользователю <code>{user_id}</code>. "
                 f"Требуется ручной возврат.")
    return False


async def run_fulfillment_worker(bot, *, batch: int = 5) -> int:
    """Один проход worker'а: захват due jobs и исполнение. Вызывается из scheduler."""
    now_iso = uc.now_str()
    # сброс зависших processing (рестарт/падение)
    stale_before = (uc.get_msk_time() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    released = tr_repo.release_stale_jobs(stale_before)
    if released:
        logger.info("FULFILLMENT worker: освобождено зависших jobs: %s", released)

    lock_token = secrets.token_hex(8)
    jobs = tr_repo.claim_due_job(lock_token, now_iso, limit=batch)
    if not jobs:
        return 0
    logger.info("FULFILLMENT worker: захвачено jobs: %d", len(jobs))
    processed = 0
    for job in jobs:
        await process_job(bot, job)
        processed += 1
    return processed
