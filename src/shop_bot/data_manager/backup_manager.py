import logging
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from . import remnawave_repository as rw_repo

logger = logging.getLogger(__name__)


BACKUPS_DIR = Path("/app/project/backups")
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


DB_FILE: Path = rw_repo.DB_FILE
ZIP_COMPRESSION = getattr(zipfile, "ZIP_LZMA", zipfile.ZIP_DEFLATED)
ZIP_COMPRESSLEVEL = 9


def get_msk_time() -> datetime:
    return datetime.now(timezone(timedelta(hours=3)))


def _timestamp() -> str:
    return get_msk_time().strftime("%Y%m%d-%H%M%S")


def _write_compressed_backup(zip_path: Path, db_path: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path, 'w', compression=ZIP_COMPRESSION) as zf:
            zf.write(db_path, arcname=db_path.name)
    except RuntimeError:
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESSLEVEL) as zf:
            zf.write(db_path, arcname=db_path.name)


def create_backup_file() -> Path | None:
    """
    Создаёт zip-архив с консистентной копией SQLite-БД.
    Возвращает путь к архиву или None при ошибке.
    """
    try:
        if not DB_FILE.exists():
            logger.error(f"Бэкап: файл БД не найден: {DB_FILE}")
            return None
        ts = _timestamp()
        tmp_db_copy = BACKUPS_DIR / f"users-{ts}.db"
        zip_path = BACKUPS_DIR / f"db-backup-{ts}.zip"


        with sqlite3.connect(DB_FILE) as src:
            with sqlite3.connect(tmp_db_copy) as dst:
                src.backup(dst)


        _write_compressed_backup(zip_path, tmp_db_copy)


        try:
            tmp_db_copy.unlink(missing_ok=True)
        except Exception:
            pass

        logger.info(f"Бэкап: создан файл {zip_path}")
        return zip_path
    except Exception as e:
        logger.error(f"Бэкап: не удалось создать архив: {e}", exc_info=True)
        return None


# ===== REMNAVE STATE SNAPSHOTS ПЕРЕД БЭКАПОМ (Этап 8 ТЗ) =====

async def collect_remnawave_snapshots(backup_run_id: int) -> str:
    """Сбор снимков состояния Remnawave перед созданием копии БД.

    Возвращает snapshot_status: complete | incomplete | failed.
    При ошибке конкретного пользователя продолжаем сбор.
    """
    import asyncio
    from shop_bot.modules import remnawave_api
    from shop_bot.data_manager import traffic_repository as tr_repo
    from shop_bot.modules import domain_constants as const
    from shop_bot.modules import utils_common as uc

    errors: list[str] = []
    keys = rw_repo.get_all_keys() or []
    for key in keys:
        key_id = int(key.get('key_id') or 0)
        if not key_id:
            continue
        try:
            usage = await remnawave_api.get_user_traffic_usage(
                key.get('remnawave_user_uuid'), host_name=key.get('host_name'))
            if usage is None:
                raise RuntimeError("user not found in panel")
            tr_repo.record_state_snapshot({
                "backup_run_id": backup_run_id, "key_id": key_id, "pair_id": None,
                "target_role": const.ROLE_PRIMARY,
                "remnawave_user_id": str(key.get('remnawave_user_uuid')),
                "traffic_limit_bytes": usage.get("limit_bytes"),
                "used_traffic_bytes": usage.get("used_bytes"),
                "status": usage.get("status"), "expire_at": usage.get("expire_at"),
                "payload": usage,
            })
        except Exception as exc:
            errors.append(f"key {key_id}: {exc}")
            tr_repo.record_state_snapshot({
                "backup_run_id": backup_run_id, "key_id": key_id, "pair_id": None,
                "target_role": const.ROLE_PRIMARY,
                "remnawave_user_id": str(key.get('remnawave_user_uuid')),
                "collection_error": str(exc)[:500],
            })
        # гибридные стороны активных пар
        try:
            pair = tr_repo.get_pair_by_primary_key(key_id)
            if pair and pair.get("status") == const.PAIR_ACTIVE:
                usage = await remnawave_api.get_user_traffic_usage(
                    pair["hybrid_remnawave_user_id"], host_name=pair["host_name"])
                if usage is None:
                    raise RuntimeError("hybrid user not found")
                tr_repo.record_state_snapshot({
                    "backup_run_id": backup_run_id, "key_id": key_id,
                    "pair_id": pair["pair_id"], "target_role": const.ROLE_HYBRID,
                    "remnawave_user_id": pair["hybrid_remnawave_user_id"],
                    "traffic_limit_bytes": usage.get("limit_bytes"),
                    "used_traffic_bytes": usage.get("used_bytes"),
                    "status": usage.get("status"), "expire_at": usage.get("expire_at"),
                    "payload": usage,
                })
        except Exception as exc:
            errors.append(f"pair key {key_id}: {exc}")

    status = "complete" if not errors else ("incomplete" if len(errors) < max(1, len(keys)) else "failed")
    if errors:
        tr_repo.update_backup_run(
            backup_run_id, snapshot_status=status,
            snapshot_error="; ".join(errors[:20])[:2000])
        logger.warning("Бэкап snapshots: статус %s, ошибок %d", status, len(errors))
    else:
        tr_repo.update_backup_run(backup_run_id, snapshot_status="complete")
    return status


