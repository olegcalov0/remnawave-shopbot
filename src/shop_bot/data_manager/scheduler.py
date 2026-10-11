import asyncio
import logging
import json

from datetime import datetime, timedelta, timezone

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from shop_bot.bot_controller import BotController
from shop_bot.data_manager import remnawave_repository as rw_repo
from shop_bot.data_manager import resource_monitor
from shop_bot.data_manager import speedtest_runner
from shop_bot.data_manager import backup_manager

from shop_bot.modules import remnawave_api
from shop_bot.bot import keyboards

CHECK_INTERVAL_SECONDS = 300
NOTIFY_BEFORE_HOURS = {72, 48, 24, 1}
notified_users = {}

logger = logging.getLogger(__name__)


def get_msk_time() -> datetime:
    return datetime.now(timezone(timedelta(hours=3)))



SPEEDTEST_INTERVAL_SECONDS = 8 * 3600
_scheduler_start_time = get_msk_time()
_last_speedtests_run_at: datetime | None = None
_last_backup_run_at: datetime | None = None
_last_resource_collect_at: datetime | None = None
_last_resource_alert_at: dict[tuple[str, str, str], datetime] = {}
_last_traffic_reset_at: datetime | None = None
_last_low_traffic_notify_at: datetime | None = None
_last_hybrid_migration_at: datetime | None = None
_last_pair_repair_at: datetime | None = None
_last_server_migration_at: datetime | None = None

def format_time_left(hours: int) -> str:
    if hours >= 24:
        days = hours // 24
        if days % 10 == 1 and days % 100 != 11:
            return f"{days} день"
        elif 2 <= days % 10 <= 4 and (days % 100 < 10 or days % 100 >= 20):
            return f"{days} дня"
        else:
            return f"{days} дней"
    else:
        if hours % 10 == 1 and hours % 100 != 11:
            return f"{hours} час"
        elif 2 <= hours % 10 <= 4 and (hours % 100 < 10 or hours % 100 >= 20):
            return f"{hours} часа"
        else:
            return f"{hours} часов"

async def send_subscription_notification(bot: Bot, user_id: int, key_id: int, time_left_hours: int, expiry_date: datetime):
    try:
        time_text = format_time_left(time_left_hours)
        expiry_str = expiry_date.strftime('%d.%m.%Y в %H:%M')
        
        message = (
            f"⚠️ **Внимание!** ⚠️\n\n"
            f"Срок действия вашей подписки истекает через **{time_text}**.\n"
            f"Дата окончания: **{expiry_str}**\n\n"
            f"Продлите подписку, чтобы не остаться без доступа к VPN!"
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔑 Мои ключи", callback_data="manage_keys")
        builder.button(text="➕ Продлить ключ", callback_data=f"extend_key_{key_id}")
        builder.adjust(2)
        
        await bot.send_message(chat_id=user_id, text=message, reply_markup=builder.as_markup(), parse_mode='Markdown')
        logger.debug(f"Scheduler: Отправлено уведомление пользователю {user_id} по ключу {key_id} (осталось {time_left_hours} ч).")
        return True
    except TelegramForbiddenError:
        logger.info("Scheduler: пользователь %s заблокировал бота; уведомление по ключу %s пропущено.", user_id, key_id)
        return True
    except Exception as e:
        logger.error(f"Scheduler: Ошибка отправки уведомления пользователю {user_id}: {e}")
        return False

def _cleanup_notified_users(all_db_keys: list[dict]):
    if not notified_users:
        return

    logger.debug("Scheduler: Очищаю кэш уведомлений...")
    
    active_key_ids = {key['key_id'] for key in all_db_keys}
    
    users_to_check = list(notified_users.keys())
    
    cleaned_users = 0
    cleaned_keys = 0

    for user_id in users_to_check:
        keys_to_check = list(notified_users[user_id].keys())
        for key_id in keys_to_check:
            if key_id not in active_key_ids:
                del notified_users[user_id][key_id]
                cleaned_keys += 1
        
        if not notified_users[user_id]:
            del notified_users[user_id]
            cleaned_users += 1
    
    if cleaned_users > 0 or cleaned_keys > 0:
        logger.debug(f"Scheduler: Очистка завершена. Удалено записей пользователей: {cleaned_users}, ключей: {cleaned_keys}.")

async def check_expiring_subscriptions(bot: Bot):
    logger.debug("Scheduler: Проверяю истекающие подписки...")
    current_time = get_msk_time().replace(tzinfo=None)
    all_keys = rw_repo.get_all_keys()
    
    _cleanup_notified_users(all_keys)
    
    for key in all_keys:
        try:
            expiry_date = datetime.fromisoformat(key['expiry_date'])
            time_left = expiry_date - current_time

            if time_left.total_seconds() < 0:
                continue

            total_hours_left = int(time_left.total_seconds() / 3600)
            user_id = key['user_id']
            key_id = key['key_id']

            for hours_mark in NOTIFY_BEFORE_HOURS:
                if hours_mark - 1 < total_hours_left <= hours_mark:
                    notified_users.setdefault(user_id, {}).setdefault(key_id, set())
                    
                    if hours_mark not in notified_users[user_id][key_id]:
                        if await send_subscription_notification(bot, user_id, key_id, hours_mark, expiry_date):
                            notified_users[user_id][key_id].add(hours_mark)
                    break 
                    
        except Exception as e:
            logger.error(f"Scheduler: Ошибка обработки истечения для ключа {key.get('key_id')}: {e}")

async def sync_keys_with_panels():
    logger.debug("Scheduler: Запускаю синхронизацию с Remnawave API...")
    total_affected_records = 0

    squads = rw_repo.list_squads()
    if not squads:
        logger.debug("Scheduler: Сквады Remnawave не настроены. Синхронизация пропущена.")
        return

    for squad in squads:
        host_name = (squad.get('host_name') or squad.get('name') or '').strip() or 'unknown'
        squad_uuid = (squad.get('squad_uuid') or squad.get('squadUuid') or '').strip()
        if not squad_uuid:
            logger.warning("Scheduler: Сквад '%s' не имеет squad_uuid — пропускаю синхронизацию.", host_name)
            continue

        try:
            remote_users = await remnawave_api.list_users(host_name=host_name, squad_uuid=squad_uuid)
        except Exception as exc:
            logger.error("Scheduler: Не удалось получить пользователей Remnawave для '%s': %s", host_name, exc)
            continue

        remote_by_email: dict[str, tuple[str, dict]] = {}
        for remote_user in remote_users or []:
            raw_email = (remote_user.get('email') or remote_user.get('accountEmail') or '').strip()
            if not raw_email:
                continue
            remote_by_email[raw_email.lower()] = (raw_email, remote_user)

        # Гибридные пары хоста: не создавать второй vpn_keys из hybrid panel user (Этап 2 ТЗ, п.6)
        from shop_bot.data_manager import traffic_repository as tr_repo
        from shop_bot.modules import domain_constants as const
        hybrid_emails: set[str] = set()
        hybrid_user_ids: set[str] = set()
        pairs = tr_repo.list_active_pairs(host_name)
        for pair in pairs:
            h_email = (pair.get('hybrid_email') or '').lower()
            if h_email:
                hybrid_emails.add(h_email)
                remote_by_email.pop(h_email, None)
            if pair.get('hybrid_remnawave_user_id'):
                hybrid_user_ids.add(str(pair['hybrid_remnawave_user_id']))
            # проверка пропажи стороны: primary/hybrid должны существовать в панели
            p_alive = any(
                str((ru or {}).get('id')) == str(pair.get('primary_remnawave_user_id'))
                for ru in (remote_users or [])
            )
            # hybrid может быть в другом squad — проверяем по обоим спискам ниже
        # отдельно: убрать hybrid users по ID из remote_by_email (squad-фильтр мог их скрыть)
        for rem_email_norm in list(remote_by_email.keys()):
            rem_email, rem_user = remote_by_email[rem_email_norm]
            rem_uuid = str(rem_user.get('uuid') or rem_user.get('id') or rem_user.get('client_uuid') or '')
            if rem_uuid and rem_uuid in hybrid_user_ids:
                hybrid_emails.add(rem_email_norm)
                remote_by_email.pop(rem_email_norm, None)

        keys_in_db = rw_repo.get_keys_for_host(host_name) or []
        now = get_msk_time().replace(tzinfo=None)

        for db_key in keys_in_db:
            raw_email = (db_key.get('key_email') or db_key.get('email') or '').strip()
            normalized_email = raw_email.lower()
            if not raw_email:
                continue

            remote_entry = remote_by_email.pop(normalized_email, None)
            remote_email = None
            remote_user = None
            if remote_entry:
                remote_email, remote_user = remote_entry
            else:
                local_uuid = (db_key.get('remnawave_user_uuid') or '').strip()
                if local_uuid:
                    for rem_email_norm, (rem_email, rem_user) in list(remote_by_email.items()):
                        rem_uuid = str(rem_user.get('uuid') or rem_user.get('id') or rem_user.get('client_uuid') or '').strip()
                        if rem_uuid and rem_uuid == local_uuid:
                            remote_entry = remote_by_email.pop(rem_email_norm)
                            remote_email, remote_user = remote_entry
                            logger.info(
                                "Scheduler: Найден ключ по UUID '%s'. Email изменён: '%s' → '%s'. Полностью обновляю данные.",
                                local_uuid,
                                raw_email,
                                rem_email,
                            )
                            expire_value = rem_user.get('expireAt') or rem_user.get('expiryDate')
                            expire_ms = None
                            if expire_value:
                                try:
                                    expire_ms = int(datetime.fromisoformat(str(expire_value).replace('Z', '+00:00')).timestamp() * 1000)
                                except Exception:
                                    pass
                            subscription_url = remnawave_api.extract_subscription_url(rem_user)
                            rw_repo.update_key_fields(
                                db_key.get('key_id'),
                                email=rem_email,
                                remnawave_user_uuid=rem_uuid,
                                expire_at_ms=expire_ms,
                                subscription_url=subscription_url,
                                short_uuid=rem_user.get('shortUuid') or rem_user.get('short_uuid'),
                                traffic_limit_bytes=rem_user.get('trafficLimitBytes') or rem_user.get('traffic_limit_bytes'),
                                traffic_limit_strategy=rem_user.get('trafficLimitStrategy') or rem_user.get('traffic_limit_strategy'),
                            )
                            total_affected_records += 1
                            break

            expiry_raw = db_key.get('expiry_date') or db_key.get('expire_at')
            try:
                expiry_date = datetime.fromisoformat(str(expiry_raw)) if expiry_raw else None
            except Exception:
                try:
                    expiry_date = datetime.fromisoformat(str(expiry_raw).replace('Z', '+00:00'))
                except Exception:
                    expiry_date = None

            if expiry_date and expiry_date < now - timedelta(days=5):
                # Идентификация перед удалением: панельный telegramId должен
                # совпадать с владельцем ключа, иначе удаляем не тот аккаунт.
                _remote_tg = (remote_user or {}).get('telegramId') if remote_user else None
                _owner = db_key.get('user_id')
                if _remote_tg not in (None, '', 'None', 0) and _owner and str(_remote_tg) != str(_owner):
                    logger.error(
                        "IDENTITY MISMATCH (scheduler delete): key %s owner=%s panel telegramId=%s — "
                        "автоудаление пропущено, панельный аккаунт не тронут",
                        db_key.get('key_id'), _owner, _remote_tg)
                    try:
                        tr_repo.record_traffic_operation(
                            idempotency_key=f"identity_mismatch_delete:{db_key.get('key_id')}:{datetime.now().strftime('%Y-%m-%d')}",
                            operation_type='manual_adjustment', key_id=db_key.get('key_id') or 0,
                            actor_type='automation', result='failed',
                            error_text=f"panel telegramId={_remote_tg} != owner {_owner}; delete skipped")
                    except Exception:
                        pass
                    continue
                # гибридные пары: не удалять primary автоматически — repair job (Этап 2 ТЗ)
                pair_for_key = tr_repo.get_pair_by_primary_key(db_key.get('key_id') or 0)
                if pair_for_key and pair_for_key.get('status') in ('active', 'repair_required'):
                    try:
                        from shop_bot.modules import hybrid_service
                        await hybrid_service.delete_pair_users(pair_for_key)
                        logger.info(
                            "Scheduler: Удалена просроченная гибридная пара для '%s' (key %s).",
                            raw_email, pair_for_key.get('primary_key_id'),
                        )
                    except Exception as exc:
                        logger.error("Scheduler: Ошибка удаления пары для '%s': %s", raw_email, exc)
                        tr_repo.update_pair_status(pair_for_key['pair_id'], 'repair_required', error=str(exc))
                else:
                    logger.debug(
                        "Scheduler: Ключ '%s' (host '%s') просрочен более 5 дней. Удаляю пользователя из Remnawave и БД.",
                        raw_email,
                        host_name,
                    )
                    try:
                        await remnawave_api.delete_client_on_host(host_name, remote_email or raw_email)
                    except Exception as exc:
                        logger.error(
                            "Scheduler: Не удалось удалить пользователя '%s' из Remnawave: %s",
                            raw_email,
                            exc,
                        )
                if rw_repo.delete_key_by_email(raw_email):
                    total_affected_records += 1
                continue

            if remote_user:
                expire_value = remote_user.get('expireAt') or remote_user.get('expiryDate')
                remote_dt = None
                if expire_value:
                    try:
                        remote_dt = datetime.fromisoformat(str(expire_value).replace('Z', '+00:00'))
                    except Exception:
                        remote_dt = None
                local_ms = int(expiry_date.timestamp() * 1000) if expiry_date else None
                remote_ms = int(remote_dt.timestamp() * 1000) if remote_dt else None
                subscription_url = remnawave_api.extract_subscription_url(remote_user)
                local_subscription = db_key.get('subscription_url') or db_key.get('connection_string')

                needs_update = False
                if remote_ms is not None and local_ms is not None and abs(remote_ms - local_ms) > 1000:
                    needs_update = True
                if subscription_url and subscription_url != local_subscription:
                    needs_update = True

                if needs_update:
                    if rw_repo.update_key_status_from_server(raw_email, remote_user):
                        total_affected_records += 1
                        logger.debug(
                            "Scheduler: Обновлён ключ '%s' на основе данных Remnawave (host '%s').",
                            raw_email,
                            host_name,
                        )
            else:
                logger.warning(
                    "Scheduler: Ключ '%s' (host '%s') отсутствует в Remnawave. Помечаю к удалению в локальной БД.",
                    raw_email,
                    host_name,
                )
                if rw_repo.update_key_status_from_server(raw_email, None):
                    total_affected_records += 1

        if remote_by_email:
            for normalized_email, (remote_email, remote_user) in remote_by_email.items():
                # гибридные panel users не должны становиться отдельными ключами
                if normalized_email in hybrid_emails:
                    logger.debug(
                        "Scheduler: '%s' — пользователь гибридной пары, вторая подписка не создаётся.",
                        remote_email,
                    )
                    continue
                import re

                # Пытаемся найти user_id разными способами
                user_id = remote_user.get('telegramId')
                
                if not user_id:
                    # Пробуем найти в note (часто там хранят)
                    note = str(remote_user.get('note') or "")
                    if note.isdigit():
                        user_id = int(note)
                
                if not user_id:
                    match = re.search(r"user(\d+)", remote_email)
                    user_id = int(match.group(1)) if match else None
                
                # Если все равно нет ID, можно попробовать найти пользователя по username из email (до @)
                if not user_id:
                     username_part = remote_email.split('@')[0]
                     # Здесь нужен метод репозитория для поиска по username, но его может не быть.
                     # Пока оставим как есть, но без user_id мы не можем привязать.
                     pass
                remote_uuid = str(remote_user.get('uuid') or remote_user.get('id') or remote_user.get('client_uuid') or '').strip()
                
                # Ищем существующий ключ в базе по Email или UUID
                existing_key = None
                existing_by_email = rw_repo.get_key_by_email(remote_email)
                if existing_by_email:
                    existing_key = existing_by_email
                elif remote_uuid:
                    existing_by_uuid = rw_repo.get_key_by_remnawave_uuid(remote_uuid)
                    if existing_by_uuid:
                        existing_key = existing_by_uuid

                # Если user_id не пришел с панели, пробуем взять его из существующего ключа
                if user_id is None and existing_key:
                    user_id = existing_key.get('user_id')
                    logger.info(
                        "Scheduler: ID пользователя восстановлен из локальной БД (user_id=%s) для '%s'.",
                        user_id,
                        remote_email,
                    )

                # Ищем пользователя по username из email (до @)
                if user_id is None:
                    username_part = remote_email.split('@')[0]
                    
                    # 1. Сначала пробуем "как есть"  
                    candidates = [username_part]
                    
                    # 2. Если есть суффиксы -2, -3 и т.д., пробуем отрезать их
                     
                    import re
                    # Ищем паттерн: любое_имя-цифра(ы)
                    # Используем цикл, чтобы отрезать несколько раз, если вдруг что-то типа name-2-3 (редко, но бывает)
                    temp = username_part
                    while True:
                        match_suffix = re.search(r"^(.*?)(?:-\d+)$", temp)
                        if match_suffix:
                             base = match_suffix.group(1)
                             if base and base not in candidates:
                                 candidates.append(base)
                             temp = base
                        else:
                            break
                    
                    for candidate in candidates:
                        # Попытка найти пользователя по username в базе данных
                        user_by_username = rw_repo.get_user_by_username(candidate)
                        if user_by_username:
                            user_id = user_by_username.get('telegram_id')
                            logger.info(
                                "Scheduler: ID пользователя найден по username '%s' (из '%s') -> user_id=%s.",
                                candidate,
                                remote_email,
                                user_id,
                            )
                            break

                if user_id is None:
                    # Если это подарочный ключ (gift-uuid@bot.local)
                    if remote_email.startswith('gift-'):
                        token_prefix = remote_email.split('@')[0]
                        # Сначала ищем по полному префиксу (напр. gift-xxxx)
                        user_id = rw_repo.get_user_id_by_gift_token(token_prefix)
                        if user_id is None and '-' in token_prefix:
                            # Пробуем без префикса "gift-"
                            user_id = rw_repo.get_user_id_by_gift_token(token_prefix.split('-', 1)[1])
                
                # Если user_id всё ещё нет, но ключ есть в БД — это странно, но мы можем обновить его
                # Если ключа нет и user_id нет — это реально новый "осиротевший" пользователь
                if user_id is None:
                    if existing_key:
                         # Теоретически не должно сюда попасть, если мы взяли user_id из existing_key
                         # Но если в existing_key user_id=None (что невозможно по схеме), то ок.
                         pass
                    else:
                        if remote_email.startswith('gift-'):
                            logger.info(
                                "Scheduler: Подарочный ключ '%s' в Remnawave ожидает активации — оставляем в БД и панели без изменений.",
                                remote_email,
                            )
                        else:
                            logger.warning(
                                "Scheduler: Осиротевший пользователь '%s' в Remnawave не содержит user_id — пропускаю (ключ останется в панели, но не привяжется).",
                                remote_email,
                            )
                        continue

                # Автоматическая регистрация пользователя, если его нет в БД (и это не подарок без владельца)
                if user_id and user_id != 0 and not rw_repo.get_user(user_id):
                    logger.info(
                        "Scheduler: Автоматически регистрирую недостающего пользователя user_id=%s для '%s'.",
                        user_id,
                        remote_email,
                    )
                    rw_repo.register_user_if_not_exists(user_id, f"User_{user_id}", None)

                # Если ключ уже есть в базе (по Email или UUID) — ОБНОВЛЯЕМ его
                if existing_key:
                    old_email = existing_key.get('email') or existing_key.get('key_email')
                    key_id = existing_key.get('key_id')
                    old_user_id = existing_key.get('user_id')
                    
                    # Если user_id изменился (например, перепривязка), логгируем
                    if old_user_id != user_id:
                        logger.info(
                             "Scheduler: Обновление владельца ключа key_id=%s: %s -> %s",
                             key_id, old_user_id, user_id
                        )

                    expire_value = remote_user.get('expireAt') or remote_user.get('expiryDate')
                    expire_ms = None
                    if expire_value:
                        try:
                            expire_ms = int(datetime.fromisoformat(str(expire_value).replace('Z', '+00:00')).timestamp() * 1000)
                        except Exception:
                            pass
                    subscription_url = remnawave_api.extract_subscription_url(remote_user)
                    
                    rw_repo.update_key_fields(
                        key_id,
                        user_id=user_id,
                        email=remote_email,
                        remnawave_user_uuid=remote_uuid,
                        expire_at_ms=expire_ms,
                        subscription_url=subscription_url,
                        short_uuid=remote_user.get('shortUuid') or remote_user.get('short_uuid'),
                        traffic_limit_bytes=remote_user.get('trafficLimitBytes') or remote_user.get('traffic_limit_bytes'),
                        traffic_limit_strategy=remote_user.get('trafficLimitStrategy') or remote_user.get('traffic_limit_strategy'),
                        host_name=host_name, # Принудительно обновляем хост, если ключ "переехал"
                        squad_uuid=squad_uuid,
                    )
                    total_affected_records += 1
                    continue

                # Если ключа нет — СОЗДАЕМ новый
                payload = dict(remote_user)
                payload.setdefault('host_name', host_name)
                payload.setdefault('squad_uuid', squad_uuid)
                payload.setdefault('squadUuid', squad_uuid)

                new_id = rw_repo.record_key_from_payload(
                    user_id=user_id,
                    payload=payload,
                    host_name=host_name,
                    description=payload.get('description'),
                    tag=payload.get('tag'),
                )
                if new_id:
                    total_affected_records += 1
                    logger.info(
                        "Scheduler: Привязал нового пользователя '%s' (host '%s') к user_id=%s как key_id=%s.",
                        remote_email,
                        host_name,
                        user_id,
                        new_id,
                    )
                else:
                    logger.warning(
                        "Scheduler: Не удалось привязать нового пользователя '%s' (host '%s').",
                        remote_email,
                        host_name,
                    )

    logger.debug(
        "Scheduler: Синхронизация с Remnawave API завершена. Затронуто записей: %s.",
        total_affected_records,
    )
async def periodic_subscription_check(bot_controller: BotController):
    logger.info("Scheduler: Планировщик фоновых задач запущен.")
    await asyncio.sleep(10)

    while True:
        try:
            await sync_keys_with_panels()

            # fulfillment retry worker (Этап 3/8 ТЗ)
            try:
                bot_for_jobs = bot_controller.get_bot_instance() if bot_controller.get_status().get("is_running") else None
                from shop_bot.modules import fulfillment as fulfillment_mod
                await fulfillment_mod.run_fulfillment_worker(bot_for_jobs)
            except Exception as e:
                logger.error(f"Scheduler: Ошибка fulfillment worker: {e}", exc_info=True)

            # daily traffic reset + expiry burn (Этап 4/8 ТЗ)
            try:
                await _maybe_run_daily_traffic_reset()
            except Exception as e:
                logger.error(f"Scheduler: Ошибка daily traffic reset: {e}", exc_info=True)

            try:
                await _maybe_run_low_traffic_notifications(bot_controller)
            except Exception as e:
                logger.error(f"Scheduler: Ошибка low-traffic notifications: {e}", exc_info=True)

            try:
                await _maybe_run_hybrid_migration_batch()
            except Exception as e:
                logger.error(f"Scheduler: Ошибка hybrid migration batch: {e}", exc_info=True)

            try:
                await _maybe_run_pair_repair()
            except Exception as e:
                logger.error(f"Scheduler: Ошибка pair repair worker: {e}", exc_info=True)

            try:
                await _maybe_run_server_migration()
            except Exception as e:
                logger.error(f"Scheduler: Ошибка server migration batch: {e}", exc_info=True)

            await _maybe_run_periodic_speedtests()


            bot = bot_controller.get_bot_instance() if bot_controller.get_status().get("is_running") else None
            if bot:
                await _maybe_run_daily_backup(bot)


            bot = bot_controller.get_bot_instance() if bot_controller.get_status().get("is_running") else None
            await _maybe_collect_resource_metrics(bot)

            if bot_controller.get_status().get("is_running"):
                bot = bot_controller.get_bot_instance()
                if bot:
                    await check_expiring_subscriptions(bot)
                else:
                    logger.warning("Scheduler: Бот помечен как запущенный, но экземпляр недоступен.")
            else:
                logger.debug("Scheduler: Бот остановлен, уведомления пользователям пропущены.")

        except Exception as e:
            logger.error(f"Scheduler: Необработанная ошибка в основном цикле: {e}", exc_info=True)
            
        logger.info(f"Scheduler: Цикл завершён. Следующая проверка через {CHECK_INTERVAL_SECONDS} сек.")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

async def _maybe_run_daily_traffic_reset():
    """Раз в сутки: догоняющая обработка индивидуальных reset + сгорание истёкших подписок."""
    global _last_traffic_reset_at
    now = get_msk_time()
    if _last_traffic_reset_at and (now - _last_traffic_reset_at).total_seconds() < 20 * 3600:
        return
    logger.info("Scheduler: запуск daily traffic reset + expiry burn")
    from shop_bot.modules import traffic_service
    from shop_bot.data_manager import traffic_repository as tr_repo
    from shop_bot.modules import domain_constants as const

    processed = await traffic_service.run_daily_resets()
    logger.info("Scheduler: daily traffic reset — обработано reset-записей: %s", processed)
    # expiry burn: истёкшие подписки теряют carry
    try:
        keys = rw_repo.get_all_keys() or []
        for key in keys:
            expire_raw = key.get('expiry_date') or key.get('expire_at')
            expire = None
            if expire_raw:
                try:
                    expire = datetime.fromisoformat(str(expire_raw).replace('Z', '+00:00'))
                except Exception:
                    expire = None
            if expire and expire < now.replace(tzinfo=None):
                await traffic_service.burn_expired_carry(
                    int(key['key_id']), const.ROLE_PRIMARY, const.TRAFFIC_TYPE_WIFI)
                pair = tr_repo.get_pair_by_primary_key(int(key['key_id']))
                if pair:
                    await traffic_service.burn_expired_carry(
                        int(key['key_id']), const.ROLE_HYBRID, const.TRAFFIC_TYPE_LTE)
    except Exception as e:
        logger.error(f"Scheduler: Ошибка expiry burn: {e}", exc_info=True)
    _last_traffic_reset_at = now
    if processed:
        logger.info(f"Scheduler: Traffic reset обработано записей: {processed}")


async def _maybe_run_low_traffic_notifications(bot_controller):
    """Уведомления низкого/нулевого трафика: раз в сутки, анти-спам (Этап 5, п.7)."""
    global _last_low_traffic_notify_at
    now = get_msk_time()
    if _last_low_traffic_notify_at and (now - _last_low_traffic_notify_at).total_seconds() < 20 * 3600:
        return
    _last_low_traffic_notify_at = now

    bot = bot_controller.get_bot_instance() if bot_controller.get_status().get("is_running") else None
    if not bot:
        return

    from shop_bot.modules import traffic_service
    from shop_bot.data_manager import traffic_repository as tr_repo

    try:
        keys = rw_repo.get_all_keys() or []
    except Exception:
        return
    for key in keys:
        try:
            key_id = int(key.get('key_id') or 0)
            if not key_id:
                continue
            stats = await traffic_service.get_key_traffic_stats(key_id)
            if not stats.get("available"):
                continue
            host = tr_repo.get_host_hybrid_settings(key.get('host_name')) or {}
            threshold_pct = int(host.get('low_traffic_threshold_percent') or 10)
            uid = int(key.get('user_id') or 0)
            if not uid or str(uid).startswith("999"):
                continue
            for ttype, block in (("wifi", stats.get("wifi")), ("lte", stats.get("lte"))):
                if not block:
                    continue
                limit = int(block.get("limit_bytes") or 0)
                if limit <= 0:
                    continue
                remaining_pct = (int(block.get("remaining_bytes") or 0) / limit) * 100
                if remaining_pct > threshold_pct:
                    continue
                name = stats.get(f"{ttype}_name") or ttype
                if int(block.get("remaining_bytes") or 0) <= 0:
                    text = (f"📉 <b>Трафик закончился</b>\n"
                            f"{name}: доступный объём исчерпан.")
                else:
                    text = (f"⚠️ <b>Мало трафика</b>\n"
                            f"{name}: осталось {block.get('remaining_gb', 0):.1f} ГБ.")
                if stats.get("purchase_enabled"):
                    from aiogram.utils.keyboard import InlineKeyboardBuilder
                    kb = InlineKeyboardBuilder()
                    kb.button(text="🛒 Купить гигабайты", callback_data=f"buy_traffic_{key_id}")
                    kb.adjust(1)
                    try:
                        await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb.as_markup())
                    except Exception:
                        pass
                else:
                    text += "\nОбъём обновится при следующем сбросе или продлении."
                    try:
                        await bot.send_message(uid, text, parse_mode="HTML")
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Scheduler: low-traffic notify ошибка для key {key.get('key_id')}: {e}")