async def create_backup_with_snapshots(bot, source: str = "scheduled", requested_by: int | None = None) -> Path | None:
    """Полный цикл: backup_run -> snapshots -> архив с manifest."""
    import json as _json
    from shop_bot.data_manager import traffic_repository as tr_repo
    from shop_bot.data_manager.database import get_setting
    from shop_bot.modules.domain_constants import SCHEMA_VERSION_CURRENT

    run_id = tr_repo.create_backup_run(source, requested_by)
    if run_id is None:
        return None

    status = await collect_remnawave_snapshots(run_id)

    zip_path = create_backup_file()
    if not zip_path:
        tr_repo.update_backup_run(run_id, snapshot_status="failed", snapshot_error="archive creation failed", completed=True)
        return None

    # manifest в archive metadata
    manifest = {
        "backup_run_id": run_id,
        "created_at": uc_now_str(),
        "snapshot_status": status,
        "schema_version": SCHEMA_VERSION_CURRENT,
        "archive_name": zip_path.name,
    }
    tr_repo.update_backup_run(run_id, snapshot_status=status, archive_name=zip_path.name, completed=True)
    try:
        manifest_path = BACKUPS_DIR / (zip_path.stem + ".manifest.json")
        manifest_path.write_text(_json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    if status == "incomplete" and bot:
        try:
            admins = list(rw_repo.get_admin_ids() or [])
        except Exception:
            admins = []
        for admin_id in admins:
            try:
                await bot.send_message(int(admin_id),
                    f"⚠️ Бэкап создан, но снимок Remnawave неполный (run #{run_id}). "
                    f"Проверьте ошибки в таблице backup_runs.")
            except Exception:
                continue
    return zip_path


def uc_now_str() -> str:
    return get_msk_time().strftime("%Y-%m-%d %H:%M:%S")


def cleanup_old_backups(keep: int = 7) -> None:
    """Хранить только N последних архивов, остальные удалять."""
    try:
        files = sorted(BACKUPS_DIR.glob("db-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[keep:]:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Бэкап: не удалось очистить старые архивы: {e}")


async def send_backup_to_admins(bot: Bot, zip_path: Path) -> int:
    """
    Отправляет архив всем администраторам. Возвращает число успешных отправок.
    """
    cnt = 0
    try:
        try:
            admin_ids = list(rw_repo.get_admin_ids() or [])
        except Exception:
            admin_ids = []
        if not admin_ids:
            logger.warning("Бэкап: нет администраторов для отправки архива")
            return 0
        caption = f"🗄 Бэкап БД: {zip_path.name}"
        file = FSInputFile(str(zip_path))
        for uid in admin_ids:
            try:
                await bot.send_document(chat_id=int(uid), document=file, caption=caption)
                cnt += 1
            except Exception as e:
                logger.error(f"Бэкап: не удалось отправить администратору {uid}: {e}")
        return cnt
    except Exception as e:
        logger.error(f"Бэкап: ошибка при рассылке архива: {e}", exc_info=True)
        return cnt


def validate_db_file(db_path: Path) -> tuple[bool, str, str]:
    """
    Валидация файла БД. Возвращает (ok, status, message).

    Статусы:
      - 'ok':        полностью совместимая БД (schema >= 2, все таблицы)
      - 'legacy':    рабочая БД старой версии (core-таблицы есть, schema < 2);
                     принимается с миграцией вперёд + предупреждением
      - 'incomplete':snapshot неполный (только для архивов с manifest)
      - 'invalid':   битый/несовместимый файл (нет core-таблиц)
    """
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()

            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            present = {row[0] for row in cur.fetchall()}

            # core-таблицы обязательны всегда
            core = {'users', 'vpn_keys', 'transactions', 'bot_settings', 'xui_hosts'}
            missing_core = core - present
            if missing_core:
                return False, 'invalid', f"отсутствуют core-таблицы: {sorted(missing_core)}"

            if not ('users' in present and 'bot_settings' in present):
                return False, 'invalid', "нет users/bot_settings"

            # schema version
            version = 0
            try:
                cur.execute("SELECT value FROM bot_settings WHERE key='schema_version'")
                row = cur.fetchone()
                version = int((row[0] if row else "0") or 0)
            except Exception:
                version = 0
            from shop_bot.modules.domain_constants import SCHEMA_VERSION_MIN_SUPPORTED, SCHEMA_VERSION_CURRENT

            if version < int(SCHEMA_VERSION_MIN_SUPPORTED):
                missing_new = {'traffic_purchases', 'payment_fulfillment_jobs',
                               'hybrid_subscription_pairs'} - present
                return True, 'legacy', (
                    f"схема БД (v{version}) старее минимально поддерживаемой "
                    f"(v{SCHEMA_VERSION_MIN_SUPPORTED}); отсутствуют таблицы нового домена: "
                    f"{sorted(missing_new)}; БД будет принята и мигрирована вперёд")

            # совместимая схема, но проверим наличие новых таблиц (не маскируем рассинхрон)
            missing_new = {'traffic_purchases', 'payment_fulfillment_jobs',
                           'hybrid_subscription_pairs'} - present
            if missing_new:
                return True, 'legacy', (
                    f"schema_version={version}, но отсутствуют таблицы нового домена: "
                    f"{sorted(missing_new)}; будет выполнена миграция")

            return True, 'ok', f"БД совместима (schema v{version}/{SCHEMA_VERSION_CURRENT})"
    except Exception as e:
        logger.error(f"Восстановление: ошибка валидации файла БД: {e}")
        return False, 'invalid', f"ошибка чтения файла: {e}"


def check_backup_snapshot_status(archive_path: Path) -> str | None:
    """Прочитать snapshot status из manifest рядом с архивом (если есть)."""
    manifest_path = archive_path.with_name(archive_path.stem + ".manifest.json")
    try:
        import json as _json
        if manifest_path.exists():
            data = _json.loads(manifest_path.read_text(encoding="utf-8"))
            return data.get("snapshot_status")
    except Exception:
        pass
    return None


def restore_from_file(uploaded_path: Path, *, allow_incomplete: bool = False) -> tuple[bool, str]:
    """
    Восстанавливает основную БД из переданного файла .db или .zip (внутри .db).
    Делает резервную копию текущей БД на случай отката.

    Политика (обновлено по требованию владельца):
      - битой БД (нет core-таблиц) — отказ;
      - старой/legacy БД (schema < 2 или нет таблиц нового домена) — ПРИНИМАЕТСЯ
        с предупреждением и мигрируется вперёд (run_migration);
      - архив с incomplete-снимком — принимается, но требует явного
        allow_incomplete=True (кнопка подтверждения в UI).
    Возвращает (ok, message) — message показывается администратору.
    """
    tmp_dir: Path | None = None
    try:
        if not uploaded_path.exists():
            logger.error(f"Восстановление: файл не найден: {uploaded_path}")
            return False, "файл не найден"

        # incomplete snapshot: предупреждаем, но принимаем (требуется явное подтверждение)
        snapshot_warning = ""
        snap = check_backup_snapshot_status(uploaded_path)
        if snap == "incomplete":
            if not allow_incomplete:
                return False, ("бэкап содержит НЕПОЛНЫЙ снимок Remnawave. "
                               "Подтвердите восстановление неполного бэкапа.")
            snapshot_warning = "Снимок Remnawave в бэкапе неполный; часть данных панели могла не сохраниться."

        tmp_dir = BACKUPS_DIR / f"restore-{_timestamp()}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        candidate_db: Path | None = None

        if uploaded_path.suffix.lower() == '.zip':
            try:
                with zipfile.ZipFile(uploaded_path, 'r') as zf:
                    for n in zf.namelist():
                        if n.lower().endswith('.db'):
                            zf.extract(n, path=tmp_dir)
                            candidate_db = tmp_dir / n
                            break
            except Exception as e:
                logger.error(f"Восстановление: не удалось распаковать архив: {e}")
                return False, "не удалось распаковать архив"
        else:

            candidate_db = uploaded_path

        if not candidate_db or not candidate_db.exists():
            logger.error("Восстановление: в переданном файле не найдено .db")
            return False, "в файле не найдена база данных"

        ok, status, message = validate_db_file(candidate_db)
        if not ok:
            logger.error(f"Восстановление: файл БД не прошёл проверку: {message}")
            return False, f"файл не прошёл проверку: {message}"

        if status == 'legacy':
            logger.warning("Восстановление: принята БД старой схемы: %s", message)

        # резервная копия текущей БД перед заменой
        backup_before = BACKUPS_DIR / f"before-restore-{_timestamp()}.zip"
        cur_backup = create_backup_file()
        if cur_backup and cur_backup.exists():
            try:
                shutil.copy(cur_backup, backup_before)
            except Exception:
                pass

        with sqlite3.connect(candidate_db) as src:
            with sqlite3.connect(DB_FILE) as dst:
                src.backup(dst)

        # миграция ТОЛЬКО вперёд: для legacy создаёт таблицы нового домена,
        # идемпотентна для уже совместимой БД
        migration_error = ""
        try:
            rw_repo.run_migration()
            logger.info("Восстановление: миграция выполнена")
        except Exception as e:
            migration_error = str(e)
            logger.error("Восстановление: ошибка миграции: %s", e)

        # контрольная проверка после миграции
        post_ok, post_status, post_msg = validate_db_file(DB_FILE)
        final_ok = post_ok and post_status == 'ok'
        if not final_ok and not migration_error:
            logger.warning("Восстановление: после миграции статус %s (%s)", post_status, post_msg)

        # audit восстановления
        try:
            from shop_bot.data_manager import database as _db
            _db.update_setting("last_restore_info", _json_dump({
                "restored_at": uc_now_str(),
                "source": str(uploaded_path.name),
                "source_status": status,
                "message": message,
                "snapshot": snap,
                "migration_error": migration_error,
            }))
        except Exception:
            pass

        parts = []
        if status == 'legacy':
            parts.append("⚠️ Загружена БД СТАРОЙ версии: " + message + ".")
            parts.append("Она принята как основная и мигрирована к текущей схеме; "
                         "данные пользователей сохранены, функции нового домена включены.")
        else:
            parts.append("БД совместима: " + message + ".")
        if snapshot_warning:
            parts.append("⚠️ " + snapshot_warning)
        if migration_error:
            parts.append(f"⚠️ Миграция завершилась с ошибкой: {migration_error}. "
                         f"Проверьте логи; текущая БД сохранена в {backup_before.name}.")
        if not final_ok and not migration_error:
            parts.append("⚠️ После миграции БД всё ещё не полностью совместима: " + post_msg)

        logger.info("Восстановление: база данных успешно заменена (статус источника: %s)", status)
        return True, " ".join(parts)
    except Exception as e:
        logger.error(f"Восстановление: ошибка: {e}", exc_info=True)
        return False, f"внутренняя ошибка восстановления: {e}"
    finally:
        if tmp_dir:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


def _json_dump(data: dict) -> str:
    import json as _json
    return _json.dumps(data, ensure_ascii=False)