async def _maybe_run_hybrid_migration_batch():
    """Обработка гибридной миграции: батчи по BATCH_SIZE ключей за проход (Этап 9 ТЗ).

    state хранится в bot_settings; если миграция активна (host задан, paused=False),
    scheduler вызывает run_migration_batch() на каждом тике (раз в CHECK_INTERVAL_SECONDS).
    """
    global _last_hybrid_migration_at
    now = get_msk_time()
    if _last_hybrid_migration_at and (now - _last_hybrid_migration_at).total_seconds() < CHECK_INTERVAL_SECONDS:
        return
    _last_hybrid_migration_at = now

    from shop_bot.modules import hybrid_migration
    state = hybrid_migration.get_migration_state()
    if not state.get("host") or state.get("paused"):
        return

    logger.info("Scheduler: запуск hybrid migration batch (host=%s, offset=%s)",
                state.get("host"), state.get("offset"))
    result = await hybrid_migration.run_migration_batch()
    logger.info("Scheduler: hybrid migration batch — %s", result)

    if result.get("done"):
        logger.info("Scheduler: hybrid migration завершена для host=%s", state.get("host"))


async def _maybe_run_pair_repair():
    """Автоматический repair гибридных пар в статусе repair_required (Этап 8 ТЗ).

    Раз в ~10 минут находит пары со статусом repair_required и пытается
    восстановить отсутствующую сторону через hybrid_service.repair_pair().
    При неудаче — пара остаётся в repair_required, логируется ошибка.
    """
    global _last_pair_repair_at
    now = get_msk_time()
    if _last_pair_repair_at and (now - _last_pair_repair_at).total_seconds() < 600:
        return
    _last_pair_repair_at = now

    from shop_bot.modules import hybrid_service
    from shop_bot.data_manager import traffic_repository as tr_repo
    from shop_bot.modules import domain_constants as const

    try:
        pairs = tr_repo.list_pairs_by_status(const.PAIR_REPAIR_REQUIRED)
    except Exception as e:
        logger.debug("Scheduler: pair repair — не удалось получить repair_required пары: %s", e)
        return
    if not pairs:
        return

    logger.info("Scheduler: pair repair — найдено %d пар в статусе repair_required", len(pairs))
    for pair in pairs:
        try:
            ok = await hybrid_service.repair_pair(pair)
            if ok:
                logger.info("Scheduler: pair repair — пара %s восстановлена", pair.get("pair_id"))
            else:
                logger.warning("Scheduler: pair repair — пара %s не восстановлена, остаётся в repair_required",
                               pair.get("pair_id"))
        except Exception as exc:
            logger.error("Scheduler: pair repair — ошибка для пары %s: %s", pair.get("pair_id"), exc)


async def _maybe_run_server_migration():
    """Обработка переноса ключей между хостами (server migration).

    state хранится в bot_settings; если миграция активна, scheduler вызывает
    run_migration_batch() на каждом тике.
    """
    global _last_server_migration_at
    now = get_msk_time()
    if _last_server_migration_at and (now - _last_server_migration_at).total_seconds() < CHECK_INTERVAL_SECONDS:
        return
    _last_server_migration_at = now

    from shop_bot.modules import server_migration
    state = server_migration.get_state()
    if not state.get("source_host") or state.get("paused"):
        return

    logger.info("Scheduler: запуск server migration batch (%s -> %s, offset=%s)",
                state.get("source_host"), state.get("target_host"), state.get("offset"))
    result = await server_migration.run_migration_batch()
    logger.info("Scheduler: server migration batch — %s", result)

    if result.get("done"):
        logger.info("Scheduler: server migration завершена")


async def _maybe_run_periodic_speedtests():
    global _last_speedtests_run_at
    now = get_msk_time()
    
    if _last_speedtests_run_at is None:
        if (now - _scheduler_start_time).total_seconds() < 120:
            return
    elif (now - _last_speedtests_run_at).total_seconds() < SPEEDTEST_INTERVAL_SECONDS:
        return
    try:
        await _run_speedtests_for_all_ssh_targets()
        _last_speedtests_run_at = now
    except Exception as e:
        logger.error(f"Scheduler: Ошибка запуска speedtests: {e}", exc_info=True)

async def _run_speedtests_for_all_hosts():
    hosts = rw_repo.get_all_hosts()
    if not hosts:
        logger.debug("Scheduler: Нет хостов для измерений скорости.")
        return
    logger.info(f"Scheduler: Запускаю speedtest для {len(hosts)} хост(ов)...")
    for h in hosts:
        host_name = h.get('host_name')
        if not host_name:
            continue
        try:
            logger.info(f"Scheduler: Speedtest для '{host_name}' запущен...")

            try:
                async with asyncio.timeout(180):
                    res = await speedtest_runner.run_both_for_host(host_name)
            except AttributeError:

                res = await asyncio.wait_for(speedtest_runner.run_both_for_host(host_name), timeout=180)
            ok = res.get('ok')
            err = res.get('error')
            if ok:
                logger.info(f"Scheduler: Speedtest для '{host_name}' завершён успешно")
            else:
                logger.warning(f"Scheduler: Speedtest для '{host_name}' завершён с ошибками: {err}")
        except asyncio.TimeoutError:
            logger.warning(f"Scheduler: Таймаут speedtest для хоста '{host_name}'")
        except Exception as e:
            logger.error(f"Scheduler: Ошибка выполнения speedtest для '{host_name}': {e}", exc_info=True)

async def _run_speedtests_for_all_ssh_targets():
    targets = rw_repo.get_all_ssh_targets() or []
    if not targets:
        logger.debug("Scheduler: Нет SSH-целей для измерений скорости.")
        return
    logger.info(f"Scheduler: Запускаю SSH speedtest для {len(targets)} цел(ей)...")
    for t in targets:
        target_name = (t.get('target_name') or '').strip()
        if not target_name:
            continue
        try:
            logger.info(f"Scheduler: SSH speedtest для цели '{target_name}' запущен...")
            try:
                async with asyncio.timeout(180):
                    res = await speedtest_runner.run_and_store_ssh_speedtest_for_target(target_name)
            except AttributeError:
                res = await asyncio.wait_for(speedtest_runner.run_and_store_ssh_speedtest_for_target(target_name), timeout=180)
            ok = res.get('ok')
            err = res.get('error')
            if ok:
                logger.info(f"Scheduler: SSH speedtest для цели '{target_name}' завершён успешно")
            else:
                logger.warning(f"Scheduler: SSH speedtest для цели '{target_name}' завершён с ошибками: {err}")
        except asyncio.TimeoutError:
            logger.warning(f"Scheduler: Таймаут SSH speedtest для цели '{target_name}'")
        except Exception as e:
            logger.error(f"Scheduler: Ошибка выполнения SSH speedtest для цели '{target_name}': {e}", exc_info=True)



async def _maybe_collect_resource_metrics(bot: Bot | None):
    """Периодический сбор метрик (локально + SSH на хостах) и отправка алертов при превышении порогов.
    Читает настройки:
      - monitoring_enabled (true/false)
      - monitoring_interval_sec (по умолчанию 300)
      - monitoring_cpu_threshold, monitoring_mem_threshold, monitoring_disk_threshold (проценты)
      - monitoring_alert_cooldown_sec (по умолчанию 3600)
    """
    global _last_resource_collect_at, _last_resource_alert_at
    try:
        enabled = (rw_repo.get_setting("monitoring_enabled") or "true").strip().lower() == "true"
        if not enabled:
            return
        try:
            interval_sec = int((rw_repo.get_setting("monitoring_interval_sec") or "300").strip() or 300)
        except Exception:
            interval_sec = 300
        now = get_msk_time()
        if _last_resource_collect_at and (now - _last_resource_collect_at).total_seconds() < max(30, interval_sec):
            return


        def _to_int(s: str | None, default: int) -> int:
            try:
                return int((s or "").strip() or default)
            except Exception:
                return default
        cpu_thr = _to_int(rw_repo.get_setting("monitoring_cpu_threshold"), 90)
        mem_thr = _to_int(rw_repo.get_setting("monitoring_mem_threshold"), 90)
        disk_thr = _to_int(rw_repo.get_setting("monitoring_disk_threshold"), 90)
        cooldown = _to_int(rw_repo.get_setting("monitoring_alert_cooldown_sec"), 3600)


        try:
            local = await asyncio.to_thread(resource_monitor.get_local_metrics)
            cpu_p = (local.get('cpu') or {}).get('percent')
            mem_p = (local.get('memory') or {}).get('percent')
            disks = local.get('disks') or []
            disk_p = max((d.get('percent') or 0) for d in disks) if disks else None
            rw_repo.insert_resource_metric(
                'local', 'panel',
                cpu_percent=cpu_p, mem_percent=mem_p, disk_percent=disk_p,
                load1=(local.get('cpu') or {}).get('loadavg',[None])[0] if (local.get('cpu') or {}).get('loadavg') else None,
                net_bytes_sent=(local.get('net') or {}).get('bytes_sent'),
                net_bytes_recv=(local.get('net') or {}).get('bytes_recv'),
                raw_json=json.dumps(local, ensure_ascii=False)
            )
            await _maybe_alert(bot, scope='local', name='panel', cpu=cpu_p, mem=mem_p, disk=disk_p,
                               cpu_thr=cpu_thr, mem_thr=mem_thr, disk_thr=disk_thr, cooldown_sec=cooldown)
        except Exception:
            logger.debug("Scheduler: не удалось собрать локальные метрики", exc_info=True)


        hosts = rw_repo.get_all_hosts() or []
        for h in hosts:
            name = h.get('host_name') or ''
            if not name:
                continue

            if not (h.get('ssh_host') and h.get('ssh_user')):
                continue
            try:
                rm = await asyncio.to_thread(resource_monitor.get_remote_metrics_for_host, name)
                mem_p = (rm.get('memory') or {}).get('percent')
                disks = rm.get('disks') or []
                disk_p = max((d.get('percent') or 0) for d in disks) if disks else None
                rw_repo.insert_resource_metric(
                    'host', name,
                    mem_percent=mem_p,
                    disk_percent=disk_p,
                    load1=(rm.get('loadavg') or [None])[0],
                    raw_json=json.dumps(rm, ensure_ascii=False)
                )
                await _maybe_alert(bot, scope='host', name=name, cpu=None, mem=mem_p, disk=disk_p,
                                   cpu_thr=cpu_thr, mem_thr=mem_thr, disk_thr=disk_thr, cooldown_sec=cooldown)
            except Exception:
                logger.debug("Scheduler: не удалось собрать метрики хоста для %s", name, exc_info=True)

        _last_resource_collect_at = now
    except Exception:
        logger.error("Scheduler: Ошибка сбора метрик ресурсов", exc_info=True)


async def _maybe_run_daily_backup(bot: Bot):
    """Автобэкап базы и отправка админам. Интервал задаётся в настройках backup_interval_days и backup_interval_unit."""
    global _last_backup_run_at
    now = get_msk_time()
    try:
        s = rw_repo.get_setting("backup_interval_days") or "1"
        interval_value = int(str(s).strip() or "1")
    except Exception:
        interval_value = 1
    if interval_value <= 0:
        return
    unit = (rw_repo.get_setting("backup_interval_unit") or "days").strip().lower()
    if unit == "hours":
        interval_seconds = max(1, interval_value) * 3600
    else:
        interval_seconds = max(1, interval_value) * 24 * 3600
    if _last_backup_run_at and (now - _last_backup_run_at).total_seconds() < interval_seconds:
        return
    try:
        # Этап 8 ТЗ: перед архивом собираем снимки состояния Remnawave
        zip_path = await backup_manager.create_backup_with_snapshots(bot, source="scheduled")
        if zip_path and zip_path.exists():
            try:
                sent = await backup_manager.send_backup_to_admins(bot, zip_path)
                logger.info(f"Scheduler: Создан бэкап {zip_path.name}, отправлен {sent} адм.")
            except Exception as e:
                logger.error(f"Scheduler: Не удалось отправить бэкап: {e}")
            try:
                backup_manager.cleanup_old_backups(keep=7)
            except Exception:
                pass
        _last_backup_run_at = now
    except Exception as e:
        logger.error(f"Scheduler: Критическая ошибка при создании и отправке бэкапа: {e}", exc_info=True)


async def _maybe_alert(
    bot: Bot | None,
    *,
    scope: str,
    name: str,
    cpu: float | None,
    mem: float | None,
    disk: float | None,
    cpu_thr: int,
    mem_thr: int,
    disk_thr: int,
    cooldown_sec: int,
):
    if not bot:
        return
    

    cpu_warning = max(50, cpu_thr - 20)
    mem_warning = max(50, mem_thr - 20)
    disk_warning = max(50, disk_thr - 20)
    
    breaches: list[dict] = []
    alerts: list[dict] = []
    

    if cpu is not None:
        if cpu >= cpu_thr:
            breaches.append({
                'type': 'Процессор',
                'value': cpu,
                'threshold': cpu_thr,
                'level': 'critical',
                'emoji': '🔴'
            })
        elif cpu >= cpu_warning:
            alerts.append({
                'type': 'Процессор',
                'value': cpu,
                'threshold': cpu_warning,
                'level': 'warning',
                'emoji': '🟡'
            })
    

    if mem is not None:
        if mem >= mem_thr:
            breaches.append({
                'type': 'Память',
                'value': mem,
                'threshold': mem_thr,
                'level': 'critical',
                'emoji': '🔴'
            })
        elif mem >= mem_warning:
            alerts.append({
                'type': 'Память',
                'value': mem,
                'threshold': mem_warning,
                'level': 'warning',
                'emoji': '🟡'
            })
    

    if disk is not None:
        if disk >= disk_thr:
            breaches.append({
                'type': 'Диск',
                'value': disk,
                'threshold': disk_thr,
                'level': 'critical',
                'emoji': '🔴'
            })
        elif disk >= disk_warning:
            alerts.append({
                'type': 'Диск',
                'value': disk,
                'threshold': disk_warning,
                'level': 'warning',
                'emoji': '🟡'
            })
    

    if breaches:
        key = (scope, name, "critical", ",".join(sorted([b['type'] for b in breaches])))
        now = get_msk_time()
        last = _last_resource_alert_at.get(key)
        if not last or (now - last).total_seconds() >= max(60, cooldown_sec):
            _last_resource_alert_at[key] = now
            await _send_alert(bot, scope, name, breaches, 'critical')
    

    if alerts:
        key = (scope, name, "warning", ",".join(sorted([a['type'] for a in alerts])))
        now = get_msk_time()
        last = _last_resource_alert_at.get(key)
        if not last or (now - last).total_seconds() >= max(300, cooldown_sec * 2):
            _last_resource_alert_at[key] = now
            await _send_alert(bot, scope, name, alerts, 'warning')


async def _send_alert(bot: Bot, scope: str, name: str, issues: list[dict], level: str):
    """Отправка алерта админам"""
    try:
        admin_ids = rw_repo.get_admin_ids() or set()
    except Exception:
        admin_ids = set()
    if not admin_ids:
        return
    

    if level == 'critical':
        header_emoji = "🚨"
        header_text = "КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ"
    else:
        header_emoji = "⚠️"
        header_text = "ПРЕДУПРЕЖДЕНИЕ"
    

    if scope == 'local':
        obj_name = f"🖥️ Панель ({name})"
    elif scope == 'host':
        obj_name = f"🖥️ Хост {name}"
    elif scope == 'target':
        obj_name = f"🔌 SSH-цель {name}"
    else:
        obj_name = f"❓ {scope}:{name}"
    

    text_lines = [
        f"{header_emoji} <b>{header_text}</b>",
        "",
        f"🎯 <b>Объект:</b> {obj_name}",
        f"⏰ <b>Время:</b> <code>{get_msk_time().strftime('%d.%m.%Y %H:%M:%S')}</code>",
        "",
        "📊 <b>Проблемы:</b>"
    ]
    
    for issue in issues:
        emoji = issue['emoji']
        type_name = issue['type']
        value = issue['value']
        threshold = issue['threshold']
        text_lines.append(f"  {emoji} <b>{type_name}:</b> {value:.1f}% (порог: {threshold}%)")
    

    text_lines.extend([
        "",
        "💡 <b>Рекомендации:</b>",
        "• Проверьте нагрузку на систему",
        "• Освободите место на диске",
        "• Перезапустите сервисы при необходимости"
    ])
    
    text = "\n".join(text_lines)
    

    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode='HTML')
        except Exception:
            continue
