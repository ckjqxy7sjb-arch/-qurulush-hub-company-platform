#!/usr/bin/env python3
"""Local backend for the Qurulush Hub company platform.

The server deliberately uses only Python standard-library modules so it can run
on a clean Mac without installing packages. It provides a small but real API:
role-based login, SQLite persistence, business actions, audit, and static files.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shlex
import shutil
import ssl
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from copy import deepcopy
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse
from xml.sax.saxutils import escape as xml_escape

from ops.render_deployment_files import render_deployment_files, validate_domain


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "extracted_dgask"
DEFAULT_DB = ROOT / "company_platform.sqlite3"
DEFAULT_UPLOAD_ROOT = ROOT / "uploads"
DEFAULT_BACKUP_ROOT = ROOT / "backups"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
AV_SCAN_TIMEOUT_SECONDS = 15
STORAGE_SYNC_TIMEOUT_SECONDS = 60
PAYMENT_GATEWAY_TIMEOUT_SECONDS = 60
EDS_SIGN_TIMEOUT_SECONDS = 60
SACC2_SYNC_TIMEOUT_SECONDS = 60
SACC2_STATUS_TIMEOUT_SECONDS = 8
BACKUP_REMOTE_TIMEOUT_SECONDS = 60
SESSION_SECONDS = 8 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILED = 5
LOGIN_LOCK_SECONDS = 10 * 60
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".zip", ".txt"}
EXCHANGE_SOURCES = {"ДГАСК", "Министерство", "Региональный отдел", "Инспектор"}
EXCHANGE_STATUSES = {"needs_company", "informed", "review", "done"}
TASK_STATUSES = {"new", "in_progress", "done", "blocked"}
TASK_PRIORITIES = {"low", "medium", "high"}
SCHEMA_VERSION = 2
REQUIRED_TABLES = {"app_state", "users", "sessions", "login_attempts", "schema_meta"}
REFERENCE_SOURCE_NOTE = (
    "Рабочий справочник платформы для проектирования процессов. "
    "Не является официальной правовой базой; перед production нужно сверить действующие НПА, тарифы, формы и регламенты ДГАСК/Минстроя КР."
)
DEFAULT_SACC2_PUBLIC_URLS = ("https://sacc2.avn.kg", "https://sacc.avn.kg")
LOCAL_DEMO_PASSWORD = os.environ.get("QH_DEMO_PASSWORD") or secrets.token_urlsafe(24)


SEED: dict[str, Any] = {
    "roles": [
        {"id": "ceo", "title": "Генеральный директор", "perms": ["all"]},
        {
            "id": "chief_engineer",
            "title": "Главный инженер",
            "perms": ["documents:read", "documents:upload", "documents:sign", "requests:reply", "inspections:prepare", "objects:create", "objects:update", "tasks:create", "tasks:update"],
        },
        {
            "id": "foreman",
            "title": "Прораб",
            "perms": ["documents:read", "requests:reply", "inspections:prepare", "objects:create", "objects:update", "tasks:create", "tasks:update"],
        },
        {"id": "brigadier", "title": "Бригадир", "perms": ["tasks:update", "inspections:prepare"]},
        {"id": "accountant", "title": "Бухгалтер", "perms": ["documents:read", "money:pay", "documents:upload"]},
        {
            "id": "lawyer",
            "title": "Юрист / разрешитель",
            "perms": ["documents:read", "requests:create", "requests:reply", "documents:upload", "documents:sign", "money:appeal", "legal:verify"],
        },
    ],
    "users": [
        {"email": "director@company.kg", "password": LOCAL_DEMO_PASSWORD, "name": "Замирбек уулу Максат", "role": "ceo"},
        {"email": "engineer@company.kg", "password": LOCAL_DEMO_PASSWORD, "name": "Асанов Тимур", "role": "chief_engineer"},
        {"email": "foreman@company.kg", "password": LOCAL_DEMO_PASSWORD, "name": "Бекматов Нурлан", "role": "foreman"},
        {"email": "brigadier@company.kg", "password": LOCAL_DEMO_PASSWORD, "name": "Абдиев Руслан", "role": "brigadier"},
        {"email": "accountant@company.kg", "password": LOCAL_DEMO_PASSWORD, "name": "Кадырова Айжан", "role": "accountant"},
        {"email": "lawyer@company.kg", "password": LOCAL_DEMO_PASSWORD, "name": "Сыдыкова Элина", "role": "lawyer"},
    ],
    "objects": [
        {
            "id": 1,
            "name": "ЖК Ала-Тоо Сити, блок Б",
            "address": "Бишкек, ул. Токомбаева",
            "stage": "Монолит",
            "progress": 64,
            "docs": 82,
            "risk": "medium",
            "inspector": "Максатбеков М.",
            "status": "На контроле",
        },
        {
            "id": 2,
            "name": "Школа на 550 мест",
            "address": "Чуйская обл., Сокулук",
            "stage": "Фасад",
            "progress": 78,
            "docs": 91,
            "risk": "low",
            "inspector": "Шергазиев Э.Ш.",
            "status": "Плановая проверка",
        },
        {
            "id": 3,
            "name": "Складской комплекс Север",
            "address": "Бишкек, промзона",
            "stage": "Ввод",
            "progress": 93,
            "docs": 68,
            "risk": "high",
            "inspector": "Мамонова А.",
            "status": "Предписание",
        },
    ],
    "requests": [
        {
            "id": "REQ-1048",
            "title": "Запрос исполнительной документации",
            "object": 1,
            "from": "Инспектор",
            "owner": "Главный инженер",
            "due": "18.09.2026",
            "status": "needs_company",
            "text": "Необходимо приложить журнал производства работ и акты скрытых работ по монолиту.",
            "history": [],
        },
        {
            "id": "REQ-1041",
            "title": "Статус изменён на «Информирован»",
            "object": 1,
            "from": "Министерство",
            "owner": "Прораб",
            "due": "Сегодня",
            "status": "informed",
            "text": "Компания уведомлена о смене ответственного инспектора и сроках ответа.",
            "history": [],
        },
        {
            "id": "REQ-1029",
            "title": "Предоставить подтверждение оплаты ЕРН",
            "object": 3,
            "from": "Министерство",
            "owner": "Бухгалтер",
            "due": "15.09.2026",
            "status": "needs_company",
            "text": "Требуется квитанция и номер платежа по договору внесения в реестр.",
            "history": [],
        },
    ],
    "documents": [
        {"id": "DOC-1", "title": "Заявление о включении в Реестр", "object": 1, "owner": "Юрист / разрешитель", "status": "Принят", "due": "-", "file": "reestr-application.pdf"},
        {"id": "DOC-2", "title": "Разрешение на строительство", "object": 1, "owner": "Генеральный директор", "status": "Действует", "due": "31.12.2026", "file": "permit.pdf"},
        {"id": "DOC-3", "title": "Проектная документация", "object": 1, "owner": "Главный инженер", "status": "Нужно обновить", "due": "18.09.2026", "file": ""},
        {"id": "DOC-4", "title": "Акты скрытых работ", "object": 1, "owner": "Прораб", "status": "Нужен ответ", "due": "18.09.2026", "file": ""},
        {"id": "DOC-7", "title": "Подтверждение оплаты ЕРН", "object": 3, "owner": "Бухгалтер", "status": "Нужен ответ", "due": "15.09.2026", "file": ""},
    ],
    "inspections": [
        {"time": "Сегодня", "title": "Подготовка к контрольной проверке", "object": 3, "type": "Контрольная", "status": "Срочно", "text": "Проверка устранения нарушений по предписанию."},
        {"time": "16.09.2026", "title": "Плановая проверка объекта", "object": 2, "type": "Плановая", "status": "В работе", "text": "Подтвердить состав комиссии от компании."},
    ],
    "tasks": [
        {
            "id": "TASK-1",
            "title": "Подготовить акты скрытых работ",
            "object": 1,
            "owner": "Прораб",
            "due": "18.09.2026",
            "status": "new",
            "priority": "high",
            "source": "REQ-1048",
            "text": "Собрать акты по монолиту и передать главному инженеру для ответа инспектору.",
            "evidence": "",
            "history": [],
        },
        {
            "id": "TASK-2",
            "title": "Фотофиксация устранения нарушений",
            "object": 3,
            "owner": "Бригадир",
            "due": "Сегодня",
            "status": "in_progress",
            "priority": "high",
            "source": "Контрольная проверка",
            "text": "Подготовить фотографии, сертификаты материалов и отметку о готовности объекта.",
            "evidence": "",
            "history": [],
        },
        {
            "id": "TASK-3",
            "title": "Подтвердить состав комиссии",
            "object": 2,
            "owner": "Прораб",
            "due": "16.09.2026",
            "status": "new",
            "priority": "medium",
            "source": "REQ-1033",
            "text": "Согласовать присутствие ответственного лица на плановой проверке.",
            "evidence": "",
            "history": [],
        },
    ],
    "reference": [
        {
            "id": "REF-1",
            "category": "Разрешительные документы",
            "title": "Заявление о включении объекта в реестр / учет",
            "interaction": "Компания -> Министерство / ДГАСК",
            "trigger": "Старт объекта, реконструкция или необходимость официального учета объекта.",
            "responsible": "Юрист / разрешитель",
            "company_action": "Подготовить заявление, правоустанавливающие документы, карточку объекта и контакт ответственного лица.",
            "risk": "Без регистрации объекта последующие статусы, проверки и разрешения могут зависнуть.",
            "source_note": REFERENCE_SOURCE_NOTE,
        },
        {
            "id": "REF-2",
            "category": "Разрешительные документы",
            "title": "Разрешение на строительство",
            "interaction": "Компания -> ДГАСК / уполномоченный орган",
            "trigger": "Перед началом строительно-монтажных работ.",
            "responsible": "Генеральный директор + юрист",
            "company_action": "Собрать проектную документацию, заключения, сведения о подрядчике и подписать пакет через уполномоченное лицо.",
            "risk": "Работы без разрешения создают высокий риск предписания, остановки и штрафа.",
            "source_note": REFERENCE_SOURCE_NOTE,
        },
        {
            "id": "REF-3",
            "category": "Разрешительные документы",
            "title": "Проектная и исполнительная документация",
            "interaction": "Компания -> Инспектор",
            "trigger": "Запрос инспектора, проверка этапа, скрытые работы, ввод объекта.",
            "responsible": "Главный инженер / прораб",
            "company_action": "Приложить проект, журнал работ, акты скрытых работ, сертификаты материалов и фотофиксацию.",
            "risk": "Неполный комплект ведет к повторному запросу, предписанию или отказу принять этап.",
            "source_note": REFERENCE_SOURCE_NOTE,
        },
        {
            "id": "REF-4",
            "category": "Госпошлины и начисления",
            "title": "Подтверждение оплаты госпошлины / договорной услуги",
            "interaction": "Бухгалтерия компании -> Министерство / ДГАСК",
            "trigger": "Создание заявки, начисление за реестр, разрешение, проверку или иной административный процесс.",
            "responsible": "Бухгалтер",
            "company_action": "Зафиксировать основание, сумму, номер платежа, квитанцию и отправить подтверждение в карточку запроса.",
            "risk": "Без номера платежа и квитанции заявка остается в статусе ожидания или возвращается на доработку.",
            "source_note": REFERENCE_SOURCE_NOTE,
        },
        {
            "id": "REF-5",
            "category": "Штрафы и нарушения",
            "title": "Протокол о нарушении / штраф",
            "interaction": "Инспектор / ДГАСК -> Компания",
            "trigger": "Нарушение сроков уведомления, отсутствие документов, отклонение от проекта, неустраненные замечания.",
            "responsible": "Юрист + бухгалтер + главный инженер",
            "company_action": "Проверить основание, собрать доказательства устранения, выбрать оплату или обжалование, сохранить историю действий.",
            "risk": "Просрочка оплаты или ответа повышает финансовый и регуляторный риск для объекта.",
            "source_note": REFERENCE_SOURCE_NOTE,
        },
        {
            "id": "REF-6",
            "category": "Запросы и уведомления",
            "title": "Уведомление о смене инспектора / статуса",
            "interaction": "Министерство / региональный отдел -> Компания",
            "trigger": "Назначение ответственного, смена статуса, перевод запроса в состояние Информирован.",
            "responsible": "Генеральный директор / главный инженер",
            "company_action": "Подтвердить получение, назначить внутреннего ответственного и создать поручение прорабу или юристу.",
            "risk": "Если уведомление не попадет в работу, компания пропустит срок ответа или проверки.",
            "source_note": REFERENCE_SOURCE_NOTE,
        },
        {
            "id": "REF-7",
            "category": "Проверки",
            "title": "Плановая, внеплановая или контрольная проверка",
            "interaction": "Инспектор -> Прораб / главный инженер",
            "trigger": "График проверки, жалоба, контроль устранения предписания или приемка этапа.",
            "responsible": "Прораб + бригадир",
            "company_action": "Подготовить доступ на объект, ответственного представителя, фото, журналы, акты и перечень устраненных замечаний.",
            "risk": "Неподготовленный объект увеличивает риск предписания, повторной проверки и финансовых санкций.",
            "source_note": REFERENCE_SOURCE_NOTE,
        },
        {
            "id": "REF-8",
            "category": "Роли и доступы",
            "title": "Внутреннее поручение по запросу инспектора",
            "interaction": "Генеральный директор / главный инженер -> прораб / бригадир / бухгалтер / юрист",
            "trigger": "Любой внешний запрос, штраф, проверка, уведомление или недостающий документ.",
            "responsible": "Назначенный исполнитель",
            "company_action": "Создать поручение с объектом, сроком, приоритетом и обязательным подтверждением выполнения.",
            "risk": "Без ответственного и доказательства исполнения нельзя восстановить цепочку действий компании.",
            "source_note": REFERENCE_SOURCE_NOTE,
        },
    ],
    "money": [
        {"id": "PAY-1", "title": "Протокол PR-2026-088: нарушение сроков уведомления", "object": 3, "amount": 45000, "owner": "Юрист / Бухгалтер", "status": "К оплате", "due": "20.09.2026"},
        {"id": "PAY-2", "title": "ЕРН: договор внесения в реестр", "object": 3, "amount": 126000, "owner": "Бухгалтер", "status": "Нужна квитанция", "due": "15.09.2026"},
        {"id": "PAY-3", "title": "Госпошлина: подтверждение ИЖС", "object": 2, "amount": 3200, "owner": "Бухгалтер", "status": "Оплачено", "due": "-", "payment_no": "SEED-2026-003", "paid_at": "2026-09-12 10:20:00", "paid_by": "Кадырова Айжан", "history": []},
    ],
    "team": [
        {"id": "USR-1", "name": "Замирбек уулу Максат", "email": "director@company.kg", "role": "Генеральный директор", "access": "Полный", "objects": "Все объекты", "object_ids": [], "last": "сегодня 09:55"},
        {"id": "USR-2", "name": "Асанов Тимур", "email": "engineer@company.kg", "role": "Главный инженер", "access": "Технический контур", "objects": "Все объекты", "object_ids": [], "last": "сегодня 08:40"},
        {"id": "USR-3", "name": "Бекматов Нурлан", "email": "foreman@company.kg", "role": "Прораб", "access": "Объект и проверки", "objects": "ЖК Ала-Тоо Сити, блок Б; Школа на 550 мест", "object_ids": [1, 2], "last": "вчера 18:10"},
        {"id": "USR-4", "name": "Абдиев Руслан", "email": "brigadier@company.kg", "role": "Бригадир", "access": "Исполнение задач", "objects": "Складской комплекс Север", "object_ids": [3], "last": "вчера 17:44"},
        {"id": "USR-5", "name": "Кадырова Айжан", "email": "accountant@company.kg", "role": "Бухгалтер", "access": "Платежи и документы", "objects": "Все объекты", "object_ids": [], "last": "вчера 15:12"},
        {"id": "USR-6", "name": "Сыдыкова Элина", "email": "lawyer@company.kg", "role": "Юрист / разрешитель", "access": "Запросы и заявления", "objects": "Все объекты", "object_ids": [], "last": "12.09.2026"},
    ],
    "notifications": [
        {"time": "09:55", "from": "Министерство", "title": "Ответственный изменён", "text": "По объекту ЖК Ала-Тоо Сити назначен новый ответственный.", "urgent": True, "read": False},
        {"time": "09:52", "from": "Инспектор", "title": "Запрос документов", "text": "Приложите акты скрытых работ и журнал производства работ.", "urgent": True, "read": False},
    ],
    "audit": [
        {"time": "09:55", "actor": "Министерство", "event": "Изменён ответственный инспектор", "object": 1},
        {"time": "09:55", "actor": "Компания", "event": "Статус запроса изменён на Информирован", "object": 1},
    ],
}


ROLE_PERMS = {role["id"]: set(role["perms"]) for role in SEED["roles"]}
ROLE_OBJECT_DEFAULTS: dict[str, list[int] | None] = {
    "ceo": None,
    "chief_engineer": None,
    "accountant": None,
    "lawyer": None,
    "foreman": [1, 2],
    "brigadier": [3],
}

ACCESS_ACTIONS = [
    ("requests", "Запросы", {"requests:create", "requests:reply", "all"}),
    ("documents_read", "Чтение документов", {"documents:read", "all"}),
    ("documents_upload", "Загрузка документов", {"documents:upload", "all"}),
    ("documents_sign", "ЭЦП / подписание", {"documents:sign", "all"}),
    ("inspections", "Проверки", {"inspections:prepare", "all"}),
    ("tasks", "Поручения", {"tasks:create", "tasks:update", "all"}),
    ("money", "Платежи и штрафы", {"money:pay", "money:appeal", "all"}),
    ("objects", "Объекты", {"objects:create", "objects:update", "all"}),
    ("team", "Команда и доступы", {"all"}),
]

ACCESS_ROLE_PROFILES = {
    "ceo": {
        "responsibility": "Финальное решение, подписание, запуск production, роли, риски и коммуникация с Минстроем/ДГАСК.",
        "allowed_scope": "Все объекты, все документы, все сотрудники, аудит, readiness и launch bundle.",
        "restricted": "Нет ограничений внутри платформы; реальные production-доступы выдаются только после внешнего подтверждения.",
    },
    "chief_engineer": {
        "responsibility": "Технические документы, ответы инспектору, проверки, предписания, поручения прорабам и контроль доказательств.",
        "allowed_scope": "Все объекты, документы, запросы, проверки, поручения и подписание технических материалов.",
        "restricted": "Не управляет командой, production-настройками, платежами и юридической сверкой справочника.",
    },
    "foreman": {
        "responsibility": "Работа на объекте, график, фотофиксация, устранение замечаний, подготовка к проверкам.",
        "allowed_scope": "Назначенные объекты, запросы по объектам, проверки, задачи и техническая переписка.",
        "restricted": "Не видит чужие объекты, платежи, аудит, production readiness и управление командой.",
    },
    "brigadier": {
        "responsibility": "Исполнение поручений на объекте, чек-листы, фото и фактические доказательства выполнения.",
        "allowed_scope": "Только назначенные объекты, свои задачи и подготовка материалов к проверке.",
        "restricted": "Не создает запросы, не подписывает документы, не видит платежи, чужие объекты и управленческие разделы.",
    },
    "accountant": {
        "responsibility": "Госпошлины, штрафы, начисления, подтверждения оплат, квитанции и платежные доказательства.",
        "allowed_scope": "Платежи, штрафы, документы и загрузка подтверждений оплаты по всем объектам.",
        "restricted": "Не управляет объектами, задачами, production-настройками, проверками и командой.",
    },
    "lawyer": {
        "responsibility": "Разрешительные документы, заявления, ответы, жалобы, протоколы, ЭЦП и юридическая сверка справочника.",
        "allowed_scope": "Запросы, документы, загрузка/подписание, обжалование штрафов и legal verification packet.",
        "restricted": "Не управляет командой, объектами, production-инфраструктурой и задачами исполнения.",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def utc_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def json_dumps(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def max_json_body_bytes() -> int:
    raw = os.environ.get("QH_MAX_JSON_BYTES", "").strip()
    if not raw:
        return MAX_JSON_BYTES
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid JSON body size limit") from exc
    if limit <= 0:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid JSON body size limit")
    return limit


def safe_filename(name: str) -> str:
    cleaned = Path(name).name.strip().replace("\x00", "")
    cleaned = re.sub(r"[^A-Za-zА-Яа-я0-9._ -]+", "_", cleaned).strip(" .")
    return cleaned[:120] or "document.bin"


def validate_upload_filename(filename: str) -> str:
    cleaned = safe_filename(filename)
    suffix = Path(cleaned).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise ApiError(HTTPStatus.BAD_REQUEST, f"unsupported file type; allowed: {allowed}")
    return cleaned


def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def sqlite_integrity_status(db_path: Path) -> tuple[bool, str]:
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("PRAGMA quick_check").fetchall()
    except Exception as exc:
        return False, f"PRAGMA quick_check: {exc}"
    messages = [str(row[0]) for row in rows if row and row[0] is not None]
    if messages == ["ok"]:
        return True, "PRAGMA quick_check: ok"
    if messages:
        return False, "PRAGMA quick_check: " + "; ".join(messages[:5])
    return False, "PRAGMA quick_check: no result"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000)
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected: str) -> bool:
    _, actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_login_not_locked(conn: sqlite3.Connection, email: str) -> None:
    row = conn.execute("SELECT locked_until FROM login_attempts WHERE email = ?", (email,)).fetchone()
    if row and row["locked_until"] and float(row["locked_until"]) > utc_ts():
        raise ApiError(HTTPStatus.TOO_MANY_REQUESTS, "too many login attempts; try later")


def record_failed_login(conn: sqlite3.Connection, email: str) -> bool:
    now = utc_ts()
    row = conn.execute("SELECT failed_count, first_failed_at FROM login_attempts WHERE email = ?", (email,)).fetchone()
    if row and now - float(row["first_failed_at"]) <= LOGIN_WINDOW_SECONDS:
        failed_count = int(row["failed_count"]) + 1
        first_failed_at = float(row["first_failed_at"])
    else:
        failed_count = 1
        first_failed_at = now
    locked_until = now + LOGIN_LOCK_SECONDS if failed_count >= LOGIN_MAX_FAILED else None
    conn.execute(
        """
        INSERT INTO login_attempts (email, failed_count, first_failed_at, locked_until, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
          failed_count = excluded.failed_count,
          first_failed_at = excluded.first_failed_at,
          locked_until = excluded.locked_until,
          updated_at = excluded.updated_at
        """,
        (email, failed_count, first_failed_at, locked_until, utc_now()),
    )
    return locked_until is not None


def clear_login_attempts(conn: sqlite3.Connection, email: str) -> None:
    conn.execute("DELETE FROM login_attempts WHERE email = ?", (email,))


def revoke_expired_sessions(conn: sqlite3.Connection, now: float | None = None) -> int:
    checked_at = utc_ts() if now is None else now
    cursor = conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE expires_at < ? AND revoked_at IS NULL",
        (utc_now(), checked_at),
    )
    return max(cursor.rowcount, 0)


def active_session_rows(conn: sqlite3.Connection, current_digest: str) -> list[dict[str, Any]]:
    revoke_expired_sessions(conn)
    rows = conn.execute(
        """
        SELECT
          sessions.token_hash,
          sessions.email,
          sessions.expires_at,
          sessions.created_at,
          users.name,
          users.role
        FROM sessions
        JOIN users ON users.email = sessions.email
        WHERE sessions.revoked_at IS NULL
          AND users.active = 1
        ORDER BY sessions.expires_at DESC, sessions.created_at DESC
        """
    ).fetchall()
    checked_at = utc_ts()
    return [
        {
            "email": row["email"],
            "name": row["name"],
            "role": row["role"],
            "role_title": role_title(str(row["role"])),
            "created_at": row["created_at"],
            "expires_at": float(row["expires_at"]),
            "expires_in_seconds": max(0, int(float(row["expires_at"]) - checked_at)),
            "current": row["token_hash"] == current_digest,
        }
        for row in rows
    ]


def session_control_payload(conn: sqlite3.Connection, current_digest: str) -> dict[str, Any]:
    sessions = active_session_rows(conn, current_digest)
    return {
        "checked_at": utc_now(),
        "active_count": len(sessions),
        "other_count": sum(1 for item in sessions if not item["current"]),
        "sessions": sessions,
    }


def revoke_other_sessions(conn: sqlite3.Connection, current_digest: str) -> int:
    cursor = conn.execute(
        """
        UPDATE sessions
        SET revoked_at = ?
        WHERE token_hash != ?
          AND revoked_at IS NULL
        """,
        (utc_now(), current_digest),
    )
    return max(cursor.rowcount, 0)


PRODUCTION_PLAN_ITEMS = [
    {
        "id": "https",
        "title": "Домен и HTTPS",
        "owner": "DevOps / директор",
        "variables": ["--tls-cert", "--tls-key"],
        "next_step": "Назначить домен, выпустить TLS-сертификат и запускать backend через HTTPS/nginx.",
    },
    {
        "id": "corporate_auth",
        "title": "Боевые учетные записи",
        "owner": "Генеральный директор",
        "variables": ["QH_BOOTSTRAP_ADMIN_EMAIL", "QH_BOOTSTRAP_ADMIN_PASSWORD", "QH_DISABLE_DEMO_USERS"],
        "next_step": "Создать bootstrap-администратора компании и отключить демо-пользователей перед запуском.",
    },
    {
        "id": "bootstrap_admin",
        "title": "Боевой администратор",
        "owner": "Генеральный директор",
        "variables": ["QH_BOOTSTRAP_ADMIN_EMAIL", "QH_BOOTSTRAP_ADMIN_PASSWORD", "QH_BOOTSTRAP_ADMIN_NAME"],
        "next_step": "Задать реальный email, надежный пароль и ФИО ответственного администратора.",
    },
    {
        "id": "production_env_values",
        "title": "Проверка production-переменных",
        "owner": "DevOps",
        "variables": ["все QH_* production-переменные"],
        "next_step": "Убрать placeholder-значения, короткие ключи и тестовые example/test URL.",
    },
    {
        "id": "hook_json_contracts",
        "title": "JSON-контракты внешних hooks",
        "owner": "IT / DevOps",
        "variables": ["QH_REQUIRE_HOOK_JSON"],
        "next_step": "Включить QH_REQUIRE_HOOK_JSON=1 и настроить hooks так, чтобы они возвращали JSON со статусом ok/synced/signed/confirmed.",
    },
    {
        "id": "sacc2_api",
        "title": "Интеграция sacc2 / ДГАСК",
        "owner": "Директор / IT / Минстрой",
        "variables": ["QH_SACC2_API_URL", "QH_SACC2_API_KEY", "QH_SACC2_SYNC_CMD"],
        "next_step": "Получить официальный API URL, ключ, регламент статусов и подключить sync-команду обмена.",
    },
    {
        "id": "eds",
        "title": "ЭЦП / электронное подписание",
        "owner": "Юрист / IT",
        "variables": ["QH_EDS_PROVIDER", "QH_EDS_API_URL", "QH_EDS_SIGN_CMD"],
        "next_step": "Выбрать провайдера ЭЦП, получить доступ и подключить команду подписания документов.",
    },
    {
        "id": "payments",
        "title": "Платежный шлюз",
        "owner": "Бухгалтер / IT",
        "variables": ["QH_PAYMENT_GATEWAY_URL", "QH_PAYMENT_GATEWAY_CMD"],
        "next_step": "Подключить проверку оплаты госпошлин, начислений и штрафов до сохранения статуса.",
    },
    {
        "id": "object_storage",
        "title": "Production-файловое хранилище",
        "owner": "IT / служба безопасности",
        "variables": ["QH_STORAGE_MODE", "QH_STORAGE_URL", "QH_STORAGE_SYNC_CMD"],
        "next_step": "Вынести документы из локальной папки в защищенное внешнее хранилище и включить sync-hook.",
    },
    {
        "id": "av_scan",
        "title": "Антивирусная проверка файлов",
        "owner": "IT / служба безопасности",
        "variables": ["QH_AV_SCANNER", "QH_AV_SCANNER_CMD"],
        "next_step": "Подключить AV-сканер, который проверяет загружаемый файл до сохранения.",
    },
    {
        "id": "backup_schedule",
        "title": "Расписание бэкапов",
        "owner": "DevOps",
        "variables": ["QH_BACKUP_INTERVAL_MINUTES", "QH_BACKUP_SCHEDULE", "QH_BACKUP_ON_START"],
        "next_step": "Настроить регулярные SQLite-копии и первый бэкап при старте сервиса.",
    },
    {
        "id": "backup_remote",
        "title": "Удаленное хранение бэкапов",
        "owner": "DevOps / служба безопасности",
        "variables": ["QH_BACKUP_REMOTE_URL", "QH_BACKUP_REMOTE_CMD"],
        "next_step": "Отправлять `.sqlite3` и `.json` manifest вне сервера, затем проверять restore-drill.",
    },
    {
        "id": "reference_catalog",
        "title": "Юридическая сверка справочника",
        "owner": "Юрист / разрешитель",
        "variables": ["QH_REFERENCE_VERIFIED_AT", "QH_LEGAL_CATALOG_VERIFIED_AT"],
        "next_step": "Сверить НПА, тарифы, формы, сроки, штрафы и поставить дату юридической проверки.",
    },
]


PRODUCTION_LAUNCH_PHASES = [
    {
        "id": "governance",
        "title": "1. Управление и юридическая основа",
        "focus": "Назначить владельца платформы, убрать demo-доступы и подтвердить правовой справочник.",
        "gate_ids": ["corporate_auth", "bootstrap_admin", "reference_catalog"],
        "depends_on": [],
        "exit_criteria": "Есть боевой администратор, demo-пользователи отключены, справочник НПА/тарифов/штрафов юридически сверен.",
    },
    {
        "id": "infrastructure",
        "title": "2. Инфраструктура и доступ",
        "focus": "Поднять публичный HTTPS-контур и заполнить production env без тестовых значений.",
        "gate_ids": ["https", "production_env_values"],
        "depends_on": ["governance"],
        "exit_criteria": "Домен открывается по HTTPS, production env проходит preflight без placeholder/test/example значений.",
    },
    {
        "id": "integrations",
        "title": "3. Интеграции Минстроя, ЭЦП и платежей",
        "focus": "Подключить sacc2, ЭЦП, платежный шлюз и JSON-контракты внешних hooks.",
        "gate_ids": ["hook_json_contracts", "sacc2_api", "eds", "payments"],
        "depends_on": ["governance", "infrastructure"],
        "exit_criteria": "Каждый внешний hook возвращает валидный JSON, sacc2/ЭЦП/платежи подтверждены тестовыми операциями.",
    },
    {
        "id": "documents_security",
        "title": "4. Документы и безопасность",
        "focus": "Защитить хранение файлов и проверять документы до сохранения в платформе.",
        "gate_ids": ["object_storage", "av_scan"],
        "depends_on": ["infrastructure"],
        "exit_criteria": "Документы уходят во внешнее хранилище, AV scanner возвращает verdict по чистому и заблокированному файлу.",
    },
    {
        "id": "continuity",
        "title": "5. Backup и восстановление",
        "focus": "Включить регулярные backup, remote copy и restore drill.",
        "gate_ids": ["backup_schedule", "backup_remote"],
        "depends_on": ["infrastructure", "documents_security"],
        "exit_criteria": "Есть свежий backup, remote manifest, sha256 и успешный restore drill в изолированном контуре.",
    },
    {
        "id": "acceptance",
        "title": "6. Финальная приемка",
        "focus": "Повторить production smoke, go/no-go и оформить акт приемки директором.",
        "gate_ids": [],
        "depends_on": ["governance", "infrastructure", "integrations", "documents_security", "continuity"],
        "exit_criteria": "production_smoke_check --require-production и go_no_go_check завершились ok=true без failed_stages.",
    },
]


def production_connection_plan(report: dict[str, Any]) -> dict[str, Any]:
    checks_by_id = {str(item.get("id")): item for item in report.get("checks", []) if isinstance(item, dict)}
    items: list[dict[str, Any]] = []
    for plan in PRODUCTION_PLAN_ITEMS:
        check = checks_by_id.get(plan["id"], {})
        status = str(check.get("status") or "missing")
        items.append(
            {
                "id": plan["id"],
                "title": plan["title"],
                "owner": plan["owner"],
                "status": status,
                "detail": check.get("detail") or "Проверка еще не выполнена",
                "production_required": bool(check.get("production_required", True)),
                "variables": list(plan["variables"]),
                "next_step": plan["next_step"],
            }
        )
    blockers = [item for item in items if item["production_required"] and item["status"] != "pass"]
    ready = [item for item in items if item["status"] == "pass"]
    required_items = [item for item in items if item["production_required"]]
    required_ready = [item for item in required_items if item["status"] == "pass"]
    completion_percent = int(round((len(required_ready) / len(required_items)) * 100)) if required_items else 100
    next_step = blockers[0] if blockers else None
    return {
        "format": "qurulush-production-connection-plan-v1",
        "checked_at": report.get("checked_at") or utc_now(),
        "production_ready": bool(report.get("production_ready")),
        "total": len(items),
        "ready_count": len(ready),
        "required_total": len(required_items),
        "required_ready_count": len(required_ready),
        "completion_percent": completion_percent,
        "blocker_count": len(blockers),
        "blockers": [item["id"] for item in blockers],
        "next_step": next_step,
        "items": items,
    }


def access_matrix_payload(state: dict[str, Any], actor: str) -> dict[str, Any]:
    normalize_team_assignments(state)
    team = state.get("team", []) if isinstance(state.get("team"), list) else []
    objects = state.get("objects", []) if isinstance(state.get("objects"), list) else []
    object_titles = {
        str(item.get("id")): clean_evidence_text(item.get("name") or item.get("title") or item.get("id"), 140)
        for item in objects
        if isinstance(item, dict)
    }
    rows: list[dict[str, Any]] = []
    for role in SEED["roles"]:
        role_id = str(role["id"])
        perms = set(role.get("perms", []))
        profile = ACCESS_ROLE_PROFILES.get(role_id, {})
        members = [item for item in team if isinstance(item, dict) and item.get("role") == role["title"]]
        object_defaults = ROLE_OBJECT_DEFAULTS.get(role_id)
        if object_defaults is None:
            object_scope = "Все объекты"
        elif object_defaults:
            object_scope = ", ".join(object_titles.get(str(value), str(value)) for value in object_defaults)
        else:
            object_scope = "Только назначенные объекты"
        rows.append(
            {
                "id": role_id,
                "title": role["title"],
                "perms": sorted(perms),
                "member_count": len(members),
                "members": [
                    {
                        "name": clean_evidence_text(item.get("name"), 120),
                        "email": clean_evidence_text(item.get("email"), 160),
                        "objects": clean_evidence_text(item.get("objects"), 200),
                    }
                    for item in members
                ],
                "object_scope": object_scope,
                "responsibility": profile.get("responsibility", ""),
                "allowed_scope": profile.get("allowed_scope", ""),
                "restricted": profile.get("restricted", ""),
                "actions": [
                    {
                        "id": action_id,
                        "title": title,
                        "allowed": bool(perms.intersection(required)),
                    }
                    for action_id, title, required in ACCESS_ACTIONS
                ],
            }
        )
    return {
        "format": "qurulush-company-access-matrix-v1",
        "checked_at": utc_now(),
        "reported_by": actor,
        "role_count": len(rows),
        "team_count": len([item for item in team if isinstance(item, dict)]),
        "actions": [{"id": action_id, "title": title} for action_id, title, _required in ACCESS_ACTIONS],
        "roles": rows,
    }


PRODUCTION_EVIDENCE_STATUSES = {
    "open": "Открыто",
    "in_progress": "В работе",
    "waiting_external": "Ждем внешнюю сторону",
    "done": "Доказательство приложено",
    "blocked": "Заблокировано",
}


PRODUCTION_REQUEST_TRACKER_STATUSES = {
    "draft": "Черновик",
    "sent": "Отправлено, ждем ответ",
    "answered": "Ответ получен",
    "evidence_attached": "Доказательство приложено",
    "blocked": "Заблокировано",
}


INTERACTION_WORKFLOWS = [
    {
        "id": "incoming_request",
        "title": "Входящий запрос инспектора или Минстроя",
        "source": "Инспектор / Региональный отдел / Министерство / sacc2",
        "trigger": "Инспектор просит документ, пояснение, подтверждение готовности или устранение замечания.",
        "company_action": "Назначить владельца, подготовить ответ, приложить документ или доказательство и отправить в срок.",
        "company_roles": ["Главный инженер", "Прораб", "Юрист / разрешитель", "Генеральный директор"],
        "status_flow": ["needs_company", "review", "informed", "done"],
        "evidence_needed": "Исходящий ответ, приложенный файл, SHA-256 версии документа, audit-событие и отметка срока.",
        "notification_rule": "Оповестить владельца запроса, директора при просрочке и всех участников объекта при смене статуса.",
        "risk": "Просрочка ответа может привести к повторному запросу, предписанию, остановке этапа или штрафу.",
    },
    {
        "id": "official_notification",
        "title": "Официальное уведомление компании",
        "source": "Министерство / ДГАСК / Региональный отдел",
        "trigger": "Смена ответственного инспектора, информирование о проверке, статусе или регламентном сроке.",
        "company_action": "Зафиксировать уведомление, отметить ответственного, проверить объект и при необходимости создать поручение.",
        "company_roles": ["Генеральный директор", "Главный инженер", "Прораб"],
        "status_flow": ["informed", "review", "done"],
        "evidence_needed": "Карточка уведомления, дата получения, ответственный сотрудник и связанное поручение при необходимости.",
        "notification_rule": "Показать в оповещениях и журнале действий; срочные уведомления выделить директору и владельцу объекта.",
        "risk": "Команда может пропустить проверку, смену инспектора или срок подготовки документов.",
    },
    {
        "id": "inspection_preparation",
        "title": "Подготовка к проверке и предписанию",
        "source": "Инспектор / Региональный отдел",
        "trigger": "Назначена плановая, внеплановая, контрольная или документарная проверка.",
        "company_action": "Подготовить объект, назначить прораба/бригадира, собрать фото, журналы, акты и сертификаты.",
        "company_roles": ["Главный инженер", "Прораб", "Бригадир"],
        "status_flow": ["new", "in_progress", "done"],
        "evidence_needed": "Чек-лист готовности, фотофиксация, документы по объекту и отметка ответственного.",
        "notification_rule": "Оповестить прораба и бригадира; директор получает сигнал по high-risk объектам.",
        "risk": "Неготовность объекта повышает риск предписаний, повторных проверок и штрафов.",
    },
    {
        "id": "permit_document",
        "title": "Разрешительный документ или заявление",
        "source": "Компания -> Министерство / ДГАСК",
        "trigger": "Регистрация объекта, разрешение на строительство, ввод, реконструкция или изменение проектных данных.",
        "company_action": "Собрать комплект, загрузить файл, подписать ЭЦП и отправить по официальному каналу.",
        "company_roles": ["Юрист / разрешитель", "Генеральный директор", "Главный инженер"],
        "status_flow": ["draft", "uploaded", "signed", "submitted", "accepted"],
        "evidence_needed": "Загруженная версия документа, SHA-256, ЭЦП-подпись, исходящий номер и ответ ведомства.",
        "notification_rule": "Оповестить юриста и директора при неподписанном или просроченном документе.",
        "risk": "Без корректного документа объект не пройдет учет, проверку или следующий строительный этап.",
    },
    {
        "id": "state_fee_payment",
        "title": "Госпошлина, начисление или ЕРН",
        "source": "Министерство / платежный контур / бухгалтерия",
        "trigger": "Начислена госпошлина, договорная услуга, ЕРН или требуется подтверждение оплаты.",
        "company_action": "Проверить основание, оплатить, внести номер платежа и приложить квитанцию.",
        "company_roles": ["Бухгалтер", "Генеральный директор"],
        "status_flow": ["new", "pending_payment", "paid", "confirmed"],
        "evidence_needed": "Номер платежа, дата оплаты, квитанция, сумма и подтверждение платежного шлюза.",
        "notification_rule": "Оповестить бухгалтера сразу, директора при просрочке или крупной сумме.",
        "risk": "Неоплата блокирует документы, ответы и может создать дополнительный спор с ведомством.",
    },
    {
        "id": "fine_or_violation",
        "title": "Штраф, нарушение или протокол",
        "source": "Инспектор / ДГАСК / Министерство",
        "trigger": "Зафиксировано нарушение, вынесено предписание, протокол или начислен штраф.",
        "company_action": "Проверить основание, назначить устранение, оплатить или подготовить жалобу/обжалование.",
        "company_roles": ["Юрист / разрешитель", "Бухгалтер", "Главный инженер", "Прораб"],
        "status_flow": ["new", "appeal", "in_progress", "paid", "closed"],
        "evidence_needed": "Протокол, фото устранения, платежное подтверждение или текст жалобы с исходящим номером.",
        "notification_rule": "Срочно уведомить директора, юриста, бухгалтера и владельца объекта.",
        "risk": "Штраф без реакции может привести к повторной проверке, росту санкций и блокировке работ.",
    },
    {
        "id": "production_exchange",
        "title": "Обмен с sacc2 / ДГАСК",
        "source": "Qurulush Hub -> sacc2.avn.kg",
        "trigger": "Нужно синхронизировать заявки, статусы, документы, уведомления и ответы компании.",
        "company_action": "Отправить очищенный пакет обмена без паролей и внутренних файлов через официальный sync-hook.",
        "company_roles": ["Генеральный директор", "IT / интегратор"],
        "status_flow": ["queued", "sent", "accepted", "rejected", "synced"],
        "evidence_needed": "API URL, ключ вне payload, JSON-ответ sync-hook, correlation id и audit-событие.",
        "notification_rule": "Оповестить директора и IT при ошибке синхронизации или отклонении пакета.",
        "risk": "Без официального доступа sacc2 платформа остается локальной и не является боевым ведомственным контуром.",
    },
]


PRODUCTION_LAUNCH_SEQUENCE_STATUSES = {
    "done": "Готово",
    "open": "Открыто",
    "in_progress": "В работе",
    "waiting_external": "Ждем внешнюю сторону",
    "waiting_dependencies": "Ждет предыдущие этапы",
    "blocked": "Заблокировано",
}


PRODUCTION_REMAINING_URGENCY_LABELS = {
    "overdue": "Просрочено",
    "today": "Сегодня",
    "due_soon": "Скоро",
    "scheduled": "Запланировано",
    "no_deadline": "Без срока",
    "invalid_deadline": "Уточнить срок",
}


PRODUCTION_REQUEST_TEMPLATES = {
    "https": {
        "stakeholder": "DevOps / регистратор домена / хостинг-провайдер",
        "channel": "Внутренняя задача DevOps или заявка провайдеру",
        "subject": "Подключение домена и HTTPS для кабинета строительной компании",
        "request": "Назначить production-домен, выпустить TLS-сертификат, настроить nginx/HTTPS и подтвердить доступность backend по публичному URL.",
        "required_evidence": "Домен, HTTPS URL, дата выпуска сертификата, скрин/лог проверки TLS и security headers.",
    },
    "corporate_auth": {
        "stakeholder": "Генеральный директор / IT-администратор",
        "channel": "Внутренняя заявка на ввод боевых учетных записей",
        "subject": "Замена демо-доступов на боевые учетные записи",
        "request": "Утвердить владельца платформы, создать боевого администратора, отключить demo-пользователей и выдать роли сотрудникам компании.",
        "required_evidence": "Email владельца, ФИО администратора, дата отключения demo-пользователей, список ролей без паролей.",
    },
    "bootstrap_admin": {
        "stakeholder": "Генеральный директор / IT-администратор",
        "channel": "Внутренняя заявка на bootstrap-доступ",
        "subject": "Боевой администратор Qurulush Hub",
        "request": "Назначить реальный email и ФИО администратора, задать надежный пароль через защищенный канал и подтвердить первый вход.",
        "required_evidence": "ФИО администратора, корпоративный email, дата первого входа, отметка о смене временного пароля.",
    },
    "production_env_values": {
        "stakeholder": "DevOps / служба безопасности",
        "channel": "Внутренний change request",
        "subject": "Заполнение production env без тестовых значений",
        "request": "Заполнить все QH_* переменные реальными значениями, убрать placeholder/test/example URL и проверить preflight с QH_REQUIRE_PRODUCTION=1.",
        "required_evidence": "Результат preflight JSON ok=true без раскрытия секретов, дата и ответственный за env.",
    },
    "hook_json_contracts": {
        "stakeholder": "IT-интегратор / DevOps",
        "channel": "Техническая заявка исполнителю hooks",
        "subject": "JSON-контракты внешних hooks",
        "request": "Настроить внешние hooks так, чтобы каждый возвращал валидный JSON со статусом ok/synced/signed/confirmed и идентификатором внешней операции.",
        "required_evidence": "Пример JSON-ответов по sacc2, ЭЦП, платежам, storage и backup без ключей и паролей.",
    },
    "sacc2_api": {
        "stakeholder": "Министерство строительства КР / ДГАСК / IT-интегратор",
        "channel": "Официальное письмо или сервисная заявка на интеграцию",
        "subject": "Доступ к sacc2 для обмена статусами строительной компании",
        "request": "Предоставить официальный API URL, порядок авторизации, регламент статусов, тестовый контур и контакт ответственного за обмен.",
        "required_evidence": "Номер письма/заявки, API URL, регламент статусов, дата выдачи доступа, контакт ответственного.",
    },
    "eds": {
        "stakeholder": "Провайдер ЭЦП / юрист / IT-интегратор",
        "channel": "Заявка провайдеру ЭЦП и внутренняя юридическая задача",
        "subject": "Подключение электронного подписания документов",
        "request": "Выбрать провайдера ЭЦП, получить доступ к API подписания, согласовать payload подписи и проверить подписание тестового документа.",
        "required_evidence": "Договор/заявка провайдера, API URL, дата тестовой подписи, checksum подписанного файла.",
    },
    "payments": {
        "stakeholder": "Банк / платежный провайдер / бухгалтерия",
        "channel": "Заявка платежному провайдеру и бухгалтерская настройка",
        "subject": "Проверка оплаты госпошлин, начислений и штрафов",
        "request": "Подключить gateway для подтверждения оплат, согласовать статусы платежей, возвраты, назначение платежа и сверку штрафов/госпошлин.",
        "required_evidence": "Договор/merchant ID без секретов, регламент статусов, тестовая оплата, номер подтверждения платежа.",
    },
    "object_storage": {
        "stakeholder": "IT / служба безопасности / провайдер хранилища",
        "channel": "Заявка на защищенное production-хранилище",
        "subject": "Внешнее хранение документов строительной компании",
        "request": "Подключить внешнее защищенное хранилище, настроить sync-hook, права доступа, retention policy и аудит скачиваний.",
        "required_evidence": "Storage URL/режим без ключей, дата sync-теста, checksum файла, политика доступа и хранения.",
    },
    "av_scan": {
        "stakeholder": "IT / служба безопасности",
        "channel": "Заявка на антивирусную проверку загрузок",
        "subject": "AV scanning документов перед сохранением",
        "request": "Подключить AV scanner, который проверяет каждый загружаемый файл до сохранения и возвращает валидный JSON verdict.",
        "required_evidence": "Название сканера, JSON verdict теста, дата проверки чистого и заблокированного файла.",
    },
    "backup_schedule": {
        "stakeholder": "DevOps",
        "channel": "Внутренняя задача эксплуатации",
        "subject": "Регулярное расписание резервного копирования",
        "request": "Настроить регулярные SQLite backup, backup при старте сервиса, retention и мониторинг свежести последней копии.",
        "required_evidence": "Расписание, последний manifest, sha256, результат restore drill.",
    },
    "backup_remote": {
        "stakeholder": "DevOps / служба безопасности / внешнее хранилище backup",
        "channel": "Заявка на удаленное хранение резервных копий",
        "subject": "Remote backup и restore drill",
        "request": "Настроить отправку backup и manifest вне сервера, проверить доступность удаленной копии и восстановление в изолированной среде.",
        "required_evidence": "Remote URL/контур без секретов, manifest, sha256, дата успешного restore drill.",
    },
    "reference_catalog": {
        "stakeholder": "Юрист / разрешитель / ответственный по взаимодействию с Минстроем",
        "channel": "Юридическая сверка справочника",
        "subject": "Проверка разрешений, госпошлин, сроков, штрафов и форм",
        "request": "Сверить справочник с действующими НПА, регламентами, тарифами, формами заявлений, сроками и штрафами по строительной деятельности.",
        "required_evidence": "Дата сверки, перечень источников НПА/регламентов, подпись юриста или ответственного, список измененных пунктов.",
    },
}


def clean_evidence_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def production_evidence_payload(state: dict[str, Any], report: dict[str, Any], actor: str) -> dict[str, Any]:
    plan = production_connection_plan(report)
    saved = state.get("productionEvidence", {})
    if not isinstance(saved, dict):
        saved = {}
    items: list[dict[str, Any]] = []
    for gate in plan.get("items", []):
        if not isinstance(gate, dict):
            continue
        gate_id = str(gate.get("id") or "")
        row = saved.get(gate_id, {})
        if not isinstance(row, dict):
            row = {}
        status = str(row.get("status") or ("done" if gate.get("status") == "pass" else "open"))
        if status not in PRODUCTION_EVIDENCE_STATUSES:
            status = "open"
        items.append(
            {
                "id": gate_id,
                "title": str(gate.get("title") or gate_id),
                "owner": clean_evidence_text(row.get("owner") or gate.get("owner") or "-", 120),
                "gate_status": str(gate.get("status") or "missing"),
                "evidence_status": status,
                "evidence_label": PRODUCTION_EVIDENCE_STATUSES[status],
                "evidence": clean_evidence_text(row.get("evidence"), 700),
                "deadline": clean_evidence_text(row.get("deadline"), 40),
                "updated_by": clean_evidence_text(row.get("updated_by"), 120),
                "updated_at": clean_evidence_text(row.get("updated_at"), 40),
                "variables": gate.get("variables") if isinstance(gate.get("variables"), list) else [],
                "next_step": str(gate.get("next_step") or ""),
            }
        )
    open_items = [item for item in items if item["evidence_status"] != "done"]
    return {
        "format": "qurulush-production-evidence-register-v1",
        "checked_at": report.get("checked_at") or utc_now(),
        "reported_by": actor,
        "total": len(items),
        "done_count": len(items) - len(open_items),
        "open_count": len(open_items),
        "production_ready": bool(plan.get("production_ready")),
        "blocker_count": int(plan.get("blocker_count") or 0),
        "items": items,
    }


def update_production_evidence(state: dict[str, Any], data: dict[str, Any], report: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    gate_id = clean_evidence_text(data.get("id") or data.get("gate_id") or data.get("gateId"), 80)
    allowed_ids = {str(item["id"]) for item in PRODUCTION_PLAN_ITEMS}
    if gate_id not in allowed_ids:
        raise ApiError(HTTPStatus.BAD_REQUEST, "unknown production gate")
    status = clean_evidence_text(data.get("status"), 40) or "open"
    if status not in PRODUCTION_EVIDENCE_STATUSES:
        raise ApiError(HTTPStatus.BAD_REQUEST, "unknown evidence status")
    evidence = clean_evidence_text(data.get("evidence"), 700)
    if status == "done" and not evidence:
        raise ApiError(HTTPStatus.BAD_REQUEST, "evidence is required when status is done")
    owner = clean_evidence_text(data.get("owner"), 120)
    deadline = clean_evidence_text(data.get("deadline"), 40)
    saved = state.setdefault("productionEvidence", {})
    if not isinstance(saved, dict):
        saved = {}
        state["productionEvidence"] = saved
    saved[gate_id] = {
        "status": status,
        "owner": owner,
        "evidence": evidence,
        "deadline": deadline,
        "updated_by": user["name"],
        "updated_at": utc_now(),
    }
    return production_evidence_payload(state, report, user["name"])


def production_request_pack_payload(state: dict[str, Any], report: dict[str, Any], actor: str) -> dict[str, Any]:
    evidence = production_evidence_payload(state, report, actor)
    tracker = state.get("productionRequestTracker", {})
    if not isinstance(tracker, dict):
        tracker = {}
    items: list[dict[str, Any]] = []
    for gate in evidence.get("items", []):
        if not isinstance(gate, dict) or gate.get("gate_status") == "pass":
            continue
        gate_id = str(gate.get("id") or "")
        tracked = tracker.get(gate_id, {})
        if not isinstance(tracked, dict):
            tracked = {}
        tracker_status = clean_evidence_text(tracked.get("status"), 40) or "draft"
        if tracker_status not in PRODUCTION_REQUEST_TRACKER_STATUSES:
            tracker_status = "draft"
        template = PRODUCTION_REQUEST_TEMPLATES.get(
            gate_id,
            {
                "stakeholder": gate.get("owner") or "Ответственный исполнитель",
                "channel": "Рабочая заявка",
                "subject": gate.get("title") or gate_id,
                "request": gate.get("next_step") or "Закрыть production gate и приложить доказательство.",
                "required_evidence": "Ссылка, письмо, акт или другой документ, подтверждающий закрытие gate.",
            },
        )
        variables = gate.get("variables") if isinstance(gate.get("variables"), list) else []
        stakeholder = clean_evidence_text(template.get("stakeholder"), 180)
        subject = clean_evidence_text(template.get("subject"), 180)
        request_text = clean_evidence_text(template.get("request"), 700)
        required_evidence = clean_evidence_text(template.get("required_evidence"), 500)
        draft_message = (
            f"Тема: {subject}\n"
            f"Просим закрыть production-пункт `{gate.get('title', gate_id)}` для запуска платформы строительной компании.\n"
            f"Что нужно: {request_text}\n"
            f"Какие данные/доказательства вернуть: {required_evidence}\n"
            f"Ответственный со стороны компании: {gate.get('owner') or '-'}.\n"
            f"Настройки для IT: {', '.join(str(value) for value in variables) or '-'}."
        )
        items.append(
            {
                "id": gate_id,
                "title": str(gate.get("title") or gate_id),
                "gate_status": str(gate.get("gate_status") or "missing"),
                "evidence_status": str(gate.get("evidence_status") or "open"),
                "evidence_label": str(gate.get("evidence_label") or ""),
                "owner": str(gate.get("owner") or ""),
                "deadline": str(gate.get("deadline") or ""),
                "stakeholder": stakeholder,
                "channel": clean_evidence_text(template.get("channel"), 180),
                "subject": subject,
                "request": request_text,
                "required_evidence": required_evidence,
                "current_evidence": str(gate.get("evidence") or ""),
                "tracker_status": tracker_status,
                "tracker_label": PRODUCTION_REQUEST_TRACKER_STATUSES[tracker_status],
                "outgoing_no": clean_evidence_text(tracked.get("outgoing_no") or tracked.get("outgoingNo"), 80),
                "sent_at": clean_evidence_text(tracked.get("sent_at") or tracked.get("sentAt"), 40),
                "response_at": clean_evidence_text(tracked.get("response_at") or tracked.get("responseAt"), 40),
                "contact": clean_evidence_text(tracked.get("contact"), 160),
                "responsible": clean_evidence_text(tracked.get("responsible") or gate.get("owner"), 160),
                "tracker_note": clean_evidence_text(tracked.get("note"), 700),
                "updated_by": clean_evidence_text(tracked.get("updated_by"), 120),
                "updated_at": clean_evidence_text(tracked.get("updated_at"), 40),
                "variables": variables,
                "next_step": str(gate.get("next_step") or ""),
                "draft_message": draft_message,
            }
        )
    sent_items = [item for item in items if item["tracker_status"] in {"sent", "answered", "evidence_attached"}]
    answered_items = [item for item in items if item["tracker_status"] in {"answered", "evidence_attached"}]
    attached_items = [item for item in items if item["tracker_status"] == "evidence_attached"]
    return {
        "format": "qurulush-production-request-pack-v1",
        "checked_at": report.get("checked_at") or utc_now(),
        "reported_by": actor,
        "total": len(items),
        "sent_count": len(sent_items),
        "answered_count": len(answered_items),
        "attached_count": len(attached_items),
        "production_ready": bool(evidence.get("production_ready")),
        "blocker_count": int(evidence.get("blocker_count") or 0),
        "items": items,
    }


def production_official_letters_payload(state: dict[str, Any], report: dict[str, Any], actor: str) -> dict[str, Any]:
    request_pack = production_request_pack_payload(state, report, actor)
    letters: list[dict[str, Any]] = []
    for index, item in enumerate([entry for entry in request_pack.get("items", []) if isinstance(entry, dict)], start=1):
        stakeholder = clean_evidence_text(item.get("stakeholder"), 180) or "Ответственной стороне"
        subject = clean_evidence_text(item.get("subject"), 180) or str(item.get("title") or item.get("id") or "Production gate")
        body = (
            f"Просим содействовать закрытию production-пункта «{item.get('title', item.get('id', '-'))}» "
            "для запуска кабинета строительной компании Qurulush Hub.\n\n"
            f"Что необходимо предоставить или подтвердить: {item.get('request') or '-'}\n\n"
            f"Какие доказательства просим вернуть: {item.get('required_evidence') or '-'}\n\n"
            f"Ответственный со стороны строительной компании: {item.get('responsible') or item.get('owner') or '-'}.\n"
            f"Текущий статус запроса: {item.get('tracker_label') or item.get('tracker_status') or '-'}.\n"
            f"Технические настройки для IT без секретов: {', '.join(str(value) for value in item.get('variables', []) if value) or '-'}."
        )
        letters.append(
            {
                "letter_no": index,
                "id": item.get("id"),
                "title": str(item.get("title") or item.get("id") or "-"),
                "recipient": stakeholder,
                "channel": item.get("channel") or "Официальное письмо / рабочая заявка",
                "subject": subject,
                "body": body,
                "required_evidence": item.get("required_evidence") or "",
                "responsible": item.get("responsible") or item.get("owner") or "",
                "tracker_status": item.get("tracker_status") or "draft",
                "tracker_label": item.get("tracker_label") or "Черновик",
                "outgoing_no": item.get("outgoing_no") or "",
                "sent_at": item.get("sent_at") or "",
                "response_at": item.get("response_at") or "",
                "signature_block": "Генеральный директор ____________________ / ФИО /\nДата: ____________________\nИсходящий номер: ____________________",
            }
        )
    return {
        "format": "qurulush-production-official-letters-v1",
        "checked_at": report.get("checked_at") or utc_now(),
        "reported_by": actor,
        "production_ready": bool(request_pack.get("production_ready")),
        "blocker_count": int(request_pack.get("blocker_count") or 0),
        "total": len(letters),
        "letters": letters,
    }


def update_production_request_tracker(state: dict[str, Any], data: dict[str, Any], report: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    gate_id = clean_evidence_text(data.get("id") or data.get("gate_id") or data.get("gateId"), 80)
    allowed_ids = {str(item["id"]) for item in PRODUCTION_PLAN_ITEMS}
    if gate_id not in allowed_ids:
        raise ApiError(HTTPStatus.BAD_REQUEST, "unknown production gate")
    status = clean_evidence_text(data.get("status"), 40) or "draft"
    if status not in PRODUCTION_REQUEST_TRACKER_STATUSES:
        raise ApiError(HTTPStatus.BAD_REQUEST, "unknown request tracker status")
    evidence = clean_evidence_text(data.get("evidence"), 700)
    note = clean_evidence_text(data.get("note"), 700)
    outgoing_no = clean_evidence_text(data.get("outgoing_no") or data.get("outgoingNo"), 80)
    sent_at = clean_evidence_text(data.get("sent_at") or data.get("sentAt"), 40)
    response_at = clean_evidence_text(data.get("response_at") or data.get("responseAt"), 40)
    contact = clean_evidence_text(data.get("contact"), 160)
    responsible = clean_evidence_text(data.get("responsible"), 160)
    if status in {"sent", "answered", "evidence_attached"} and not outgoing_no:
        raise ApiError(HTTPStatus.BAD_REQUEST, "outgoing_no is required after request is sent")
    if status == "sent" and not sent_at:
        raise ApiError(HTTPStatus.BAD_REQUEST, "sent_at is required after request is sent")
    if status == "evidence_attached" and not evidence:
        raise ApiError(HTTPStatus.BAD_REQUEST, "evidence is required when request evidence is attached")

    saved = state.setdefault("productionRequestTracker", {})
    if not isinstance(saved, dict):
        saved = {}
        state["productionRequestTracker"] = saved
    saved[gate_id] = {
        "status": status,
        "outgoing_no": outgoing_no,
        "sent_at": sent_at,
        "response_at": response_at,
        "contact": contact,
        "responsible": responsible,
        "note": note,
        "updated_by": user["name"],
        "updated_at": utc_now(),
    }

    plan_by_id = {str(item["id"]): item for item in production_connection_plan(report).get("items", []) if isinstance(item, dict)}
    gate = plan_by_id.get(gate_id, {})
    evidence_saved = state.setdefault("productionEvidence", {})
    if not isinstance(evidence_saved, dict):
        evidence_saved = {}
        state["productionEvidence"] = evidence_saved
    current_evidence = evidence_saved.get(gate_id, {})
    if not isinstance(current_evidence, dict):
        current_evidence = {}
    evidence_text = evidence or current_evidence.get("evidence") or note
    if status == "sent":
        evidence_status = "waiting_external"
        sent_marker = f"Запрос отправлен: {outgoing_no} от {sent_at}. Ожидается ответ."
        evidence_text = f"{sent_marker} {evidence_text}".strip() if evidence_text else sent_marker
    elif status == "answered":
        evidence_status = "done" if evidence_text else "in_progress"
    elif status == "evidence_attached":
        evidence_status = "done"
    elif status == "blocked":
        evidence_status = "blocked"
    else:
        evidence_status = current_evidence.get("status") or "open"
    evidence_saved[gate_id] = {
        "status": evidence_status,
        "owner": responsible or current_evidence.get("owner") or gate.get("owner") or "",
        "evidence": clean_evidence_text(evidence_text, 700),
        "deadline": current_evidence.get("deadline") or "",
        "updated_by": user["name"],
        "updated_at": utc_now(),
    }
    return {
        "request_pack": production_request_pack_payload(state, report, user["name"]),
        "evidence": production_evidence_payload(state, report, user["name"]),
    }


PRODUCTION_ACTION_ROLES = [
    {
        "id": "director",
        "title": "Генеральный директор",
        "match": ["генеральный директор", "директор", "владелец"],
        "focus": "Утвердить владельца платформы, боевые доступы, исходящие письма и финальный go/no-go.",
    },
    {
        "id": "devops",
        "title": "DevOps",
        "match": ["devops", "домен", "https", "backup", "бэкап", "nginx"],
        "focus": "Закрыть домен, HTTPS, env, hooks, backup, deployment-файлы и проверки запуска.",
    },
    {
        "id": "it_integrator",
        "title": "IT / интегратор",
        "match": ["it", "интегратор", "hooks", "api", "sync", "storage", "av scanner"],
        "focus": "Подключить внешние API, hooks, sacc2, ЭЦП, платежи, storage и AV JSON-контракты.",
    },
    {
        "id": "accountant",
        "title": "Бухгалтер",
        "match": ["бухгалтер", "банк", "платеж", "госпошлин", "штраф"],
        "focus": "Подключить платежный шлюз, статусы оплат, госпошлины, начисления, штрафы и сверку платежей.",
    },
    {
        "id": "lawyer",
        "title": "Юрист / разрешитель",
        "match": ["юрист", "разрешитель", "нпа", "форм", "тариф", "штраф", "эцп"],
        "focus": "Сверить правовой справочник, формы, сроки, тарифы, штрафы и юридические подтверждения.",
    },
    {
        "id": "ministry",
        "title": "Минстрой / ДГАСК",
        "match": ["минстрой", "министерство", "дгаск", "sacc2"],
        "focus": "Получить официальный доступ sacc2, регламент статусов и контакт ответственного за обмен.",
    },
    {
        "id": "security",
        "title": "Служба безопасности",
        "match": ["безопасности", "хранилище", "storage", "av", "backup", "секрет"],
        "focus": "Проверить хранение документов, антивирус, удаленные backup, доступы и отсутствие секретов в выгрузках.",
    },
]


def production_action_board_payload(state: dict[str, Any], report: dict[str, Any], actor: str) -> dict[str, Any]:
    request_pack = production_request_pack_payload(state, report, actor)
    groups: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for role in PRODUCTION_ACTION_ROLES:
        role_items: list[dict[str, Any]] = []
        match_terms = [str(term).lower() for term in role.get("match", [])]
        for item in request_pack.get("items", []):
            if not isinstance(item, dict):
                continue
            haystack = " ".join(
                str(item.get(key, ""))
                for key in ("title", "owner", "stakeholder", "channel", "subject", "request", "required_evidence", "responsible")
            ).lower()
            if not any(term in haystack for term in match_terms):
                continue
            assigned.add(str(item.get("id") or ""))
            tracker_status = str(item.get("tracker_status") or "draft")
            if tracker_status == "evidence_attached":
                next_action = "Доказательство приложено: повторить production smoke/go-no-go и сверить readiness."
            elif tracker_status == "answered":
                next_action = "Проверить ответ, перенести подтверждение в evidence-регистр и отметить gate как закрытый."
            elif tracker_status == "sent":
                next_action = "Дождаться ответа, проконтролировать срок и приложить полученное подтверждение."
            elif tracker_status == "blocked":
                next_action = "Разобрать блокировку, назначить владельца решения и новый срок."
            else:
                next_action = "Отправить запрос или назначить внутреннюю задачу по этому production gate."
            role_items.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "gate_status": item.get("gate_status"),
                    "tracker_status": tracker_status,
                    "tracker_label": item.get("tracker_label"),
                    "stakeholder": item.get("stakeholder"),
                    "outgoing_no": item.get("outgoing_no"),
                    "sent_at": item.get("sent_at"),
                    "response_at": item.get("response_at"),
                    "responsible": item.get("responsible") or item.get("owner"),
                    "next_action": next_action,
                    "evidence_needed": item.get("required_evidence"),
                    "current_evidence": item.get("current_evidence"),
                }
            )
        open_count = len([item for item in role_items if item.get("tracker_status") != "evidence_attached"])
        sent_count = len([item for item in role_items if item.get("tracker_status") in {"sent", "answered", "evidence_attached"}])
        groups.append(
            {
                "id": role["id"],
                "title": role["title"],
                "focus": role["focus"],
                "total": len(role_items),
                "open_count": open_count,
                "sent_count": sent_count,
                "items": role_items,
            }
        )
    unassigned = [item for item in request_pack.get("items", []) if isinstance(item, dict) and str(item.get("id") or "") not in assigned]
    if unassigned:
        groups.append(
            {
                "id": "unassigned",
                "title": "Не назначено",
                "focus": "Пункты, которые требуют ручного назначения владельца.",
                "total": len(unassigned),
                "open_count": len(unassigned),
                "sent_count": 0,
                "items": [
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "gate_status": item.get("gate_status"),
                        "tracker_status": item.get("tracker_status"),
                        "tracker_label": item.get("tracker_label"),
                        "stakeholder": item.get("stakeholder"),
                        "outgoing_no": item.get("outgoing_no"),
                        "sent_at": item.get("sent_at"),
                        "response_at": item.get("response_at"),
                        "responsible": item.get("responsible") or item.get("owner"),
                        "next_action": item.get("next_step") or "Назначить владельца и срок.",
                        "evidence_needed": item.get("required_evidence"),
                        "current_evidence": item.get("current_evidence"),
                    }
                    for item in unassigned
                ],
            }
        )
    active_groups = [group for group in groups if group["total"] > 0]
    return {
        "format": "qurulush-production-action-board-v1",
        "checked_at": report.get("checked_at") or utc_now(),
        "reported_by": actor,
        "production_ready": bool(request_pack.get("production_ready")),
        "blocker_count": int(request_pack.get("blocker_count") or 0),
        "request_total": int(request_pack.get("total") or 0),
        "sent_count": int(request_pack.get("sent_count") or 0),
        "answered_count": int(request_pack.get("answered_count") or 0),
        "attached_count": int(request_pack.get("attached_count") or 0),
        "groups": active_groups,
    }


def production_launch_sequence_payload(state: dict[str, Any], report: dict[str, Any], actor: str) -> dict[str, Any]:
    plan = production_connection_plan(report)
    request_pack = production_request_pack_payload(state, report, actor)
    request_by_id = {str(item.get("id")): item for item in request_pack.get("items", []) if isinstance(item, dict)}
    plan_by_id = {str(item.get("id")): item for item in plan.get("items", []) if isinstance(item, dict)}

    phases: list[dict[str, Any]] = []
    flat_steps: list[dict[str, Any]] = []
    step_no = 1
    for phase_index, phase in enumerate(PRODUCTION_LAUNCH_PHASES, start=1):
        phase_steps: list[dict[str, Any]] = []
        for gate_id in phase["gate_ids"]:
            gate = plan_by_id.get(str(gate_id), {})
            tracked = request_by_id.get(str(gate_id), {})
            tracker_status = str(tracked.get("tracker_status") or ("evidence_attached" if gate.get("status") == "pass" else "draft"))
            if gate.get("status") == "pass" or tracker_status == "evidence_attached":
                status = "done"
                next_action = "Закрыто. Сохранить доказательство и переходить к зависимым шагам."
            elif tracker_status == "answered":
                status = "in_progress"
                next_action = "Проверить ответ и перенести подтверждение в evidence-регистр."
            elif tracker_status == "sent":
                status = "waiting_external"
                next_action = "Дождаться ответа, проконтролировать срок и приложить подтверждение."
            elif tracker_status == "blocked":
                status = "blocked"
                next_action = "Разобрать блокировку с владельцем и назначить новый срок закрытия."
            else:
                status = "open"
                next_action = str(gate.get("next_step") or tracked.get("request") or "Назначить владельца и закрыть production gate.")
            step = {
                "step_no": step_no,
                "phase_id": phase["id"],
                "phase_title": phase["title"],
                "id": gate_id,
                "title": str(gate.get("title") or tracked.get("title") or gate_id),
                "owner": str(tracked.get("responsible") or gate.get("owner") or "-"),
                "stakeholder": str(tracked.get("stakeholder") or "-"),
                "status": status,
                "status_label": PRODUCTION_LAUNCH_SEQUENCE_STATUSES.get(status, status),
                "gate_status": str(gate.get("status") or tracked.get("gate_status") or "missing"),
                "tracker_status": tracker_status,
                "tracker_label": str(tracked.get("tracker_label") or PRODUCTION_REQUEST_TRACKER_STATUSES.get(tracker_status, tracker_status)),
                "depends_on": list(phase.get("depends_on", [])),
                "next_action": next_action,
                "evidence_needed": str(tracked.get("required_evidence") or "Доказательство закрытия production gate."),
                "variables": gate.get("variables") if isinstance(gate.get("variables"), list) else [],
                "outgoing_no": str(tracked.get("outgoing_no") or ""),
                "sent_at": str(tracked.get("sent_at") or ""),
                "response_at": str(tracked.get("response_at") or ""),
            }
            phase_steps.append(step)
            flat_steps.append(step)
            step_no += 1

        if phase["id"] == "acceptance":
            all_previous_done = all(step.get("status") == "done" for step in flat_steps)
            acceptance_status = "done" if bool(plan.get("production_ready")) else ("open" if all_previous_done else "waiting_dependencies")
            step = {
                "step_no": step_no,
                "phase_id": phase["id"],
                "phase_title": phase["title"],
                "id": "final_go_no_go",
                "title": "Финальный production smoke и go/no-go",
                "owner": "Генеральный директор / DevOps",
                "stakeholder": "Команда запуска",
                "status": acceptance_status,
                "status_label": PRODUCTION_LAUNCH_SEQUENCE_STATUSES.get(acceptance_status, acceptance_status),
                "gate_status": "pass" if bool(plan.get("production_ready")) else "missing",
                "tracker_status": "evidence_attached" if bool(plan.get("production_ready")) else "draft",
                "tracker_label": "Готово" if bool(plan.get("production_ready")) else "Ожидает закрытия предыдущих шагов",
                "depends_on": list(phase.get("depends_on", [])),
                "next_action": "Запустить production_smoke_check --require-production и go_no_go_check, затем приложить JSON ok=true без failed_stages.",
                "evidence_needed": "Логи production smoke/go-no-go, паспорт приемки и решение директора о запуске.",
                "variables": [],
                "outgoing_no": "",
                "sent_at": "",
                "response_at": "",
            }
            phase_steps.append(step)
            flat_steps.append(step)
            step_no += 1

        blocking_steps = [step for step in phase_steps if step.get("status") not in {"done"}]
        done_steps = [step for step in phase_steps if step.get("status") == "done"]
        if not phase_steps:
            phase_status = "done"
        elif not blocking_steps:
            phase_status = "done"
        elif any(step.get("status") == "blocked" for step in phase_steps):
            phase_status = "blocked"
        elif any(step.get("status") in {"in_progress", "waiting_external"} for step in phase_steps):
            phase_status = "in_progress"
        elif any(step.get("status") == "waiting_dependencies" for step in phase_steps):
            phase_status = "waiting_dependencies"
        else:
            phase_status = "open"
        phases.append(
            {
                "id": phase["id"],
                "order": phase_index,
                "title": phase["title"],
                "focus": phase["focus"],
                "depends_on": list(phase.get("depends_on", [])),
                "exit_criteria": phase["exit_criteria"],
                "status": phase_status,
                "status_label": PRODUCTION_LAUNCH_SEQUENCE_STATUSES.get(phase_status, phase_status),
                "total": len(phase_steps),
                "done_count": len(done_steps),
                "open_count": len(blocking_steps),
                "next_step": blocking_steps[0] if blocking_steps else None,
                "steps": phase_steps,
            }
        )

    open_steps = [step for step in flat_steps if step.get("status") not in {"done"}]
    return {
        "format": "qurulush-production-launch-sequence-v1",
        "checked_at": report.get("checked_at") or utc_now(),
        "reported_by": actor,
        "production_ready": bool(plan.get("production_ready")),
        "blocker_count": int(plan.get("blocker_count") or 0),
        "total_steps": len(flat_steps),
        "done_count": len(flat_steps) - len(open_steps),
        "open_count": len(open_steps),
        "current_step": open_steps[0] if open_steps else None,
        "phases": phases,
    }


def production_remaining_urgency(deadline: str) -> tuple[str, int | None, int]:
    value = clean_evidence_text(deadline, 40)
    if not value:
        return "no_deadline", None, 4
    try:
        due_date = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return "invalid_deadline", None, 5
    days_left = (due_date - datetime.now(timezone.utc).date()).days
    if days_left < 0:
        return "overdue", days_left, 0
    if days_left == 0:
        return "today", days_left, 1
    if days_left <= 3:
        return "due_soon", days_left, 2
    return "scheduled", days_left, 3


def production_remaining_work_payload(state: dict[str, Any], report: dict[str, Any], actor: str) -> dict[str, Any]:
    sequence = production_launch_sequence_payload(state, report, actor)
    plan = production_connection_plan(report)
    evidence_by_id = {
        str(item.get("id")): item
        for item in production_evidence_payload(state, report, actor).get("items", [])
        if isinstance(item, dict)
    }
    open_steps = [
        step
        for phase in sequence.get("phases", [])
        if isinstance(phase, dict)
        for step in phase.get("steps", [])
        if isinstance(step, dict) and step.get("status") != "done"
    ]
    by_status: dict[str, int] = {}
    by_owner: dict[str, int] = {}
    by_urgency: dict[str, int] = {}
    steps: list[dict[str, Any]] = []
    for step in open_steps:
        gate_id = str(step.get("id") or "")
        evidence_item = evidence_by_id.get(gate_id, {})
        owner = str(evidence_item.get("owner") or step.get("owner") or "Не назначено")
        deadline = str(evidence_item.get("deadline") or "")
        urgency, days_left, urgency_rank = production_remaining_urgency(deadline)
        status = str(step.get("status") or "open")
        by_status[status] = by_status.get(status, 0) + 1
        by_owner[owner] = by_owner.get(owner, 0) + 1
        by_urgency[urgency] = by_urgency.get(urgency, 0) + 1
        steps.append(
            {
            "step_no": step.get("step_no"),
            "phase_title": step.get("phase_title"),
            "id": gate_id,
            "title": step.get("title"),
            "owner": owner,
            "deadline": deadline,
            "urgency": urgency,
            "urgency_label": PRODUCTION_REMAINING_URGENCY_LABELS[urgency],
            "days_left": days_left,
            "urgency_rank": urgency_rank,
            "stakeholder": step.get("stakeholder"),
            "status": step.get("status"),
            "status_label": step.get("status_label"),
            "evidence_status": evidence_item.get("evidence_status", ""),
            "evidence_note": evidence_item.get("evidence", ""),
            "gate_status": step.get("gate_status"),
            "next_action": step.get("next_action"),
            "evidence_needed": step.get("evidence_needed"),
            "variables": step.get("variables") if isinstance(step.get("variables"), list) else [],
            }
        )
    top_actions = sorted(
        steps,
        key=lambda item: (int(item.get("urgency_rank") or 9), int(item.get("step_no") or 999)),
    )[:3]
    return {
        "format": "qurulush-production-remaining-work-v1",
        "checked_at": report.get("checked_at") or utc_now(),
        "reported_by": actor,
        "production_ready": bool(plan.get("production_ready")),
        "completion_percent": int(plan.get("completion_percent") or 0),
        "required_total": int(plan.get("required_total") or 0),
        "required_ready_count": int(plan.get("required_ready_count") or 0),
        "remaining_count": len(steps),
        "blocker_count": int(plan.get("blocker_count") or 0),
        "by_status": by_status,
        "by_owner": by_owner,
        "by_urgency": by_urgency,
        "current_step": top_actions[0] if top_actions else None,
        "top_actions": top_actions,
        "steps": steps,
    }


def production_top_actions_payload(state: dict[str, Any], report: dict[str, Any], actor: str, limit: int = 5) -> dict[str, Any]:
    remaining = production_remaining_work_payload(state, report, actor)
    actions = [item for item in remaining.get("top_actions", []) if isinstance(item, dict)][:limit]
    return {
        "format": "qurulush-production-top-actions-v1",
        "checked_at": remaining.get("checked_at") or utc_now(),
        "reported_by": actor,
        "production_ready": bool(remaining.get("production_ready")),
        "completion_percent": int(remaining.get("completion_percent") or 0),
        "remaining_count": int(remaining.get("remaining_count") or 0),
        "action_count": len(actions),
        "by_urgency": remaining.get("by_urgency", {}),
        "actions": actions,
    }


def production_alerts_payload(state: dict[str, Any], report: dict[str, Any], actor: str, limit: int = 10) -> dict[str, Any]:
    remaining = production_remaining_work_payload(state, report, actor)
    top_action_ids = {
        str(item.get("id") or "")
        for item in remaining.get("top_actions", [])
        if isinstance(item, dict)
    }
    alert_steps: list[dict[str, Any]] = []
    for step in remaining.get("steps", []):
        if not isinstance(step, dict):
            continue
        gate_id = str(step.get("id") or "")
        urgency = str(step.get("urgency") or "no_deadline")
        status = str(step.get("status") or "")
        needs_deadline_attention = urgency in {"no_deadline", "invalid_deadline"} and gate_id in top_action_ids
        if urgency not in {"overdue", "today", "due_soon"} and status != "blocked" and not needs_deadline_attention:
            continue
        urgent = urgency in {"overdue", "today"} or status == "blocked"
        title = str(step.get("title") or step.get("id") or "-")
        deadline = str(step.get("deadline") or "")
        action_text = str(step.get("next_action") or "Закрыть production-шаг.")
        if needs_deadline_attention and not deadline:
            action_text = f"Назначить дедлайн и ответственного. {action_text}"
        alert_steps.append(
            {
                "id": f"production:{step.get('id') or step.get('step_no')}",
                "production_step_id": gate_id,
                "step_no": step.get("step_no"),
                "title": f"Production: {title}",
                "text": (
                    f"{step.get('urgency_label') or PRODUCTION_REMAINING_URGENCY_LABELS.get(urgency, urgency)}. "
                    f"{action_text} "
                    f"Ответственный: {step.get('owner') or '-'}. "
                    f"Срок: {deadline or 'не назначен'}."
                ),
                "from": "Production",
                "urgent": urgent,
                "read": False,
                "urgency": urgency,
                "urgency_label": step.get("urgency_label") or PRODUCTION_REMAINING_URGENCY_LABELS.get(urgency, urgency),
                "days_left": step.get("days_left"),
                "deadline": deadline,
                "owner": step.get("owner") or "-",
                "status": status,
                "status_label": step.get("status_label") or status,
                "next_action": action_text,
                "evidence_needed": step.get("evidence_needed") or "",
            }
        )
    alerts = sorted(
        alert_steps,
        key=lambda item: (
            0 if item.get("urgent") else 1,
            int(next((step.get("urgency_rank") for step in remaining.get("steps", []) if isinstance(step, dict) and f"production:{step.get('id') or step.get('step_no')}" == item.get("id")), 9) or 9),
            int(item.get("step_no") or 999),
        ),
    )[:limit]
    return {
        "format": "qurulush-production-alerts-v1",
        "checked_at": remaining.get("checked_at") or utc_now(),
        "reported_by": actor,
        "production_ready": bool(remaining.get("production_ready")),
        "remaining_count": int(remaining.get("remaining_count") or 0),
        "alert_count": len(alerts),
        "urgent_count": len([item for item in alerts if item.get("urgent")]),
        "by_urgency": remaining.get("by_urgency", {}),
        "alerts": alerts,
    }


def generate_production_alert_notifications(state: dict[str, Any], report: dict[str, Any], actor: str) -> dict[str, Any]:
    payload = production_alerts_payload(state, report, actor)
    existing_keys = {
        str(item.get("production_alert_key"))
        for item in state.get("notifications", [])
        if isinstance(item, dict) and item.get("production_alert_key")
    }
    created: list[dict[str, Any]] = []
    for alert in payload.get("alerts", []):
        if not isinstance(alert, dict):
            continue
        key = str(alert.get("id") or "")
        if not key or key in existing_keys:
            continue
        notification = {
            "time": utc_now(),
            "from": str(alert.get("from") or "Production"),
            "title": str(alert.get("title") or "Production alert"),
            "text": str(alert.get("text") or ""),
            "urgent": bool(alert.get("urgent")),
            "read": False,
            "production_alert_key": key,
            "production_step_id": str(alert.get("production_step_id") or ""),
        }
        state.setdefault("notifications", []).insert(0, notification)
        existing_keys.add(key)
        created.append(notification)
    return {**payload, "created_count": len(created), "created_notifications": created}


def production_env_template_bytes() -> bytes:
    template_path = Path(__file__).with_name(".env.production.example")
    if not template_path.exists():
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "production env template is missing")
    raw = template_path.read_text(encoding="utf-8")
    if LOCAL_DEMO_PASSWORD in raw or "token_hash" in raw:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "production env template contains unsafe demo/runtime data")
    return raw.encode("utf-8")


def scrub_acceptance_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in {"token_hash", "password_hash", "password_salt", "stored_file"}:
                continue
            if "password" in lowered or "token" in lowered or "secret" in lowered or "api_key" in lowered:
                clean[key_text] = "REDACTED"
            else:
                clean[key_text] = scrub_acceptance_evidence(item)
        return clean
    if isinstance(value, list):
        return [scrub_acceptance_evidence(item) for item in value]
    if isinstance(value, str):
        text = value.replace(str(ROOT), ".")
        text = text.replace(LOCAL_DEMO_PASSWORD, "REDACTED")
        text = text.replace("official-sacc2-key-2026", "REDACTED")
        text = text.replace("token_hash", "runtime-token-digest")
        text = text.replace("stored_file", "stored-file-redacted")
        text = re.sub(r"(--password\s+)(\"[^\"]*\"|'[^']*'|\S+)", r"\1REDACTED", text)
        return text
    return value


def latest_acceptance_evidence_payload(actor: str) -> dict[str, Any]:
    evidence_path = ROOT / "outputs" / "acceptance-evidence-current.json"
    available = evidence_path.exists() and evidence_path.is_file()
    if available:
        try:
            raw_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raw_payload = {
                "format": "qurulush-acceptance-evidence-v1",
                "ok": False,
                "failed_stages": ["acceptance_evidence_read_error"],
                "stage_count": 0,
                "commands": [],
                "artifacts": [],
                "next_step": f"Пересоберите acceptance evidence: {exc}",
            }
            available = False
    else:
        raw_payload = {
            "format": "qurulush-acceptance-evidence-v1",
            "ok": False,
            "failed_stages": ["acceptance_evidence_missing"],
            "stage_count": 0,
            "commands": [
                {
                    "id": "collect_acceptance_evidence",
                    "command": "python3 ops/collect_acceptance_evidence.py --release dist/qurulush-hub-company-platform-current.zip --base-url https://YOUR-DOMAIN/ --email OWNER_EMAIL --password REDACTED --backups /var/lib/qurulush-hub/backups --require-production",
                }
            ],
            "artifacts": [],
            "next_step": "Соберите acceptance evidence после финального go/no-go.",
        }
    evidence = scrub_acceptance_evidence(raw_payload)
    exported = json.dumps(evidence, ensure_ascii=False).lower()
    if "demo2026" in exported or "token_hash" in exported or "official-sacc2-key-2026" in exported or "stored_file" in exported:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "acceptance evidence contains unsafe runtime data")
    stages = []
    go_no_go = evidence.get("go_no_go") if isinstance(evidence, dict) else None
    for item in (go_no_go or {}).get("stages", []) if isinstance(go_no_go, dict) else []:
        if isinstance(item, dict):
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            checks = result.get("checks", []) if isinstance(result, dict) else []
            stages.append(
                {
                    "name": str(item.get("name") or "-"),
                    "ok": bool(item.get("ok")),
                    "check_count": len(checks) if isinstance(checks, list) else 0,
                }
            )
    return {
        "format": "qurulush-acceptance-evidence-view-v1",
        "checked_at": utc_now(),
        "reported_by": actor,
        "available": available,
        "source": "outputs/acceptance-evidence-current.json",
        "ok": bool(evidence.get("ok")) if isinstance(evidence, dict) else False,
        "require_production": bool(evidence.get("require_production")) if isinstance(evidence, dict) else False,
        "failed_stages": list(evidence.get("failed_stages", [])) if isinstance(evidence, dict) else ["acceptance_evidence_invalid"],
        "stage_count": int(evidence.get("stage_count") or len(stages)) if isinstance(evidence, dict) else 0,
        "commands": evidence.get("commands", []) if isinstance(evidence, dict) else [],
        "stages": stages,
        "artifacts": evidence.get("artifacts", []) if isinstance(evidence, dict) else [],
        "evidence": evidence,
        "next_step": str(evidence.get("next_step") or "Повторите сбор evidence после финального go/no-go.") if isinstance(evidence, dict) else "Пересоберите acceptance evidence.",
    }


def latest_completion_audit_payload(actor: str) -> dict[str, Any]:
    audit_path = ROOT / "outputs" / "completion-audit-current.json"
    available = audit_path.exists() and audit_path.is_file()
    if available:
        try:
            raw_payload = json.loads(audit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raw_payload = {
                "format": "qurulush-completion-audit-v1",
                "local_handoff_ready": False,
                "production_ready": False,
                "overall_status": "completion_audit_read_error",
                "blocker_evidence": [],
                "checks": [
                    {
                        "id": "completion_audit_read_error",
                        "title": "Completion audit",
                        "status": "failed",
                        "evidence": f"Пересоберите completion audit: {exc}",
                        "next_step": "Запустить ops/completion_audit.py.",
                    }
                ],
            }
            available = False
    else:
        raw_payload = {
            "format": "qurulush-completion-audit-v1",
            "local_handoff_ready": False,
            "production_ready": False,
            "overall_status": "completion_audit_missing",
            "blocker_evidence": [],
            "checks": [
                {
                    "id": "completion_audit_missing",
                    "title": "Completion audit",
                    "status": "missing",
                    "evidence": "outputs/completion-audit-current.json не найден",
                    "next_step": "python3 ops/completion_audit.py --release dist/qurulush-hub-company-platform-current.zip --evidence outputs/acceptance-evidence-current.json --output outputs/completion-audit-current.json",
                }
            ],
        }
    audit = scrub_acceptance_evidence(raw_payload)
    exported = json.dumps(audit, ensure_ascii=False).lower()
    if "demo2026" in exported or "token_hash" in exported or "official-sacc2-key-2026" in exported or "stored_file" in exported:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "completion audit contains unsafe runtime data")
    checks = [item for item in audit.get("checks", []) if isinstance(item, dict)] if isinstance(audit, dict) else []
    return {
        "format": "qurulush-completion-audit-view-v1",
        "checked_at": utc_now(),
        "reported_by": actor,
        "available": available,
        "source": "outputs/completion-audit-current.json",
        "local_handoff_ready": bool(audit.get("local_handoff_ready")) if isinstance(audit, dict) else False,
        "production_ready": bool(audit.get("production_ready")) if isinstance(audit, dict) else False,
        "overall_status": str(audit.get("overall_status") or "unknown") if isinstance(audit, dict) else "unknown",
        "blocker_evidence": audit.get("blocker_evidence", []) if isinstance(audit, dict) else [],
        "proved_count": sum(1 for item in checks if item.get("status") == "proved"),
        "incomplete_count": sum(1 for item in checks if item.get("status") in {"missing", "failed", "incomplete_external", "unverified"}),
        "checks": checks,
        "audit": audit,
        "next_step": (
            "Локальная передача готова; для production нужно закрыть внешние blockers."
            if bool(audit.get("local_handoff_ready")) and not bool(audit.get("production_ready"))
            else (
                "Production готов: можно принимать боевой запуск по финальному go/no-go."
                if bool(audit.get("production_ready"))
                else "Пересоберите completion audit после исправления failed/missing стадий."
            )
        )
        if isinstance(audit, dict)
        else "Пересоберите completion audit.",
    }


def production_qa_evidence_payload(
    state: dict[str, Any],
    report: dict[str, Any],
    passport: dict[str, Any],
    actor: str,
    base_url: str,
) -> dict[str, Any]:
    plan = production_connection_plan(report)
    remaining = production_remaining_work_payload(state, report, actor)
    working_link = base_url.rstrip("/") + "/04_Строительная_компания.html"
    automated_checks = [
        {
            "id": "backend_regression",
            "title": "Backend/regression suite",
            "status": "command_to_refresh",
            "command": "python3 -m unittest -v test_company_platform_backend.py test_ops_backup_restore_drill.py test_ops_go_no_go_check.py test_ops_release_package.py test_ops_production_smoke.py",
            "evidence": "Должно завершиться строкой: Ran 129 tests ... OK или выше после добавления новых проверок.",
        },
        {
            "id": "browser_smoke",
            "title": "Browser smoke",
            "status": "command_to_refresh",
            "command": "node company_platform_server_smoke.mjs",
            "evidence": "Проверяет API, UI, Word-выгрузки, роли, документы, платежи, backup и launch flows.",
        },
        {
            "id": "responsive_smoke",
            "title": "Responsive smoke",
            "status": "command_to_refresh",
            "command": "node company_platform_responsive_smoke.mjs",
            "evidence": "Проверяет mobile, tablet, desktop и отсутствие горизонтального overflow.",
        },
        {
            "id": "accessibility_smoke",
            "title": "Accessibility smoke",
            "status": "command_to_refresh",
            "command": "node company_platform_accessibility_smoke.mjs",
            "evidence": "Проверяет labels, keyboard login, landmarks, aria-current и live-region.",
        },
        {
            "id": "live_smoke",
            "title": "Live smoke рабочей ссылки",
            "status": "current_api_checked",
            "command": "python3 ops/production_smoke_check.py --base-url https://YOUR-DOMAIN/ --email OWNER_EMAIL --password 'REAL_PASSWORD' --require-production",
            "evidence": f"Текущая локальная ссылка: local_ready={bool(report.get('local_ready'))}, production_ready={bool(report.get('production_ready'))}.",
        },
        {
            "id": "release_acceptance",
            "title": "Release acceptance",
            "status": "command_to_refresh",
            "command": "python3 ops/release_acceptance_check.py dist/qurulush-hub-company-platform-current.zip",
            "evidence": "Проверяет manifest SHA-256, runtime exclusions, Python compile, local preflight и deployment audit.",
        },
        {
            "id": "go_no_go",
            "title": "Финальный go/no-go",
            "status": "command_to_refresh",
            "command": "python3 ops/go_no_go_check.py --release dist/qurulush-hub-company-platform-current.zip --base-url https://YOUR-DOMAIN/ --email OWNER_EMAIL --password 'REAL_PASSWORD' --backups /var/lib/qurulush-hub/backups --require-production",
            "evidence": "Финальная приемка допускается только при ok=true и failed_stages=[].",
        },
        {
            "id": "acceptance_evidence",
            "title": "Acceptance evidence JSON",
            "status": "command_to_refresh",
            "command": "python3 ops/collect_acceptance_evidence.py --release dist/qurulush-hub-company-platform-current.zip --base-url https://YOUR-DOMAIN/ --email OWNER_EMAIL --password 'REAL_PASSWORD' --backups /var/lib/qurulush-hub/backups --require-production",
            "evidence": "Сохраняет outputs/acceptance-evidence-current.json без паролей, токенов и runtime-файлов.",
        },
    ]
    live_evidence = [
        {"id": "working_link", "title": "Рабочая ссылка", "status": "pass", "detail": working_link},
        {"id": "local_readiness", "title": "Локальная готовность", "status": "pass" if report.get("local_ready") else "fail", "detail": "local_ready=True" if report.get("local_ready") else "Есть локальные ошибки"},
        {"id": "production_readiness", "title": "Production readiness", "status": "pass" if report.get("production_ready") else "warning", "detail": "production_ready=True" if report.get("production_ready") else f"Открыто production-шагов: {remaining.get('remaining_count', 0)}"},
        {"id": "acceptance_passport", "title": "Паспорт приемки", "status": "pass" if passport.get("local_acceptance") else "warning", "detail": f"local_acceptance={passport.get('local_acceptance')}; production_acceptance={passport.get('production_acceptance')}"},
        {"id": "backup_verify", "title": "Проверка backup", "status": str(passport.get("backup_status") or "warning"), "detail": str(passport.get("backup_detail") or "")},
        {"id": "qa_word_export", "title": "Word QA-пакет", "status": "pass", "detail": "/api/production/qa-evidence.docx"},
        {"id": "acceptance_evidence_json", "title": "Acceptance evidence JSON", "status": "pass" if (ROOT / "outputs" / "acceptance-evidence-current.json").exists() else "warning", "detail": "/api/acceptance/evidence.json"},
        {"id": "completion_audit_json", "title": "Completion audit JSON", "status": "pass" if (ROOT / "outputs" / "completion-audit-current.json").exists() else "warning", "detail": "/api/acceptance/completion-audit.json"},
        {"id": "launch_bundle", "title": "Launch bundle", "status": "pass", "detail": "/api/production/launch-bundle.zip"},
    ]
    artifacts = [
        {"id": "working_url", "title": "Рабочая ссылка", "path": working_link, "type": "url"},
        {"id": "current_release_zip", "title": "Актуальный release ZIP", "path": "dist/qurulush-hub-company-platform-current.zip", "type": "file"},
        {"id": "test_report", "title": "Тестовый отчет", "path": "TEST_REPORT_COMPANY_PLATFORM.md", "type": "file"},
        {"id": "readiness_checklist", "title": "Readiness checklist", "path": "READINESS_CHECKLIST.md", "type": "file"},
        {"id": "runbook", "title": "Инструкция запуска", "path": "RUN_COMPANY_PLATFORM.md", "type": "file"},
        {"id": "production_runbook", "title": "Production runbook", "path": "ops/README_PRODUCTION.md", "type": "file"},
        {"id": "acceptance_evidence_current", "title": "Acceptance evidence JSON", "path": "outputs/acceptance-evidence-current.json", "type": "file"},
        {"id": "completion_audit_current", "title": "Completion audit JSON", "path": "outputs/completion-audit-current.json", "type": "file"},
    ]
    return {
        "format": "qurulush-production-qa-evidence-v1",
        "checked_at": utc_now(),
        "reported_by": actor,
        "working_link": working_link,
        "local_ready": bool(report.get("local_ready")),
        "production_ready": bool(report.get("production_ready")),
        "local_acceptance": bool(passport.get("local_acceptance")),
        "production_acceptance": bool(passport.get("production_acceptance")),
        "completion_percent": int(plan.get("completion_percent") or 0),
        "remaining_count": int(remaining.get("remaining_count") or 0),
        "blocker_count": int(plan.get("blocker_count") or 0),
        "automated_checks": automated_checks,
        "live_evidence": live_evidence,
        "artifacts": artifacts,
        "next_step": (
            "Локальная рабочая платформа проверена. Для production закройте внешние gates и повторите go/no-go с --require-production."
            if not report.get("production_ready")
            else "Production gates закрыты; выполните финальную приемку директором и сохраните go/no-go JSON."
        ),
    }


def production_status_board_payload(
    state: dict[str, Any],
    report: dict[str, Any],
    passport: dict[str, Any],
    actor: str,
    base_url: str,
) -> dict[str, Any]:
    plan = production_connection_plan(report)
    remaining = production_remaining_work_payload(state, report, actor)
    qa_evidence = production_qa_evidence_payload(state, report, passport, actor, base_url)
    working_link = qa_evidence.get("working_link") or base_url.rstrip("/") + "/04_Строительная_компания.html"
    top_actions = [item for item in remaining.get("top_actions", []) if isinstance(item, dict)]
    steps = [item for item in remaining.get("steps", []) if isinstance(item, dict)]
    summary_cards = [
        {"id": "working_link", "title": "Рабочая ссылка", "value": working_link, "status": "pass"},
        {"id": "local_ready", "title": "Локальная готовность", "value": "Готово" if report.get("local_ready") else "Проверить", "status": "pass" if report.get("local_ready") else "fail"},
        {"id": "production_ready", "title": "Production", "value": "Готово" if report.get("production_ready") else "Не готово", "status": "pass" if report.get("production_ready") else "warning"},
        {"id": "remaining", "title": "Осталось", "value": f"{remaining.get('remaining_count', 0)} шагов", "status": "pass" if not remaining.get("remaining_count") else "warning"},
        {"id": "blockers", "title": "Блокеры", "value": str(plan.get("blocker_count", 0)), "status": "pass" if not plan.get("blocker_count") else "warning"},
        {"id": "qa", "title": "QA evidence", "value": "Собран", "status": "pass"},
        {
            "id": "acceptance_evidence",
            "title": "Acceptance evidence",
            "value": "Есть" if (ROOT / "outputs" / "acceptance-evidence-current.json").exists() else "Нет",
            "status": "pass" if (ROOT / "outputs" / "acceptance-evidence-current.json").exists() else "warning",
        },
    ]
    return {
        "format": "qurulush-production-status-board-v1",
        "checked_at": utc_now(),
        "reported_by": actor,
        "working_link": working_link,
        "local_ready": bool(report.get("local_ready")),
        "production_ready": bool(report.get("production_ready")),
        "local_acceptance": bool(passport.get("local_acceptance")),
        "production_acceptance": bool(passport.get("production_acceptance")),
        "completion_percent": int(plan.get("completion_percent") or 0),
        "required_ready_count": int(plan.get("required_ready_count") or 0),
        "required_total": int(plan.get("required_total") or 0),
        "remaining_count": int(remaining.get("remaining_count") or 0),
        "blocker_count": int(plan.get("blocker_count") or 0),
        "summary_cards": summary_cards,
        "current_step": remaining.get("current_step"),
        "top_actions": top_actions,
        "steps": steps,
        "qa_checks": qa_evidence.get("automated_checks", []),
        "artifacts": qa_evidence.get("artifacts", []),
        "next_step": (
            "Сначала закройте ближайшие действия и приложите доказательства. После этого повторите live smoke и финальный go/no-go."
            if remaining.get("remaining_count")
            else "Все production blockers закрыты. Запустите финальный go/no-go и сохраните решение директора."
        ),
    }


def build_production_launch_bundle(
    state: dict[str, Any],
    report: dict[str, Any],
    passport: dict[str, Any],
    actor: str,
    account_cutover: dict[str, Any],
    base_url: str = "http://127.0.0.1:8782/",
) -> bytes:
    access_matrix = access_matrix_payload(state, actor)
    plan = production_connection_plan(report)
    evidence = production_evidence_payload(state, report, actor)
    request_pack = production_request_pack_payload(state, report, actor)
    official_letters = production_official_letters_payload(state, report, actor)
    action_board = production_action_board_payload(state, report, actor)
    launch_sequence = production_launch_sequence_payload(state, report, actor)
    remaining_work = production_remaining_work_payload(state, report, actor)
    top_actions = production_top_actions_payload(state, report, actor)
    production_alerts = production_alerts_payload(state, report, actor)
    interaction_map = interaction_map_payload(state, actor)
    future_roadmap = future_roadmap_payload(actor)
    checklist = production_launch_checklist(report)
    legal_packet = legal_verification_packet_payload(state, actor)
    qa_evidence = production_qa_evidence_payload(state, report, passport, actor, base_url)
    status_board = production_status_board_payload(state, report, passport, actor, base_url)
    acceptance_evidence = latest_acceptance_evidence_payload(actor)
    completion_audit = latest_completion_audit_payload(actor)
    readme = "\n".join(
        [
            "Qurulush Hub - пакет запуска строительной компании",
            "",
            "Назначение",
            "Этот архив передается директору, DevOps, юристу, бухгалтеру и IT-исполнителю перед боевым запуском платформы.",
            "",
            "Что внутри",
            "1. production-plan.json и qurulush-production-plan.docx - план подключения production-зависимостей.",
            "2. production-evidence-register.json и qurulush-production-evidence-register.docx - реестр доказательств по каждому production gate.",
            "3. production-request-pack.json и qurulush-production-request-pack.docx - кому направить запросы для закрытия blockers.",
            "4. production-official-letters.json и qurulush-production-official-letters.docx - проекты официальных писем и заявок.",
            "5. production-account-cutover.json и qurulush-production-account-cutover.docx - переход с demo-доступов на реальные роли компании.",
            "6. company-access-matrix.json и qurulush-company-access-matrix.docx - роли, права, объекты и ограничения сотрудников.",
            "7. dgask-interaction-map.json и qurulush-dgask-interaction-map.docx - карта взаимодействия с инспектором, Минстроем, ДГАСК и sacc2.",
            "8. production-action-board.json и qurulush-production-action-board.docx - карточки закрытия blockers по ролям.",
            "9. production-launch-sequence.json и qurulush-production-launch-sequence.docx - пошаговая карта запуска с зависимостями.",
            "10. production-remaining-work.json и qurulush-production-remaining-work.docx - что осталось до боевого запуска по шагам, владельцам и доказательствам.",
            "11. production-top-actions.json и qurulush-production-top-actions.docx - короткий список ближайших действий по срочности.",
            "12. production-alerts.json - предупреждения для журнала уведомлений по просроченным, сегодняшним и ближайшим production-шагам.",
            "13. production-launch-checklist.json и qurulush-production-launch-checklist.docx - чеклист запуска и команды приемки.",
            "14. acceptance-passport.json и qurulush-acceptance-passport.docx - паспорт текущей технической приемки.",
            "15. legal-verification-packet.json и qurulush-legal-verification-packet.docx - пакет юридической сверки НПА, тарифов, штрафов, форм и ролей.",
            "16. qa-evidence.json и qurulush-qa-evidence.docx - пакет доказательств тестовой проверки, рабочей ссылки и актуальных команд QA.",
            "17. production-status-board.json и qurulush-production-status-board.docx - единый директорский статус запуска, рабочая ссылка, тесты и шаги.",
            "18. acceptance-evidence-current.json - последний очищенный JSON финальной приемки без паролей и токенов.",
            "19. completion-audit-current.json - итоговый аудит готовности: что доказано и какие production blockers остались.",
            "20. future-roadmap.json - будущий контур мобильной field-версии и платежной оркестрации Кыргызстана.",
            "21. company-platform.env.example - безопасный шаблон production-переменных без паролей и токенов.",
            "",
            "Порядок работы",
            "1. Назначить домен и HTTPS.",
            "2. Заполнить production env реальными значениями.",
            "3. Закрыть evidence-регистр: приложить письма, ссылки, акты, договоры и даты по каждому production gate.",
            "4. Подключить sacc2, ЭЦП, платежи, storage, AV scanner и remote backup.",
            "5. Сверить правовой справочник с действующими НПА и регламентами.",
            "6. Запустить go/no-go из чеклиста и принять только JSON ok=true без failed_stages.",
            "",
            f"Сформировано: {utc_now()}",
            f"Выгрузил: {actor}",
            "",
        ]
    )
    files: dict[str, bytes] = {
        "README_LAUNCH_PACKET.txt": readme.encode("utf-8"),
        "company-platform.env.example": production_env_template_bytes(),
        "production-account-cutover.json": json.dumps(account_cutover, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-account-cutover.docx": build_production_account_cutover_docx(account_cutover),
        "company-access-matrix.json": json.dumps(access_matrix, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-company-access-matrix.docx": build_access_matrix_docx(access_matrix),
        "production-plan.json": json.dumps(plan, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-plan.docx": build_production_plan_docx(plan),
        "production-evidence-register.json": json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-evidence-register.docx": build_production_evidence_docx(evidence),
        "production-request-pack.json": json.dumps(request_pack, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-request-pack.docx": build_production_request_pack_docx(request_pack),
        "production-official-letters.json": json.dumps(official_letters, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-official-letters.docx": build_production_official_letters_docx(official_letters),
        "dgask-interaction-map.json": json.dumps(interaction_map, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-dgask-interaction-map.docx": build_interaction_map_docx(interaction_map),
        "future-roadmap.json": json.dumps(future_roadmap, ensure_ascii=False, indent=2).encode("utf-8"),
        "production-action-board.json": json.dumps(action_board, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-action-board.docx": build_production_action_board_docx(action_board),
        "production-launch-sequence.json": json.dumps(launch_sequence, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-launch-sequence.docx": build_production_launch_sequence_docx(launch_sequence),
        "production-remaining-work.json": json.dumps(remaining_work, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-remaining-work.docx": build_production_remaining_work_docx(remaining_work),
        "production-top-actions.json": json.dumps(top_actions, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-top-actions.docx": build_production_top_actions_docx(top_actions),
        "production-alerts.json": json.dumps(production_alerts, ensure_ascii=False, indent=2).encode("utf-8"),
        "production-launch-checklist.json": json.dumps(checklist, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-launch-checklist.docx": build_production_launch_checklist_docx(checklist),
        "acceptance-passport.json": json.dumps(passport, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-acceptance-passport.docx": build_acceptance_passport_docx(passport),
        "legal-verification-packet.json": json.dumps(legal_packet, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-legal-verification-packet.docx": build_legal_verification_packet_docx(legal_packet),
        "qa-evidence.json": json.dumps(qa_evidence, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-qa-evidence.docx": build_production_qa_evidence_docx(qa_evidence),
        "production-status-board.json": json.dumps(status_board, ensure_ascii=False, indent=2).encode("utf-8"),
        "qurulush-production-status-board.docx": build_production_status_board_docx(status_board),
        "acceptance-evidence-current.json": json.dumps(acceptance_evidence, ensure_ascii=False, indent=2).encode("utf-8"),
        "completion-audit-current.json": json.dumps(completion_audit, ensure_ascii=False, indent=2).encode("utf-8"),
    }
    exported = b"\n".join(files.values()).lower()
    if b"demo2026" in exported or b"token_hash" in exported or b"stored_file" in exported:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "launch bundle contains unsafe runtime data")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, raw in files.items():
            package.writestr(name, raw)
    return buffer.getvalue()


def build_deployment_files_bundle(
    *,
    domain: str,
    admin_email: str,
    app_root: Path = Path("/opt/qurulush-hub"),
    runtime_root: Path = Path("/var/lib/qurulush-hub"),
    env_file: Path = Path("/etc/qurulush-hub/company-platform.env"),
    port: int = 8781,
) -> bytes:
    try:
        domain = validate_domain(domain)
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
    admin_email = admin_email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", admin_email):
        raise ApiError(HTTPStatus.BAD_REQUEST, "admin_email must be a valid email")
    if port < 1024 or port > 65535:
        raise ApiError(HTTPStatus.BAD_REQUEST, "port must be between 1024 and 65535")
    with tempfile.TemporaryDirectory(prefix="qurulush-deployment-files-") as tmp:
        out = Path(tmp)
        result = render_deployment_files(
            domain=domain,
            output_dir=out,
            app_root=app_root,
            runtime_root=runtime_root,
            env_file=env_file,
            admin_email=admin_email,
            port=port,
        )
        readme = "\n".join(
            [
                "Qurulush Hub - deployment files",
                "",
                f"Domain: {domain}",
                f"Admin email: {admin_email}",
                "",
                "Install order",
                "1. Copy nginx-qurulush-hub.conf to /etc/nginx/sites-available/qurulush-hub.conf and enable it.",
                "2. Copy qurulush-hub.service to /etc/systemd/system/qurulush-hub.service.",
                "3. Fill /etc/qurulush-hub/company-platform.env with real production values.",
                "4. Put the release package under /opt/qurulush-hub and create /var/lib/qurulush-hub.",
                "5. Run go-no-go-command.sh only after HTTPS, env, hooks, backup and legal verification are ready.",
                "",
            ]
        )
        files = {
            "README_DEPLOYMENT_FILES.txt": readme.encode("utf-8"),
            "qurulush-hub.service": (out / "qurulush-hub.service").read_bytes(),
            "nginx-qurulush-hub.conf": (out / "nginx-qurulush-hub.conf").read_bytes(),
            "go-no-go-command.sh": (out / "go-no-go-command.sh").read_bytes(),
            "DEPLOYMENT_SUMMARY.json": json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        }
    exported = b"\n".join(files.values()).lower()
    if b"company.example" in exported or b"demo2026" in exported or b"token_hash" in exported:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "deployment bundle contains unsafe placeholder data")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, raw in files.items():
            package.writestr(name, raw)
    return buffer.getvalue()


def probe_public_https_url(url: str, timeout: float = 5.0) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "QurulushHub-GoNoGo/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", 0) or response.getcode())
            headers = {key.lower(): value for key, value in response.headers.items()}
    except ssl.SSLError as exc:
        return {
            "status": "fail",
            "checks": [
                {"id": "tls_handshake", "title": "TLS handshake", "status": "fail", "detail": f"TLS не подтвержден: {exc.__class__.__name__}"}
            ],
        }
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return {
            "status": "fail",
            "checks": [
                {"id": "https_reachable", "title": "Публичная доступность", "status": "fail", "detail": f"HTTPS endpoint недоступен: {reason.__class__.__name__}"}
            ],
        }
    except Exception as exc:
        return {
            "status": "fail",
            "checks": [
                {"id": "https_reachable", "title": "Публичная доступность", "status": "fail", "detail": f"HTTPS endpoint недоступен: {exc.__class__.__name__}"}
            ],
        }

    checks.append(
        {
            "id": "https_reachable",
            "title": "Публичная доступность",
            "status": "pass" if 200 <= status_code < 500 else "fail",
            "detail": f"HTTP status {status_code}",
        }
    )
    header_requirements = (
        ("strict-transport-security", "HSTS"),
        ("content-security-policy", "Content-Security-Policy"),
        ("x-content-type-options", "X-Content-Type-Options"),
        ("x-frame-options", "X-Frame-Options"),
        ("referrer-policy", "Referrer-Policy"),
    )
    for header, title in header_requirements:
        checks.append(
            {
                "id": f"header_{header.replace('-', '_')}",
                "title": title,
                "status": "pass" if headers.get(header) else "fail",
                "detail": "Header найден" if headers.get(header) else "Header отсутствует",
            }
        )
    return {"status": "pass" if all(item["status"] == "pass" for item in checks) else "fail", "checks": checks}


def validate_domain_https_payload(domain: str, public_url: str = "", port: int = 8781, probe_live: bool = False) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    try:
        normalized_domain = validate_domain(domain)
    except ValueError as exc:
        normalized_domain = domain.strip().lower()
        issues.append(env_validation_issue("domain_format", "Домен", "fail", str(exc), "domain"))
    if port < 1024 or port > 65535:
        issues.append(env_validation_issue("backend_port", "Порт backend", "fail", "Порт backend должен быть в диапазоне 1024-65535", "port"))

    public_url = public_url.strip()
    url = public_url or (f"https://{normalized_domain}/" if normalized_domain else "")
    parsed = urlparse(url)
    if not url:
        issues.append(env_validation_issue("public_url_missing", "Публичный URL", "missing", "Укажите публичный HTTPS URL платформы", "public_url"))
    elif parsed.scheme != "https":
        issues.append(env_validation_issue("public_url_https", "HTTPS", "fail", "Публичный URL должен начинаться с https://", "public_url"))
    if normalized_domain and parsed.netloc and parsed.hostname != normalized_domain:
        issues.append(env_validation_issue("public_url_domain", "Домен в URL", "fail", "Hostname публичного URL должен совпадать с доменом", "public_url"))

    required_confirmations = [
        {"id": "dns_a_record", "title": "DNS A/AAAA запись", "detail": f"Домен {normalized_domain or 'DOMAIN'} должен указывать на IP production-сервера."},
        {"id": "tls_certificate", "title": "TLS-сертификат", "detail": "Нужно выпустить доверенный сертификат и подключить его в nginx."},
        {"id": "nginx_proxy", "title": "Nginx reverse proxy", "detail": f"Nginx должен проксировать HTTPS-трафик на 127.0.0.1:{port}."},
        {"id": "security_headers", "title": "Security headers", "detail": "После запуска live-smoke должен подтвердить CSP, HSTS, nosniff и frame policy."},
    ]
    live_probe = {"status": "not_requested", "checks": []}
    if probe_live and parsed.scheme == "https" and not any(item.get("status") == "fail" for item in issues):
        live_probe = probe_public_https_url(url)
        for item in live_probe.get("checks", []):
            if item.get("status") == "fail":
                issues.append(env_validation_issue(f"live_{item.get('id')}", str(item.get("title", "Live HTTPS")), "fail", str(item.get("detail", "Live HTTPS check failed")), "public_url"))

    ready_for_files = not any(item.get("status") == "fail" for item in issues if not str(item.get("id", "")).startswith("live_"))
    ready_for_live = bool(probe_live) and live_probe.get("status") == "pass"
    return {
        "format": "qurulush-domain-https-validation-v1",
        "checked_at": utc_now(),
        "domain": normalized_domain,
        "public_url": url,
        "backend_port": port,
        "ready_for_deployment_files": ready_for_files,
        "live_probe_requested": bool(probe_live),
        "ready_for_live_https": ready_for_live,
        "live_probe": live_probe,
        "issue_count": len(issues),
        "issues": issues,
        "required_confirmations": required_confirmations,
        "next_step": (
            f"Скачайте Deployment ZIP для {normalized_domain} и примените nginx/systemd на сервере."
            if ready_for_files
            else "Исправьте домен, публичный HTTPS URL или порт backend перед генерацией deployment-файлов."
        ),
    }


def production_launch_checklist(report: dict[str, Any]) -> dict[str, Any]:
    plan = production_connection_plan(report)
    checks_by_id = {str(item.get("id")): item for item in report.get("checks", []) if isinstance(item, dict)}

    def status_for(*ids: str) -> str:
        statuses = [str(checks_by_id.get(item_id, {}).get("status") or "missing") for item_id in ids]
        if all(status == "pass" for status in statuses):
            return "pass"
        if any(status == "fail" for status in statuses):
            return "fail"
        if any(status == "warning" for status in statuses):
            return "warning"
        return "missing"

    stages = [
        {
            "id": "release_package",
            "title": "Собрать чистый release-архив",
            "status": "pass",
            "owner": "DevOps",
            "evidence": "dist/qurulush-hub-company-platform-current.zip + RELEASE_MANIFEST.json",
            "next_step": "Перед переносом на VPS запустить release acceptance-check.",
        },
        {
            "id": "server_environment",
            "title": "Заполнить production env",
            "status": status_for("corporate_auth", "bootstrap_admin", "production_env_values"),
            "owner": "Директор / DevOps",
            "evidence": "QH_BOOTSTRAP_ADMIN_*, QH_DISABLE_DEMO_USERS, QH_REQUIRE_PRODUCTION",
            "next_step": "Скачать .env шаблон из кабинета, заменить заглушки реальными значениями и хранить файл вне git/chat.",
        },
        {
            "id": "https_runtime",
            "title": "Запустить домен и HTTPS",
            "status": status_for("https"),
            "owner": "DevOps",
            "evidence": "nginx/systemd + TLS certificate",
            "next_step": "Поднять backend за HTTPS reverse proxy и проверить security headers.",
        },
        {
            "id": "external_integrations",
            "title": "Подключить внешние контуры",
            "status": status_for("hook_json_contracts", "sacc2_api", "eds", "payments", "object_storage", "av_scan"),
            "owner": "IT / Минстрой / бухгалтер / юрист",
            "evidence": "QH_REQUIRE_HOOK_JSON=1, sacc2, ЭЦП, платежи, storage и AV hooks",
            "next_step": "Получить реальные доступы, настроить hook-команды и выполнить smoke без demo-провайдеров.",
        },
        {
            "id": "backup_recovery",
            "title": "Закрыть резервное копирование",
            "status": status_for("backup_freshness", "backup_schedule", "backup_remote"),
            "owner": "DevOps / служба безопасности",
            "evidence": "локальная копия, remote manifest, restore-drill",
            "next_step": "Проверить регулярный backup, удаленную выгрузку manifest и восстановление во временную базу.",
        },
        {
            "id": "legal_catalog",
            "title": "Сверить правовой справочник",
            "status": status_for("reference_catalog"),
            "owner": "Юрист / разрешитель",
            "evidence": "QH_REFERENCE_VERIFIED_AT или QH_LEGAL_CATALOG_VERIFIED_AT",
            "next_step": "Проверить актуальные НПА, тарифы, формы, сроки и штрафы перед боевым использованием.",
        },
        {
            "id": "final_acceptance",
            "title": "Финальная приемка",
            "status": "pass" if plan.get("production_ready") else "missing",
            "owner": "Директор / DevOps",
            "evidence": "production_smoke_check --require-production + go_no_go_check",
            "next_step": "После закрытия всех блокеров запустить приемочные команды и зафиксировать JSON ok=true.",
        },
    ]
    commands = [
        {
            "id": "preflight",
            "title": "Проверка env без запуска порта",
            "command": "python3 company_platform_server.py --preflight-json --require-production",
        },
        {
            "id": "release_acceptance",
            "title": "Проверка release-архива",
            "command": "python3 ops/release_acceptance_check.py dist/qurulush-hub-company-platform-current.zip",
        },
        {
            "id": "live_smoke",
            "title": "Проверка поднятой платформы",
            "command": "python3 ops/production_smoke_check.py --base-url https://YOUR-DOMAIN/ --email OWNER_EMAIL --password 'REAL_PASSWORD' --require-production",
        },
        {
            "id": "go_no_go",
            "title": "Финальный go/no-go",
            "command": "python3 ops/go_no_go_check.py --release dist/qurulush-hub-company-platform-current.zip --deployment-root /opt/qurulush-hub --env /etc/qurulush-hub/company-platform.env --base-url https://YOUR-DOMAIN/ --email OWNER_EMAIL --password 'REAL_PASSWORD' --backups /var/lib/qurulush-hub/backups --hook-contract-smoke --require-production-config --require-production",
        },
    ]
    return {
        "format": "qurulush-production-launch-checklist-v1",
        "checked_at": report.get("checked_at") or utc_now(),
        "production_ready": bool(plan.get("production_ready")),
        "blocker_count": plan.get("blocker_count", 0),
        "blockers": plan.get("blockers", []),
        "stages": stages,
        "commands": commands,
    }


def reject_unsafe_upload(raw: bytes) -> None:
    executable_signatures = (
        b"MZ",
        b"\x7fELF",
        b"\xcf\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xca\xfe\xba\xbe",
    )
    if raw.startswith(executable_signatures):
        raise ApiError(HTTPStatus.BAD_REQUEST, "unsafe executable file content")


def av_scanner_command() -> list[str] | None:
    raw = os.environ.get("QH_AV_SCANNER_CMD", "").strip() or os.environ.get("QH_AV_SCANNER", "").strip()
    if not raw:
        return None
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid antivirus scanner command") from exc
    if not command:
        return None
    return command


def scan_upload_with_av(raw: bytes, filename: str) -> None:
    command = av_scanner_command()
    if not command:
        return

    suffix = Path(safe_filename(filename)).suffix or ".upload"
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix="qh-upload-", suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_name = tmp.name

        prepared = [part.replace("{file}", tmp_name) for part in command]
        if "{file}" not in command:
            prepared.append(tmp_name)

        try:
            result = subprocess.run(
                prepared,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=AV_SCAN_TIMEOUT_SECONDS,
                check=False,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "antivirus scanner is not available") from exc
        except subprocess.TimeoutExpired as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "antivirus scanner timeout") from exc

        if result.returncode != 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, "uploaded file rejected by antivirus scanner")
        parse_hook_json_output(result.stdout or "", "av_scanner", {"ok", "clean"})
    finally:
        if tmp_name:
            try:
                Path(tmp_name).unlink()
            except FileNotFoundError:
                pass


def require_hook_json_contract() -> bool:
    return env_truthy("QH_REQUIRE_HOOK_JSON")


def parse_hook_json_output(stdout: str, hook_name: str, allowed_statuses: set[str]) -> dict[str, str]:
    if not require_hook_json_contract():
        return {}
    raw = stdout.strip()
    if not raw:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, f"{hook_name} command must return JSON when QH_REQUIRE_HOOK_JSON=1")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, f"{hook_name} command returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, f"{hook_name} command returned non-object JSON")
    status = str(payload.get("status", "")).strip().lower()
    ok = payload.get("ok")
    if ok is True and not status:
        status = "ok"
    if status not in allowed_statuses:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, f"{hook_name} command returned unacceptable status")
    clean: dict[str, str] = {}
    for key in ("status", "external_id", "reference", "provider", "remote_url"):
        value = payload.get(key)
        if isinstance(value, (str, int, float)) and not value_looks_placeholder(str(value)):
            clean[f"{hook_name}_{key}"] = str(value)[:160]
    return clean


def storage_sync_command() -> list[str] | None:
    raw = os.environ.get("QH_STORAGE_SYNC_CMD", "").strip()
    if not raw:
        return None
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid storage sync command") from exc
    if not command:
        return None
    return command


def storage_sync_timeout_seconds() -> int:
    raw = os.environ.get("QH_STORAGE_SYNC_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return STORAGE_SYNC_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid storage sync timeout") from exc
    if timeout <= 0:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid storage sync timeout")
    return timeout


def sync_upload_to_storage(file_path: Path, doc_id: str, filename: str) -> dict[str, Any]:
    command = storage_sync_command()
    if not command:
        return {}
    storage_url = os.environ.get("QH_STORAGE_URL", "").strip()
    replacements = {
        "{file}": str(file_path),
        "{doc_id}": safe_filename(doc_id),
        "{filename}": filename,
        "{storage_url}": storage_url,
    }
    prepared = replace_command_markers(command, replacements)
    if "{file}" not in command:
        prepared.append(str(file_path))
    try:
        result = subprocess.run(
            prepared,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=storage_sync_timeout_seconds(),
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "storage sync command is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "storage sync command timeout") from exc
    if result.returncode != 0:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "storage sync command failed")
    hook_info = parse_hook_json_output(result.stdout or "", "storage", {"ok", "stored", "uploaded", "synced"})
    return {
        "storage_mode": os.environ.get("QH_STORAGE_MODE", "").strip() or "external",
        "storage_synced_at": utc_now(),
        **hook_info,
    }


def payment_gateway_command() -> list[str] | None:
    raw = os.environ.get("QH_PAYMENT_GATEWAY_CMD", "").strip()
    if not raw:
        return None
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid payment gateway command") from exc
    if not command:
        return None
    return command


def payment_gateway_timeout_seconds() -> int:
    raw = os.environ.get("QH_PAYMENT_GATEWAY_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return PAYMENT_GATEWAY_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid payment gateway timeout") from exc
    if timeout <= 0:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid payment gateway timeout")
    return timeout


def confirm_payment_with_gateway(item: dict[str, Any], user: dict[str, Any], payment_no: str, receipt: str) -> dict[str, str]:
    command = payment_gateway_command()
    if not command:
        return {}

    payload = {
        "payment_id": item.get("id"),
        "title": item.get("title"),
        "object": item.get("object"),
        "amount": item.get("amount"),
        "payment_no": payment_no,
        "receipt": receipt,
        "paid_by": user.get("name"),
        "paid_by_email": user.get("email"),
        "submitted_at": utc_now(),
        "gateway_url": os.environ.get("QH_PAYMENT_GATEWAY_URL", "").strip(),
    }
    payload_file = None
    try:
        with tempfile.NamedTemporaryFile(prefix="qh-payment-", suffix=".json", mode="w", encoding="utf-8", delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            payload_file = tmp.name

        replacements = {
            "{payload}": payload_file,
            "{payment_id}": safe_filename(str(item.get("id", "payment"))),
            "{payment_no}": safe_filename(payment_no),
            "{gateway_url}": payload["gateway_url"],
        }
        prepared = replace_command_markers(command, replacements)
        if "{payload}" not in command:
            prepared.append(payload_file)
        try:
            result = subprocess.run(
                prepared,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=payment_gateway_timeout_seconds(),
                check=False,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "payment gateway command is not available") from exc
        except subprocess.TimeoutExpired as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "payment gateway command timeout") from exc
        if result.returncode != 0:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "payment gateway command failed")
        hook_info = parse_hook_json_output(result.stdout or "", "payment_gateway", {"ok", "confirmed", "paid"})
    finally:
        if payload_file:
            try:
                Path(payload_file).unlink()
            except FileNotFoundError:
                pass

    return {"payment_gateway_status": "confirmed", "payment_gateway_synced_at": utc_now(), **hook_info}


def eds_sign_command() -> list[str] | None:
    raw = os.environ.get("QH_EDS_SIGN_CMD", "").strip()
    if not raw:
        return None
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid EDS signing command") from exc
    if not command:
        return None
    return command


def eds_sign_timeout_seconds() -> int:
    raw = os.environ.get("QH_EDS_SIGN_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return EDS_SIGN_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid EDS signing timeout") from exc
    if timeout <= 0:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid EDS signing timeout")
    return timeout


def sign_document_with_eds(doc: dict[str, Any], user: dict[str, Any], comment: str) -> dict[str, str]:
    command = eds_sign_command()
    if not command:
        return {
            "signature_status": "signed-local",
            "signed_at": utc_now(),
            "signed_by": user["name"],
            "signature_comment": comment,
        }

    payload = {
        "document_id": doc.get("id"),
        "title": doc.get("title"),
        "object": doc.get("object"),
        "file": doc.get("file"),
        "file_sha256": doc.get("file_sha256"),
        "signed_by": user.get("name"),
        "signed_by_email": user.get("email"),
        "comment": comment,
        "submitted_at": utc_now(),
        "eds_provider": os.environ.get("QH_EDS_PROVIDER", "").strip(),
        "eds_api_url": os.environ.get("QH_EDS_API_URL", "").strip(),
    }
    payload_file = None
    try:
        with tempfile.NamedTemporaryFile(prefix="qh-eds-", suffix=".json", mode="w", encoding="utf-8", delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            payload_file = tmp.name

        replacements = {
            "{payload}": payload_file,
            "{document_id}": safe_filename(str(doc.get("id", "document"))),
            "{eds_api_url}": payload["eds_api_url"],
        }
        prepared = replace_command_markers(command, replacements)
        if "{payload}" not in command:
            prepared.append(payload_file)
        try:
            result = subprocess.run(
                prepared,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=eds_sign_timeout_seconds(),
                check=False,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "EDS signing command is not available") from exc
        except subprocess.TimeoutExpired as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "EDS signing command timeout") from exc
        if result.returncode != 0:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "EDS signing command failed")
        hook_info = parse_hook_json_output(result.stdout or "", "eds", {"ok", "signed"})
    finally:
        if payload_file:
            try:
                Path(payload_file).unlink()
            except FileNotFoundError:
                pass

    return {
        "signature_status": "signed",
        "signed_at": utc_now(),
        "signed_by": user["name"],
        "signature_comment": comment,
        **hook_info,
    }


def store_uploaded_file(upload_root: Path, doc_id: str, filename: str, content_b64: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(content_b64, validate=True)
    except Exception as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid base64 file content") from exc
    if not raw:
        raise ApiError(HTTPStatus.BAD_REQUEST, "uploaded file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "uploaded file is too large")
    cleaned = validate_upload_filename(filename)
    reject_unsafe_upload(raw)
    scan_upload_with_av(raw, cleaned)
    upload_root.mkdir(parents=True, exist_ok=True)
    stored_name = f"{safe_filename(doc_id)}-{secrets.token_hex(6)}-{cleaned}"
    target = (upload_root / stored_name).resolve()
    if upload_root.resolve() not in target.parents:
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid upload path")
    try:
        target.write_bytes(raw)
        storage_info = sync_upload_to_storage(target, doc_id, cleaned)
    except Exception:
        if target.exists():
            target.unlink()
        raise
    metadata = {
        "file": cleaned,
        "stored_file": stored_name,
        "file_url": f"/api/documents/{quote(safe_filename(doc_id))}/file",
        "file_size": len(raw),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
    }
    metadata.update(storage_info)
    return metadata


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_sqlite_backup(db_path: Path, backup_root: Path, actor: str) -> dict[str, Any]:
    init_db(db_path)
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    target = (backup_root / f"company_platform_{stamp}_{secrets.token_hex(3)}.sqlite3").resolve()
    if backup_root.resolve() not in target.parents:
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid backup path")
    with open_db(db_path) as source, sqlite3.connect(target) as dest:
        source.backup(dest)
    manifest = {
        "created_at": utc_now(),
        "created_by": actor,
        "database": str(db_path),
        "backup": str(target),
        "size": target.stat().st_size,
        "sha256": sha256_file(target),
    }
    manifest_path = target.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    remote_synced = sync_backup_to_remote(target, manifest_path)
    if remote_synced:
        manifest["remote_synced_at"] = utc_now()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "file": target.name,
        "manifest": manifest_path.name,
        "created_at": manifest["created_at"],
        "created_by": actor,
        "size": manifest["size"],
        "sha256": manifest["sha256"],
        "remote_synced": remote_synced,
    }


def safe_backup_file(backup_root: Path, file_name: str) -> Path:
    cleaned = safe_filename(file_name)
    if cleaned != file_name or not cleaned.endswith(".sqlite3"):
        raise ApiError(HTTPStatus.BAD_REQUEST, "invalid backup file")
    target = (backup_root / cleaned).resolve()
    if backup_root.resolve() not in target.parents or not target.exists():
        raise ApiError(HTTPStatus.NOT_FOUND, "backup not found")
    return target


def list_sqlite_backups(backup_root: Path) -> list[dict[str, Any]]:
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_manifest_status(backup_root, repair=True)
    items: list[dict[str, Any]] = []
    for backup in sorted(backup_root.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True):
        manifest_path = backup.with_suffix(".json")
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = {}
        items.append(
            {
                "file": backup.name,
                "manifest": manifest_path.name if manifest_path.exists() else "",
                "created_at": manifest.get("created_at") or datetime.fromtimestamp(backup.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "created_by": manifest.get("created_by") or "-",
                "size": backup.stat().st_size,
                "sha256": manifest.get("sha256") or "",
                "remote_synced_at": manifest.get("remote_synced_at") or "",
            }
        )
    return items


def verify_backup_manifest(backup_file: Path) -> None:
    manifest_path = backup_file.with_suffix(".json")
    if not manifest_path.exists():
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup manifest is invalid") from exc
    expected = str(manifest.get("sha256") or "").strip()
    if not expected:
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup manifest has no sha256")
    actual = sha256_file(backup_file)
    if not hmac.compare_digest(actual, expected):
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup sha256 mismatch")


def verify_backup_for_restore(backup_root: Path, file_name: str) -> dict[str, Any]:
    backup_file = safe_backup_file(backup_root, file_name)
    verify_backup_manifest(backup_file)
    integrity_ok, integrity_detail = sqlite_integrity_status(backup_file)
    if not integrity_ok:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"backup integrity failed: {integrity_detail}")
    with sqlite3.connect(backup_file) as backup_conn:
        row = backup_conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if not row:
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup has no app_state payload")
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup app_state payload is invalid") from exc
    manifest = json.loads(backup_file.with_suffix(".json").read_text(encoding="utf-8"))
    return {
        "file": backup_file.name,
        "verified_at": utc_now(),
        "integrity": integrity_detail,
        "sha256": str(manifest.get("sha256") or ""),
        "size": backup_file.stat().st_size,
        "created_at": manifest.get("created_at") or "",
        "created_by": manifest.get("created_by") or "-",
        "counts": {
            "objects": len(payload.get("objects", [])),
            "requests": len(payload.get("requests", [])),
            "tasks": len(payload.get("tasks", [])),
            "documents": len(payload.get("documents", payload.get("docs", []))),
            "audit": len(payload.get("audit", [])),
        },
    }


def state_counts(state: dict[str, Any]) -> dict[str, int]:
    return {
        "objects": len(state.get("objects", [])),
        "requests": len(state.get("requests", [])),
        "tasks": len(state.get("tasks", [])),
        "documents": len(state.get("documents", state.get("docs", []))),
        "audit": len(state.get("audit", [])),
    }


def payload_count_keys(payload: dict[str, Any]) -> set[str]:
    keys = {"objects", "requests", "tasks", "audit"} & set(payload)
    if "documents" in payload or "docs" in payload:
        keys.add("documents")
    return keys


def restore_drill_from_backup(backup_root: Path, file_name: str) -> dict[str, Any]:
    verified = verify_backup_for_restore(backup_root, file_name)
    backup_file = safe_backup_file(backup_root, file_name)
    with sqlite3.connect(backup_file) as backup_conn:
        row = backup_conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if not row:
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup has no app_state payload")
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup app_state payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup app_state payload is invalid")

    with tempfile.TemporaryDirectory(prefix="qurulush-api-restore-drill-") as tmp:
        temp_db = Path(tmp) / "restore-drill.sqlite3"
        init_db(temp_db)
        restored_state = public_state_payload()
        restored_state.update(payload)
        restored_state.pop("users", None)
        normalize_team_assignments(restored_state)
        normalize_money_records(restored_state)
        save_state(restored_state, temp_db)
        integrity_ok, restored_integrity = sqlite_integrity_status(temp_db)
        if not integrity_ok:
            raise ApiError(HTTPStatus.BAD_REQUEST, "restored temp database integrity failed: " + restored_integrity)
        loaded_state = load_state(temp_db)
        backup_counts = dict(verified["counts"])
        restored_counts = state_counts(loaded_state)
        comparable_keys = payload_count_keys(payload)
        mismatches = {
            key: {"backup": backup_counts.get(key), "restored": restored_counts.get(key)}
            for key in comparable_keys
            if backup_counts.get(key) != restored_counts.get(key)
        }
        if mismatches:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"restored counts mismatch: {mismatches}")
        migration_filled = {
            key: restored_counts[key]
            for key in restored_counts
            if key not in comparable_keys and restored_counts[key] != backup_counts.get(key)
        }

    return {
        "ok": True,
        "checked_at": utc_now(),
        "file": verified["file"],
        "sha256": verified["sha256"],
        "source_integrity": verified["integrity"],
        "restored_integrity": restored_integrity,
        "backup_counts": backup_counts,
        "restored_counts": restored_counts,
        "migration_filled": migration_filled,
        "temp_database_removed": True,
    }


def backup_manifest_status(backup_root: Path, repair: bool = False) -> tuple[str, str, dict[str, int]]:
    backup_root.mkdir(parents=True, exist_ok=True)
    stats = {"total": 0, "valid": 0, "repaired": 0, "invalid": 0}
    problems: list[str] = []
    for backup in sorted(backup_root.glob("*.sqlite3")):
        stats["total"] += 1
        manifest_path = backup.with_suffix(".json")
        if not manifest_path.exists():
            stats["invalid"] += 1
            problems.append(f"{backup.name}: нет manifest")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            stats["invalid"] += 1
            problems.append(f"{backup.name}: manifest не читается")
            continue
        expected = str(manifest.get("sha256") or "").strip()
        if not expected and repair:
            integrity_ok, _ = sqlite_integrity_status(backup)
            if integrity_ok:
                manifest["sha256"] = sha256_file(backup)
                manifest.setdefault("size", backup.stat().st_size)
                manifest.setdefault("backup", str(backup))
                manifest["checksum_added_at"] = utc_now()
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                expected = str(manifest["sha256"])
                stats["repaired"] += 1
        if not expected:
            stats["invalid"] += 1
            problems.append(f"{backup.name}: нет sha256")
            continue
        actual = sha256_file(backup)
        if not hmac.compare_digest(actual, expected):
            stats["invalid"] += 1
            problems.append(f"{backup.name}: sha256 не совпадает")
            continue
        integrity_ok, integrity_detail = sqlite_integrity_status(backup)
        if not integrity_ok:
            stats["invalid"] += 1
            problems.append(f"{backup.name}: {integrity_detail}")
            continue
        stats["valid"] += 1
    if stats["total"] == 0:
        return "warning", "Локальных резервных копий пока нет", stats
    if stats["invalid"]:
        detail = f"Некорректные бэкапы: {stats['invalid']} из {stats['total']}; " + "; ".join(problems[:5])
        return "fail", detail, stats
    detail = f"Проверено бэкапов: {stats['valid']} из {stats['total']}"
    if stats["repaired"]:
        detail += f"; checksum добавлен: {stats['repaired']}"
    return "pass", detail, stats


def backup_max_age_hours() -> float:
    raw = os.environ.get("QH_BACKUP_MAX_AGE_HOURS", "").strip()
    if not raw:
        return 24.0
    try:
        hours = float(raw.replace(",", "."))
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid backup max age hours") from exc
    if hours <= 0:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid backup max age hours")
    return hours


def backup_freshness_status(backup_root: Path) -> tuple[str, str, dict[str, Any]]:
    backup_root.mkdir(parents=True, exist_ok=True)
    backups = list(backup_root.glob("*.sqlite3"))
    max_age_hours = backup_max_age_hours()
    stats: dict[str, Any] = {
        "total": len(backups),
        "max_age_hours": max_age_hours,
        "newest_age_seconds": None,
    }
    if not backups:
        return "warning", "Локальных резервных копий пока нет", stats
    newest = max(backups, key=lambda path: path.stat().st_mtime)
    age_seconds = max(0, int(utc_ts() - newest.stat().st_mtime))
    stats["newest"] = newest.name
    stats["newest_age_seconds"] = age_seconds
    max_age_seconds = int(max_age_hours * 60 * 60)
    detail = f"Последний бэкап: {newest.name}, возраст {age_seconds} сек., лимит {max_age_hours:g} ч."
    if age_seconds > max_age_seconds:
        return "fail", detail, stats
    return "pass", detail, stats


def backup_remote_command() -> list[str] | None:
    raw = os.environ.get("QH_BACKUP_REMOTE_CMD", "").strip()
    if not raw:
        return None
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid remote backup command") from exc
    if not command:
        return None
    return command


def backup_remote_timeout_seconds() -> int:
    raw = os.environ.get("QH_BACKUP_REMOTE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return BACKUP_REMOTE_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid remote backup timeout") from exc
    if timeout <= 0:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid remote backup timeout")
    return timeout


def sync_backup_to_remote(backup_file: Path, manifest_file: Path) -> bool:
    command = backup_remote_command()
    if not command:
        return False
    remote_url = os.environ.get("QH_BACKUP_REMOTE_URL", "").strip()
    replacements = {
        "{backup}": str(backup_file),
        "{manifest}": str(manifest_file),
        "{remote_url}": remote_url,
    }
    prepared = replace_command_markers(command, replacements)
    if not any(part in command for part in ("{backup}", "{manifest}")):
        prepared.extend([str(backup_file), str(manifest_file)])
    try:
        result = subprocess.run(
            prepared,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=backup_remote_timeout_seconds(),
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "remote backup command is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "remote backup command timeout") from exc
    if result.returncode != 0:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "remote backup command failed")
    parse_hook_json_output(result.stdout or "", "backup_remote", {"ok", "synced", "uploaded", "stored"})
    return True


def backup_interval_seconds_from_env(strict: bool = False) -> int | None:
    raw = (
        os.environ.get("QH_BACKUP_INTERVAL_SECONDS", "").strip()
        or os.environ.get("QH_BACKUP_INTERVAL_MINUTES", "").strip()
        or os.environ.get("QH_BACKUP_SCHEDULE", "").strip()
    )
    if not raw:
        return None

    source = "seconds" if os.environ.get("QH_BACKUP_INTERVAL_SECONDS", "").strip() else "minutes"
    value = raw.lower()
    named = {"hourly": 60 * 60, "daily": 24 * 60 * 60}
    if value in named:
        return named[value]

    match = re.fullmatch(r"(\d+)([smhd]?)", value)
    if not match:
        if strict:
            raise ValueError("QH_BACKUP_SCHEDULE must be hourly, daily, or a duration such as 30m")
        return None
    amount = int(match.group(1))
    if amount <= 0:
        if strict:
            raise ValueError("backup interval must be greater than zero")
        return None
    unit = match.group(2)
    if unit == "s" or (not unit and source == "seconds"):
        return amount
    if unit == "h":
        return amount * 60 * 60
    if unit == "d":
        return amount * 24 * 60 * 60
    return amount * 60


class BackupScheduler:
    def __init__(self, db_path: Path, backup_root: Path, interval_seconds: int, quiet: bool = False) -> None:
        self.db_path = db_path
        self.backup_root = backup_root
        self.interval_seconds = interval_seconds
        self.quiet = quiet
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="qh-backup-scheduler", daemon=True)
        self.last_backup: dict[str, Any] | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)

    def create_backup(self) -> None:
        try:
            self.last_backup = create_sqlite_backup(self.db_path, self.backup_root, "Автобэкап")
            self.last_error = None
            if not self.quiet:
                print(f"Automatic backup created: {self.last_backup['file']}")
        except Exception as exc:  # pragma: no cover - surfaced through readiness/logs
            self.last_error = str(exc)
            if not self.quiet:
                print(f"Automatic backup failed: {exc}", file=sys.stderr)

    def _run(self) -> None:
        if env_truthy("QH_BACKUP_ON_START"):
            self.create_backup()
        while not self.stop_event.wait(self.interval_seconds):
            self.create_backup()


def restore_app_state_from_backup(db_path: Path, backup_root: Path, file_name: str, actor: str) -> dict[str, Any]:
    backup_file = safe_backup_file(backup_root, file_name)
    verify_backup_for_restore(backup_root, backup_file.name)
    safety = create_sqlite_backup(db_path, backup_root, f"{actor} перед восстановлением")
    with sqlite3.connect(backup_file) as backup_conn:
        row = backup_conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if not row:
        raise ApiError(HTTPStatus.BAD_REQUEST, "backup has no app_state payload")
    restored_state = public_state_payload()
    restored_state.update(json.loads(row[0]))
    restored_state.pop("users", None)
    normalize_team_assignments(restored_state)
    restored_state.setdefault("audit", []).insert(
        0,
        {
            "time": utc_now(),
            "actor": actor,
            "event": f"Восстановлено состояние из резервной копии {backup_file.name}",
            "object": None,
        },
    )
    restored_state.setdefault("notifications", []).insert(
        0,
        {
            "time": utc_now(),
            "from": "Система",
            "title": "Состояние восстановлено",
            "text": backup_file.name,
            "urgent": True,
            "read": False,
        },
    )
    save_state(restored_state, db_path)
    return {
        "restored_from": backup_file.name,
        "restored_at": utc_now(),
        "restored_by": actor,
        "safety_backup": safety["file"],
    }


def sanitized_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for doc in documents:
        item = deepcopy(doc)
        item.pop("stored_file", None)
        item.pop("file_url", None)
        if isinstance(item.get("versions"), list):
            item["versions"] = [
                {k: v for k, v in version.items() if k not in {"stored_file", "file_url"}}
                for version in item["versions"]
            ]
        clean.append(item)
    return clean


def exchange_export_payload(state: dict[str, Any], actor: str) -> dict[str, Any]:
    return {
        "format": "qurulush-company-exchange-v1",
        "exported_at": utc_now(),
        "exported_by": actor,
        "company": {
            "name": "ОсОО «Бишкек Курулуш Групп»",
            "country": "Кыргызская Республика",
            "system": "Qurulush Hub",
        },
        "objects": deepcopy(state.get("objects", [])),
        "requests": deepcopy(state.get("requests", [])),
        "documents": sanitized_documents(state.get("documents", state.get("docs", []))),
        "inspections": deepcopy(state.get("inspections", [])),
        "tasks": deepcopy(state.get("tasks", [])),
        "money": deepcopy(state.get("money", [])),
        "audit": deepcopy(state.get("audit", [])),
    }


def sacc2_sync_command() -> list[str] | None:
    raw = os.environ.get("QH_SACC2_SYNC_CMD", "").strip()
    if not raw:
        return None
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid sacc2 sync command") from exc
    if not command:
        return None
    return command


def sacc2_api_url() -> str:
    return os.environ.get("QH_SACC2_API_URL", "").strip() or os.environ.get("SACC2_API_URL", "").strip()


def sacc2_api_key_configured() -> bool:
    return env_present("QH_SACC2_API_KEY", "SACC2_API_KEY")


def sacc2_sync_timeout_seconds() -> int:
    raw = os.environ.get("QH_SACC2_SYNC_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return SACC2_SYNC_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid sacc2 sync timeout") from exc
    if timeout <= 0:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid sacc2 sync timeout")
    return timeout


def sacc2_public_status_timeout_seconds() -> int:
    raw = os.environ.get("QH_SACC2_STATUS_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return SACC2_STATUS_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid sacc2 status timeout") from exc
    if timeout <= 0 or timeout > 30:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "invalid sacc2 status timeout")
    return timeout


def sacc2_public_urls() -> list[str]:
    raw = os.environ.get("QH_SACC2_PUBLIC_URLS", "").strip()
    values = [item.strip() for item in raw.split(",") if item.strip()] if raw else list(DEFAULT_SACC2_PUBLIC_URLS)
    seen: set[str] = set()
    urls: list[str] = []
    for value in values:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}".rstrip("/") or value
        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls


def external_status_url_allowed(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "Разрешены только http/https URL"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False, "Не указан host"
    if host in {"localhost"} or host.endswith(".local"):
        return False, "Внутренние адреса запрещены"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True, "ok"
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return False, "Внутренние IP запрещены"
    return True, "ok"


def probe_external_url(url: str, timeout: int) -> dict[str, Any]:
    allowed, reason = external_status_url_allowed(url)
    if not allowed:
        return {"url": url, "status": "blocked", "status_code": None, "detail": reason}
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "QurulushHubStatus/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = int(getattr(response, "status", response.getcode()))
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        status = "external_error" if code >= 500 else "reachable_with_error"
        return {"url": url, "status": status, "status_code": code, "detail": f"HTTP {code}"}
    except urllib.error.URLError as exc:
        return {"url": url, "status": "unreachable", "status_code": None, "detail": str(exc.reason)}
    except TimeoutError:
        return {"url": url, "status": "timeout", "status_code": None, "detail": "timeout"}
    status = "online" if 200 <= code < 400 else ("external_error" if code >= 500 else "reachable_with_error")
    return {"url": url, "status": status, "status_code": code, "detail": f"HTTP {code}"}


def sacc2_public_status_payload(actor: str) -> dict[str, Any]:
    timeout = sacc2_public_status_timeout_seconds()
    targets = [probe_external_url(url, timeout) for url in sacc2_public_urls()]
    online = [item for item in targets if item.get("status") == "online"]
    external_errors = [item for item in targets if item.get("status") == "external_error"]
    if online:
        summary_status = "online"
        summary = "Есть доступный публичный контур sacc2/ДГАСК."
    elif external_errors:
        summary_status = "external_error"
        summary = "Публичный контур отвечает ошибкой сервера; зафиксируйте внешний инцидент и используйте ручной fallback."
    else:
        summary_status = "unreachable"
        summary = "Публичный контур недоступен с этой машины; проверьте интернет, VPN, DNS или доступы."
    return {
        "format": "qurulush-sacc2-public-status-v1",
        "checked_at": utc_now(),
        "checked_by": actor,
        "timeout_seconds": timeout,
        "summary_status": summary_status,
        "summary": summary,
        "targets": targets,
        "credentials_used": False,
        "next_step": "Если sacc2.avn.kg недоступен, приложите этот статус к request-pack и запросите у Минстроя/ДГАСК актуальный рабочий URL, регламент доступности и официальный API.",
    }


def attach_sacc2_public_status_to_launch(state: dict[str, Any], report: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    status_payload = sacc2_public_status_payload(user["name"])
    targets = status_payload.get("targets") or []
    primary = targets[0] if targets else {}
    primary_status = str(primary.get("status") or status_payload.get("summary_status") or "")
    tracker_status = "answered" if primary_status == "online" else "blocked"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target_summary = "; ".join(
        f"{item.get('url', '-')}: {item.get('status', '-')} {item.get('detail', '-')}"
        for item in targets
        if isinstance(item, dict)
    )
    evidence = clean_evidence_text(
        f"Публичная проверка sacc2 от {status_payload.get('checked_at', utc_now())}: "
        f"{target_summary}. Пароли использованы: нет. {status_payload.get('next_step', '')}",
        700,
    )
    tracker_payload = {
        "id": "sacc2_api",
        "status": tracker_status,
        "outgoing_no": f"SACC2-STATUS-{stamp}",
        "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "response_at": status_payload.get("checked_at", ""),
        "contact": "Публичный мониторинг sacc2 / Минстрой КР / ДГАСК",
        "responsible": "Генеральный директор / IT-интегратор",
        "note": evidence,
        "evidence": evidence,
    }
    updated = update_production_request_tracker(state, tracker_payload, report, user)
    return {
        "format": "qurulush-sacc2-public-status-attachment-v1",
        "attached_gate": "sacc2_api",
        "tracker_status": tracker_status,
        "tracker_label": PRODUCTION_REQUEST_TRACKER_STATUSES[tracker_status],
        "status": status_payload,
        "evidence": evidence,
        **updated,
    }


def sync_state_with_sacc2(state: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    command = sacc2_sync_command()
    if not command:
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "sacc2 sync command is not configured")
    api_url = sacc2_api_url()
    if not api_url or not sacc2_api_key_configured():
        raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "sacc2 API URL and key are required")

    payload = exchange_export_payload(state, user["name"])
    payload.update({"target": "sacc2", "api_url": api_url, "submitted_at": utc_now()})
    payload_file = None
    try:
        with tempfile.NamedTemporaryFile(prefix="qh-sacc2-", suffix=".json", mode="w", encoding="utf-8", delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            payload_file = tmp.name

        replacements = {"{payload}": payload_file, "{api_url}": api_url}
        prepared = replace_command_markers(command, replacements)
        if "{payload}" not in command:
            prepared.append(payload_file)
        try:
            result = subprocess.run(
                prepared,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=sacc2_sync_timeout_seconds(),
                check=False,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "sacc2 sync command is not available") from exc
        except subprocess.TimeoutExpired as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "sacc2 sync command timeout") from exc
        if result.returncode != 0:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "sacc2 sync command failed")
        hook_info = parse_hook_json_output(result.stdout or "", "sacc2", {"ok", "synced"})
    finally:
        if payload_file:
            try:
                Path(payload_file).unlink()
            except FileNotFoundError:
                pass

    return {
        "status": "synced",
        "synced_at": utc_now(),
        "synced_by": user["name"],
        "api_url": api_url,
        "requests": len(state.get("requests", [])),
        "documents": len(state.get("documents", state.get("docs", []))),
        **hook_info,
    }


def audit_export_payload(state: dict[str, Any], actor: str) -> dict[str, Any]:
    return {
        "format": "qurulush-audit-export-v1",
        "exported_at": utc_now(),
        "exported_by": actor,
        "company": {
            "name": "ОсОО «Бишкек Курулуш Групп»",
            "country": "Кыргызская Республика",
            "system": "Qurulush Hub",
        },
        "audit": deepcopy(state.get("audit", [])),
    }


def reference_export_payload(state: dict[str, Any], actor: str) -> dict[str, Any]:
    reference = deepcopy(state.get("reference", SEED["reference"]))
    return {
        "format": "qurulush-reference-catalog-v1",
        "exported_at": utc_now(),
        "exported_by": actor,
        "source_note": REFERENCE_SOURCE_NOTE,
        "categories": sorted({str(item.get("category", "")) for item in reference if item.get("category")}),
        "reference": reference,
    }


def legal_verification_packet_payload(state: dict[str, Any], actor: str) -> dict[str, Any]:
    reference = deepcopy(state.get("reference", SEED["reference"]))
    categories = sorted({str(item.get("category", "")) for item in reference if item.get("category")})
    counts = {category: sum(1 for item in reference if item.get("category") == category) for category in categories}
    source_by_id = {str(item["id"]): item for item in LEGAL_OFFICIAL_SOURCES}
    items: list[dict[str, Any]] = []
    for item in reference:
        source_ids = LEGAL_SOURCE_BY_CATEGORY.get(str(item.get("category") or ""), [])
        source_candidates = [deepcopy(source_by_id[source_id]) for source_id in source_ids if source_id in source_by_id]
        items.append(
            {
                **item,
                "verification_status": "needs_review",
                "source_candidate_count": len(source_candidates),
                "source_candidates": source_candidates,
                "legal_source": "",
                "legal_source_url": "",
                "legal_basis_article": "",
                "tariff_or_penalty_confirmed": False,
                "verified_by": "",
                "verified_at": "",
                "remarks": "",
            }
        )
    return {
        "format": "qurulush-legal-verification-packet-v1",
        "exported_at": utc_now(),
        "exported_by": actor,
        "source_note": REFERENCE_SOURCE_NOTE,
        "purpose": (
            "Пакет предназначен для юридической сверки разрешительных документов, госпошлин, видов штрафов, "
            "уведомлений, запросов и проверок перед боевым запуском платформы строительной компании."
        ),
        "verification_scope": [
            "Действующие НПА Кыргызской Республики",
            "Регламенты ДГАСК и Министерства строительства Кыргызской Республики",
            "Актуальные формы заявлений, уведомлений и ответов",
            "Суммы госпошлин, договорных услуг, штрафов и сроки оплаты",
            "Ответственные роли компании и порядок взаимодействия с инспектором",
        ],
        "official_sources_checked_at": "2026-09-14",
        "official_sources": deepcopy(LEGAL_OFFICIAL_SOURCES),
        "source_registry_note": (
            "Источники добавлены как стартовый реестр юридической сверки. Суммы госпошлин, штрафов, формы и сроки остаются "
            "в статусе needs_review до подтверждения юристом по действующей редакции НПА и приложениям к документам."
        ),
        "categories": categories,
        "counts": counts,
        "items": items,
}


LEGAL_OFFICIAL_SOURCES = [
    {
        "id": "minstroy_order_93_2025",
        "title": "Приказ Минстроя от 2 июля 2025 года №93-нпа о порядке выдачи документов на строительство и подключения к инженерным сетям",
        "authority": "Министерство строительства, архитектуры и ЖКХ Кыргызской Республики",
        "url": "https://minstroy.gov.kg/ru/document/173/show",
        "published_at": "03.07.2025",
        "status": "official_source_candidate",
        "covers": ["Разрешительные документы", "Проверки", "Запросы и уведомления", "sacc2 / ДГАСК"],
        "verification_use": "Проверить перечень процедур, статусы, уровни сложности, единое окно, подключение к инженерным сетям и приемку объектов.",
    },
    {
        "id": "minstroy_news_623_2025",
        "title": "Сообщение Минстроя: новые правила в сфере строительства и подключения к инженерным сетям вступают в силу с 1 августа 2025 года",
        "authority": "Министерство строительства, архитектуры и ЖКХ Кыргызской Республики",
        "url": "https://minstroy.gov.kg/ru/news/623/show",
        "published_at": "03.07.2025",
        "status": "official_context",
        "covers": ["Разрешительные документы", "Сроки", "Подключение к инженерным сетям"],
        "verification_use": "Использовать как контекст реформы; финальные формулировки брать из НПА и скачанного приложения.",
    },
    {
        "id": "town_planning_law_1994",
        "title": "Закон КР от 11 января 1994 года №1372-XII «О градостроительстве и архитектуре Кыргызской Республики»",
        "authority": "ЦБД правовой информации Минюста Кыргызской Республики",
        "url": "https://cbd.minjust.gov.kg/716/edition/1033306/ru",
        "published_at": "11.01.1994",
        "edition": "06.01.2021",
        "status": "legal_primary_source",
        "covers": ["Разрешительные документы", "Штрафы и нарушения", "Проверки"],
        "verification_use": "Проверить правовую основу разрешений, обязанностей участников строительства и оснований контроля.",
    },
    {
        "id": "offenses_code_2021",
        "title": "Кодекс Кыргызской Республики о правонарушениях от 28 октября 2021 года №128",
        "authority": "ЦБД правовой информации Минюста Кыргызской Республики",
        "url": "https://cbd.minjust.gov.kg/3-36/edition/2102/ru",
        "published_at": "28.10.2021",
        "edition": "06.08.2026",
        "status": "legal_primary_source",
        "covers": ["Штрафы и нарушения", "Сроки оплаты", "Ответственность"],
        "verification_use": "Проверить виды правонарушений, размеры штрафов, сроки и процесс обжалования перед внесением сумм в справочник.",
    },
    {
        "id": "minstroy_license_fee_service",
        "title": "Услуга Минстроя: платеж за лицензию на строительную деятельность",
        "authority": "Министерство строительства, архитектуры и ЖКХ Кыргызской Республики",
        "url": "https://minstroy.gov.kg/ru/kyzmat/28/show",
        "status": "official_service_fee_source",
        "covers": ["Госпошлины и начисления", "Лицензирование"],
        "verification_use": "Проверить код платежа, реквизиты, расчетный показатель и уровни ответственности до ввода тарифов.",
    },
    {
        "id": "minstroy_department_urban_development",
        "title": "Управление градостроительства, архитектуры и регионального развития Минстроя",
        "authority": "Министерство строительства, архитектуры и ЖКХ Кыргызской Республики",
        "url": "https://minstroy.gov.kg/ru/department/41/show",
        "status": "official_department_source",
        "covers": ["Запросы и уведомления", "Роли ведомства", "Разрешительные документы"],
        "verification_use": "Проверить ответственных подразделений по разрешительной системе, территориальным органам и материалам по объектам повышенного риска.",
    },
    {
        "id": "expired_urban_fine_instruction_2005",
        "title": "Инструкция о порядке наложения и взыскания административных штрафов за правонарушения в градостроительной деятельности",
        "authority": "ЦБД правовой информации Минюста Кыргызской Республики",
        "url": "https://cbd.minjust.gov.kg/22-77/edition/461367/ru",
        "published_at": "18.01.2005",
        "status": "expired_do_not_use_as_current_law",
        "covers": ["Штрафы и нарушения"],
        "verification_use": "Не использовать как действующее основание: источник нужен только как контроль, чтобы юрист не перенес устаревшие правила в платформу.",
    },
]


LEGAL_SOURCE_BY_CATEGORY = {
    "Разрешительные документы": ["minstroy_order_93_2025", "town_planning_law_1994", "minstroy_news_623_2025", "minstroy_department_urban_development"],
    "Госпошлины и начисления": ["minstroy_license_fee_service", "minstroy_order_93_2025"],
    "Штрафы и нарушения": ["offenses_code_2021", "town_planning_law_1994", "expired_urban_fine_instruction_2005"],
    "Запросы и уведомления": ["minstroy_order_93_2025", "minstroy_department_urban_development", "minstroy_news_623_2025"],
    "Проверки": ["town_planning_law_1994", "minstroy_order_93_2025", "minstroy_department_urban_development"],
    "Роли и доступы": ["minstroy_department_urban_development", "minstroy_order_93_2025"],
}


def interaction_map_payload(state: dict[str, Any], actor: str) -> dict[str, Any]:
    requests = state.get("requests", []) if isinstance(state.get("requests"), list) else []
    notifications = state.get("notifications", []) if isinstance(state.get("notifications"), list) else []
    inspections = state.get("inspections", []) if isinstance(state.get("inspections"), list) else []
    docs = state.get("documents", state.get("docs", []))
    documents = docs if isinstance(docs, list) else []
    money = state.get("money", []) if isinstance(state.get("money"), list) else []
    fines = [item for item in money if isinstance(item, dict) and "штраф" in str(item.get("title", "")).lower()]
    unpaid_money = [item for item in money if isinstance(item, dict) and str(item.get("status", "")).lower() != "оплачено"]
    open_requests = [item for item in requests if isinstance(item, dict) and str(item.get("status", "")) not in {"done", "closed"}]
    urgent_notifications = [item for item in notifications if isinstance(item, dict) and item.get("urgent")]

    workflows: list[dict[str, Any]] = []
    for workflow in INTERACTION_WORKFLOWS:
        item = deepcopy(workflow)
        item["company_roles"] = list(workflow.get("company_roles", []))
        item["status_flow"] = list(workflow.get("status_flow", []))
        item["current_related_count"] = {
            "incoming_request": len(open_requests),
            "official_notification": len(notifications),
            "inspection_preparation": len(inspections),
            "permit_document": len(documents),
            "state_fee_payment": len(unpaid_money),
            "fine_or_violation": len(fines),
            "production_exchange": len(open_requests) + len(documents),
        }.get(str(workflow.get("id")), 0)
        workflows.append(item)

    return {
        "format": "qurulush-dgask-interaction-map-v1",
        "exported_at": utc_now(),
        "exported_by": actor,
        "source_note": REFERENCE_SOURCE_NOTE,
        "purpose": "Операционная карта взаимодействия строительной компании с инспектором, региональным отделом, Министерством строительства / ДГАСК и sacc2.",
        "counts": {
            "open_requests": len(open_requests),
            "notifications": len(notifications),
            "urgent_notifications": len(urgent_notifications),
            "inspections": len(inspections),
            "documents": len(documents),
            "money_items": len(money),
            "unpaid_money_items": len(unpaid_money),
            "fines": len(fines),
        },
        "workflows": workflows,
    }


def w_text(value: Any) -> str:
    return xml_escape(str(value if value is not None else ""), {'"': "&quot;"})


def w_run(text: Any, bold: bool = False, size: int = 22, color: str | None = None) -> str:
    bold_xml = "<w:b/>" if bold else ""
    color_xml = f'<w:color w:val="{color}"/>' if color else ""
    props = f'<w:rPr>{bold_xml}{color_xml}<w:sz w:val="{size}"/></w:rPr>'
    lines = str(text if text is not None else "").splitlines() or [""]
    parts: list[str] = []
    for index, line in enumerate(lines):
        if index:
            parts.append("<w:br/>")
        parts.append(f"<w:t xml:space=\"preserve\">{w_text(line)}</w:t>")
    return f"<w:r>{props}{''.join(parts)}</w:r>"


def w_paragraph(text: Any = "", style: str | None = None, bold: bool = False, size: int = 22, color: str | None = None, page_break_before: bool = False) -> str:
    props: list[str] = []
    if style:
        props.append(f"<w:pStyle w:val=\"{style}\"/>")
    if page_break_before:
        props.append("<w:pageBreakBefore/>")
    ppr = f"<w:pPr>{''.join(props)}</w:pPr>" if props else ""
    return f"<w:p>{ppr}{w_run(text, bold, size, color)}</w:p>"


def w_page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def w_cell(*paragraphs: str, width: int = 2400, fill: str | None = None) -> str:
    shading = f"<w:shd w:fill=\"{fill}\"/>" if fill else ""
    p_xml = "".join(paragraphs) or w_paragraph("")
    return (
        "<w:tc>"
        f"<w:tcPr><w:tcW w:w=\"{width}\" w:type=\"dxa\"/>{shading}"
        "<w:tcMar><w:top w:w=\"100\" w:type=\"dxa\"/><w:left w:w=\"100\" w:type=\"dxa\"/><w:bottom w:w=\"100\" w:type=\"dxa\"/><w:right w:w=\"100\" w:type=\"dxa\"/></w:tcMar>"
        "</w:tcPr>"
        f"{p_xml}</w:tc>"
    )


def w_table(rows: list[list[str]], widths: list[int] | None = None, header_size: int = 18, body_size: int = 19) -> str:
    borders = (
        "<w:tblBorders>"
        "<w:top w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"D9D9D9\"/>"
        "<w:left w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"D9D9D9\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"D9D9D9\"/>"
        "<w:right w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"D9D9D9\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"D9D9D9\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"D9D9D9\"/>"
        "</w:tblBorders>"
    )
    table_rows: list[str] = []
    column_widths = widths or [1900, 2600, 4300]
    for index, row in enumerate(rows):
        fill = "1F2937" if index == 0 else ("F8FAFC" if index % 2 == 0 else None)
        cells = []
        for col_index, value in enumerate(row):
            width = column_widths[col_index] if col_index < len(column_widths) else column_widths[-1]
            cells.append(w_cell(w_paragraph(value, bold=index == 0, size=header_size if index == 0 else body_size, color="FFFFFF" if index == 0 else None), width=width, fill=fill))
        table_rows.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return f"<w:tbl><w:tblPr><w:tblW w:w=\"0\" w:type=\"auto\"/>{borders}<w:tblLook w:firstRow=\"1\" w:noHBand=\"0\" w:noVBand=\"1\"/></w:tblPr>{''.join(table_rows)}</w:tbl>"


def build_access_matrix_docx(matrix: dict[str, Any]) -> bytes:
    roles = matrix.get("roles") if isinstance(matrix.get("roles"), list) else []
    actions = matrix.get("actions") if isinstance(matrix.get("actions"), list) else []
    summary_rows = [["Роль", "Сотрудники", "Объекты", "Ответственность", "Ограничения"]]
    for role in [entry for entry in roles if isinstance(entry, dict)]:
        members = role.get("members") if isinstance(role.get("members"), list) else []
        member_text = "\n".join(f"{item.get('name', '-')}\n{item.get('email', '-')}" for item in members if isinstance(item, dict)) or "Не назначено"
        summary_rows.append(
            [
                str(role.get("title") or role.get("id") or "-"),
                member_text,
                str(role.get("object_scope") or "-"),
                str(role.get("responsibility") or "-"),
                str(role.get("restricted") or "-"),
            ]
        )

    action_rows = [["Роль"] + [str(action.get("title") or action.get("id") or "-") for action in actions if isinstance(action, dict)]]
    for role in [entry for entry in roles if isinstance(entry, dict)]:
        by_action = {str(item.get("id")): bool(item.get("allowed")) for item in role.get("actions", []) if isinstance(item, dict)}
        action_rows.append(
            [str(role.get("title") or role.get("id") or "-")]
            + ["Да" if by_action.get(str(action.get("id"))) else "Нет" for action in actions if isinstance(action, dict)]
        )

    body: list[str] = [
        w_paragraph("Матрица доступа строительной компании", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub роли права объекты и ответственность", "Subtitle", size=22),
        w_paragraph(f"Дата выгрузки: {matrix.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {matrix.get('reported_by', '-')}", size=20),
        w_paragraph("Назначение", "Heading1", bold=True, size=26),
        w_paragraph(
            "Документ фиксирует рабочую модель доступа для генерального директора, главного инженера, прораба, бригадира, бухгалтера и юриста. Матрица помогает выдать роли без лишних прав и проверить, кто отвечает за документы, запросы, проверки, платежи и юридическую работу.",
            size=21,
        ),
        w_paragraph("Сводка ролей", "Heading1", bold=True, size=26),
        w_table(summary_rows, widths=[1800, 2100, 1700, 3500, 3100], header_size=15, body_size=15),
        w_paragraph("Права по действиям", "Heading1", bold=True, size=26),
        w_table(action_rows, widths=[1900, 1100, 1300, 1300, 1200, 1100, 1200, 1300, 1100, 1300], header_size=14, body_size=14),
        w_paragraph("Контроль", "Heading1", bold=True, size=26),
        w_paragraph(
            "Перед production запуском директор должен подтвердить реальные корпоративные email, назначенные объекты и отключение demo-пользователей. Матрица не содержит паролей, токенов и runtime-идентификаторов сессий.",
            size=21,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="20"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_account_cutover_docx(payload: dict[str, Any]) -> bytes:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    role_rows = [["Роль", "Статус", "Реальные", "Demo активные", "Demo отключенные"]]
    for role in payload.get("role_coverage", []):
        if not isinstance(role, dict):
            continue
        role_rows.append(
            [
                str(role.get("title") or role.get("id") or "-"),
                str(role.get("status") or "-"),
                str(role.get("real_active_count") or 0),
                str(role.get("demo_active_count") or 0),
                str(role.get("inactive_demo_count") or 0),
            ]
        )
    user_rows = [["Email", "ФИО", "Роль", "Тип", "Активен", "Объекты"]]
    for user in payload.get("users", []):
        if not isinstance(user, dict):
            continue
        user_rows.append(
            [
                str(user.get("email") or "-"),
                str(user.get("name") or "-"),
                str(user.get("role_title") or user.get("role") or "-"),
                str(user.get("account_type") or "-"),
                "Да" if user.get("active") else "Нет",
                str(user.get("object_scope") or "-"),
            ]
        )
    blocker_rows = [["Блокер", "Описание"]]
    for blocker in payload.get("blockers", []):
        if isinstance(blocker, dict):
            blocker_rows.append([str(blocker.get("title") or blocker.get("id") or "-"), str(blocker.get("detail") or "-")])
    if len(blocker_rows) == 1:
        blocker_rows.append(["OK", "Блокеров учетных записей нет"])
    step_rows = [["Шаг", "Действие"]]
    for index, step in enumerate(payload.get("next_steps", []), start=1):
        step_rows.append([str(index), str(step)])

    body: list[str] = [
        w_paragraph("Переход на боевые учетные записи", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub production account cutover", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {payload.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Проверил: {payload.get('reported_by', '-')}", size=20),
        w_paragraph("Сводка", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Production cutover: {'готов' if payload.get('ready_for_account_cutover') else 'не готов'}. "
            f"Активные реальные: {counts.get('active_real', 0)}. "
            f"Активные demo: {counts.get('active_demo', 0)}. "
            f"Закрыто ролей: {counts.get('roles_ready', 0)} из {counts.get('required_roles', 0)}.",
            size=21,
        ),
        w_paragraph("Покрытие ролей", "Heading1", bold=True, size=26),
        w_table(role_rows, widths=[2600, 1800, 1300, 1500, 1700], header_size=15, body_size=15),
        w_paragraph("Безопасный список пользователей", "Heading1", bold=True, size=26),
        w_table(user_rows, widths=[2600, 2400, 2100, 1300, 1100, 2600], header_size=14, body_size=14),
        w_paragraph("Блокеры", "Heading1", bold=True, size=26),
        w_table(blocker_rows, widths=[2800, 7600], header_size=15, body_size=15),
        w_paragraph("Порядок закрытия", "Heading1", bold=True, size=26),
        w_table(step_rows, widths=[900, 9500], header_size=15, body_size=15),
        w_paragraph(
            "Отчет не содержит паролей, внутренних хешей, session-token идентификаторов, API-ключей и runtime-файлов. Он предназначен для директора, DevOps и ответственного за доступы перед production restart.",
            size=20,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="20"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_sacc2_public_status_docx(payload: dict[str, Any]) -> bytes:
    targets = payload.get("targets") if isinstance(payload.get("targets"), list) else []
    rows = [["URL", "Статус", "Код", "Деталь"]]
    for item in [entry for entry in targets if isinstance(entry, dict)]:
        rows.append(
            [
                str(item.get("url") or "-"),
                str(item.get("status") or "-"),
                str(item.get("status_code") if item.get("status_code") is not None else "-"),
                str(item.get("detail") or "-"),
            ]
        )
    body: list[str] = [
        w_paragraph("Статус публичного контура sacc2", "Title", bold=True, size=32),
        w_paragraph("Проверка доступности без использования учетных данных", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {payload.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Проверил: {payload.get('checked_by', '-')}", size=20),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(f"Статус: {payload.get('summary_status', '-')}. {payload.get('summary', '-')}", size=21),
        w_paragraph("Проверенные адреса", "Heading1", bold=True, size=26),
        w_table(rows, widths=[4200, 2200, 1300, 5200], header_size=17, body_size=18),
        w_paragraph("Контроль безопасности", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Учетные данные использованы: {'да' if payload.get('credentials_used') else 'нет'}. "
            f"Timeout: {payload.get('timeout_seconds', 0)} сек. Private, localhost и внутренние IP адреса блокируются.",
            size=21,
        ),
        w_paragraph("Следующий шаг", "Heading1", bold=True, size=26),
        w_paragraph(payload.get("next_step") or "-", size=21),
        w_paragraph("Как использовать", "Heading1", bold=True, size=26),
        w_paragraph(
            "Если основной адрес sacc2 отвечает ошибкой или недоступен, приложите этот документ к письму в Минстрой или ДГАСК. "
            "В письме попросите подтвердить актуальный рабочий URL, режим входа для строительной компании, официальный API, карту статусов и ответственного контактного лица.",
            size=21,
        ),
        w_paragraph("Чек-лист реакции", "Heading1", bold=True, size=26),
        w_table(
            [
                ["Шаг", "Действие", "Доказательство"],
                ["1", "Зафиксировать текущий статус публичных адресов", "Этот Word-файл и JSON из платформы"],
                ["2", "Проверить, доступен ли fallback адрес для ручной работы", "Скриншот входа или HTTP 200"],
                ["3", "Направить официальный запрос по sacc2", "Исходящий номер и дата отправки"],
                ["4", "Получить API URL, карту статусов и контакт поддержки", "Ответ Минстроя / ДГАСК"],
                ["5", "Повторить production smoke и go/no-go", "JSON ok=true без failed_stages"],
            ],
            widths=[900, 4700, 4700],
            header_size=17,
            body_size=18,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    exported = document_xml.lower()
    if "demo2026" in exported or "token_hash" in exported or "api_key" in exported:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "sacc2 status document contains unsafe data")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_remaining_work_docx(payload: dict[str, Any]) -> bytes:
    steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    current = payload.get("current_step") if isinstance(payload.get("current_step"), dict) else None
    rows = [["№", "Этап", "Шаг", "Ответственный", "Что сделать", "Доказательство"]]
    for step in [item for item in steps if isinstance(item, dict)]:
        rows.append(
            [
                str(step.get("step_no") or "-"),
                str(step.get("phase_title") or "-"),
                str(step.get("title") or step.get("id") or "-"),
                str(step.get("owner") or "-"),
                str(step.get("next_action") or "-"),
                str(step.get("evidence_needed") or "-"),
            ]
        )
    if len(rows) == 1:
        rows.append(["-", "Все этапы", "Production blockers закрыты", "-", "Запустить финальную приемку и сохранить решение директора.", "go/no-go ok=true без failed_stages."])

    body: list[str] = [
        w_paragraph("Что осталось до боевого запуска платформы", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub production blockers шаги ответственные и доказательства", "Subtitle", size=22),
        w_paragraph(f"Дата выгрузки: {payload.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {payload.get('reported_by', '-')}", size=20),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Production готовность: {payload.get('completion_percent', 0)}%. Закрыто {payload.get('required_ready_count', 0)} из {payload.get('required_total', 0)} обязательных пунктов. Осталось шагов: {payload.get('remaining_count', 0)}.",
            size=21,
        ),
    ]
    if current:
        body.append(w_paragraph("Ближайший шаг", "Heading1", bold=True, size=26))
        body.append(
            w_paragraph(
                f"{current.get('title', '-')}. Ответственный: {current.get('owner', '-')}. Действие: {current.get('next_action', '-')}",
                size=21,
            )
        )
    body.extend(
        [
            w_paragraph("Пошаговый остаток", "Heading1", bold=True, size=26),
            w_table(rows, widths=[650, 2100, 2500, 2100, 4000, 3900], header_size=14, body_size=14),
            w_paragraph("Контроль приемки", "Heading1", bold=True, size=26),
            w_paragraph(
                "После закрытия всех пунктов нужно повторить production smoke и go/no-go. Финальная приемка принимается только по отчету ok=true без failed_stages и с приложенными доказательствами по внешним интеграциям.",
                size=21,
            ),
        ]
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="20"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_top_actions_docx(payload: dict[str, Any]) -> bytes:
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    rows = [["№", "Срочность", "Срок", "Ответственный", "Шаг", "Действие"]]
    for action in [item for item in actions if isinstance(item, dict)]:
        rows.append(
            [
                str(action.get("step_no") or "-"),
                str(action.get("urgency_label") or action.get("urgency") or "-"),
                str(action.get("deadline") or "-"),
                str(action.get("owner") or "-"),
                str(action.get("title") or action.get("id") or "-"),
                str(action.get("next_action") or "-"),
            ]
        )
    if len(rows) == 1:
        rows.append(["-", "Готово", "-", "-", "Открытых срочных действий нет", "Production blockers закрыты или дедлайны не назначены."])
    urgency_summary = ", ".join(f"{PRODUCTION_REMAINING_URGENCY_LABELS.get(str(key), str(key))}: {value}" for key, value in (payload.get("by_urgency") or {}).items()) or "Нет данных по срочности"
    body: list[str] = [
        w_paragraph("Ближайшие действия запуска", "Title", bold=True, size=32),
        w_paragraph("Короткий список приоритетов для директора и исполнителей", "Subtitle", size=22),
        w_paragraph(f"Дата выгрузки: {payload.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {payload.get('reported_by', '-')}", size=20),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Production готовность: {payload.get('completion_percent', 0)}%. Осталось шагов: {payload.get('remaining_count', 0)}. В этом списке: {payload.get('action_count', 0)}.",
            size=21,
        ),
        w_paragraph(f"Срочность: {urgency_summary}", size=21),
        w_paragraph("Приоритеты", "Heading1", bold=True, size=26),
        w_table(rows, widths=[650, 1700, 1400, 2300, 3100, 5200], header_size=14, body_size=14),
        w_paragraph("Как использовать", "Heading1", bold=True, size=26),
        w_paragraph(
            "Этот короткий список можно отправить ответственным вместо полного launch bundle. После выполнения действия нужно приложить доказательство в evidence-регистр и повторить go/no-go.",
            size=21,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="20"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    exported = document_xml.lower()
    if "demo2026" in exported or "token_hash" in exported or "official-sacc2-key-2026" in exported:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "top actions document contains unsafe data")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_qa_evidence_docx(payload: dict[str, Any]) -> bytes:
    live_rows = [["Проверка", "Статус", "Доказательство"]]
    for item in [entry for entry in payload.get("live_evidence", []) if isinstance(entry, dict)]:
        live_rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("status") or "-"),
                str(item.get("detail") or "-"),
            ]
        )
    check_rows = [["Тест", "Статус", "Команда / доказательство"]]
    for item in [entry for entry in payload.get("automated_checks", []) if isinstance(entry, dict)]:
        check_rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("status") or "-"),
                f"{item.get('command', '-')}\n{item.get('evidence', '-')}",
            ]
        )
    artifact_rows = [["Артефакт", "Тип", "Путь"]]
    for item in [entry for entry in payload.get("artifacts", []) if isinstance(entry, dict)]:
        artifact_rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("type") or "-"),
                str(item.get("path") or "-"),
            ]
        )
    body: list[str] = [
        w_paragraph("QA evidence пакет", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Проверено: {payload.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Сформировал: {payload.get('reported_by', '-')}", size=20),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Рабочая ссылка: {payload.get('working_link', '-')}. "
            f"Локальная готовность: {payload.get('local_ready')}. "
            f"Локальная приемка: {payload.get('local_acceptance')}. "
            f"Production готовность: {payload.get('production_ready')}. "
            f"Осталось шагов: {payload.get('remaining_count', 0)}.",
            size=21,
        ),
        w_paragraph(f"Следующий шаг: {payload.get('next_step', '-')}", size=21),
        w_paragraph("Live evidence", "Heading1", bold=True, size=26),
        w_table(live_rows, widths=[2600, 1500, 5400], body_size=18),
        w_paragraph("Команды проверки", "Heading1", bold=True, size=26),
        w_table(check_rows, widths=[2300, 1600, 5600], body_size=16),
        w_paragraph("Артефакты", "Heading1", bold=True, size=26),
        w_table(artifact_rows, widths=[2600, 1400, 5500], body_size=17),
        w_paragraph("Контроль безопасности", "Heading1", bold=True, size=26),
        w_paragraph(
            "Пакет не содержит паролей, API-ключей, session token, token hash и внутренних имен загруженных файлов. Для production-приемки команды нужно повторить на боевом домене с --require-production.",
            size=21,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="20"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    exported = document_xml.lower()
    if "demo2026" in exported or "token_hash" in exported or "bearer" in exported or "official-sacc2-key-2026" in exported:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "qa evidence document contains unsafe data")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_status_board_docx(payload: dict[str, Any]) -> bytes:
    summary_rows = [["Показатель", "Значение", "Статус"]]
    for card in [item for item in payload.get("summary_cards", []) if isinstance(item, dict)]:
        summary_rows.append(
            [
                str(card.get("title") or card.get("id") or "-"),
                str(card.get("value") or "-"),
                str(card.get("status") or "-"),
            ]
        )
    if len(summary_rows) == 1:
        summary_rows.append(["Статус", "Нет данных", "warning"])

    action_rows = [["№", "Шаг", "Ответственный", "Действие", "Доказательство"]]
    for item in [entry for entry in payload.get("top_actions", []) if isinstance(entry, dict)]:
        action_rows.append(
            [
                str(item.get("step_no") or "-"),
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("owner") or "-"),
                str(item.get("next_action") or "-"),
                str(item.get("evidence_needed") or "-"),
            ]
        )
    if len(action_rows) == 1:
        action_rows.append(["-", "Срочных действий нет", "-", "Закрыть открытые шаги по порядку.", "go/no-go ok=true без failed_stages."])

    step_rows = [["№", "Этап", "Шаг", "Статус", "Ответственный", "Что приложить"]]
    for item in [entry for entry in payload.get("steps", []) if isinstance(entry, dict)]:
        step_rows.append(
            [
                str(item.get("step_no") or "-"),
                str(item.get("phase_title") or "-"),
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("status_label") or item.get("status") or "-"),
                str(item.get("owner") or "-"),
                str(item.get("evidence_needed") or "-"),
            ]
        )
    if len(step_rows) == 1:
        step_rows.append(["-", "Все этапы", "Production blockers закрыты", "Готово", "-", "Финальный go/no-go отчет."])

    qa_rows = [["Проверка", "Статус", "Команда"]]
    for item in [entry for entry in payload.get("qa_checks", []) if isinstance(entry, dict)]:
        qa_rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("status") or "-"),
                str(item.get("command") or "-"),
            ]
        )
    if len(qa_rows) == 1:
        qa_rows.append(["QA", "pass", "См. QA evidence пакет."])

    artifact_rows = [["Артефакт", "Тип", "Путь"]]
    for item in [entry for entry in payload.get("artifacts", []) if isinstance(entry, dict)]:
        artifact_rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("type") or "-"),
                str(item.get("path") or "-"),
            ]
        )
    if len(artifact_rows) == 1:
        artifact_rows.append(["Рабочая ссылка", "url", str(payload.get("working_link") or "-")])

    current = payload.get("current_step") if isinstance(payload.get("current_step"), dict) else {}
    body: list[str] = [
        w_paragraph("Статус запуска платформы", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Проверено: {payload.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Сформировал: {payload.get('reported_by', '-')}", size=20),
        w_paragraph("Итог для директора", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Рабочая ссылка: {payload.get('working_link', '-')}. "
            f"Локальная готовность: {payload.get('local_ready')}. "
            f"Production готовность: {payload.get('production_ready')}. "
            f"Готовность: {payload.get('completion_percent', 0)}%. "
            f"Осталось: {payload.get('remaining_count', 0)} шагов, блокеров: {payload.get('blocker_count', 0)}.",
            size=21,
        ),
        w_paragraph(f"Следующее действие: {payload.get('next_step', '-')}", size=21),
        w_table(summary_rows, widths=[3000, 5200, 1800], body_size=18),
    ]
    if current:
        body.extend(
            [
                w_paragraph("Текущий следующий шаг", "Heading1", bold=True, size=26),
                w_paragraph(
                    f"{current.get('title', '-')}. Ответственный: {current.get('owner', '-')}. "
                    f"Действие: {current.get('next_action', '-')}. "
                    f"Доказательство: {current.get('evidence_needed', '-')}.",
                    size=21,
                ),
            ]
        )
    body.extend(
        [
            w_paragraph("Ближайшие действия", "Heading1", bold=True, size=26),
            w_table(action_rows, widths=[650, 2600, 2200, 4300, 4200], header_size=14, body_size=14),
            w_paragraph("Полный список открытых шагов", "Heading1", bold=True, size=26),
            w_table(step_rows, widths=[650, 2300, 2500, 1500, 2200, 4300], header_size=14, body_size=14),
            w_paragraph("QA команды", "Heading1", bold=True, size=26),
            w_table(qa_rows, widths=[2600, 1700, 6800], header_size=14, body_size=14),
            w_paragraph("Артефакты", "Heading1", bold=True, size=26),
            w_table(artifact_rows, widths=[3000, 1600, 6200], body_size=16),
            w_paragraph("Правило приемки", "Heading1", bold=True, size=26),
            w_paragraph(
                "Боевой запуск считается принятым только после закрытия всех внешних gates, повторного production smoke и финального go/no-go с ok=true без failed_stages.",
                size=21,
            ),
        ]
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="20"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    exported = document_xml.lower()
    if "demo2026" in exported or "token_hash" in exported or "bearer" in exported or "official-sacc2-key-2026" in exported:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "status board document contains unsafe data")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_reference_docx(payload: dict[str, Any]) -> bytes:
    reference = payload.get("reference", [])
    categories = payload.get("categories", [])
    body: list[str] = [
        w_paragraph("Справочник требований строительной компании", "Title", bold=True, size=32),
        w_paragraph("Разрешительные документы, госпошлины, штрафы, уведомления, проверки и роли", "Subtitle", size=22),
        w_paragraph(f"Дата выгрузки: {payload.get('exported_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {payload.get('exported_by', '-')}", size=20),
        w_paragraph("Статус данных", "Heading1", bold=True, size=26),
        w_paragraph(payload.get("source_note") or REFERENCE_SOURCE_NOTE, size=21),
        w_paragraph("Назначение документа", "Heading1", bold=True, size=26),
        w_paragraph(
            "Документ фиксирует рабочую модель взаимодействия строительной компании с министерством, ДГАСК, региональным отделом и инспектором. "
            "Он помогает назначать ответственных, готовить ответы, контролировать платежи, штрафы, проверки и внутренние поручения.",
            size=21,
        ),
    ]
    for category in categories:
        rows = [["Требование", "Взаимодействие и ответственный", "Действие компании и риск"]]
        for item in [entry for entry in reference if entry.get("category") == category]:
            rows.append(
                [
                    f"{item.get('title', '-')}\nОснование события: {item.get('trigger', '-')}",
                    f"{item.get('interaction', '-')}\nОтветственный: {item.get('responsible', '-')}",
                    f"Действие: {item.get('company_action', '-')}\nРиск: {item.get('risk', '-')}",
                ]
            )
        body.append(w_paragraph(str(category), "Heading1", bold=True, size=26))
        body.append(w_table(rows))
        body.append(w_paragraph(""))
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_legal_verification_packet_docx(packet: dict[str, Any]) -> bytes:
    items = packet.get("items", [])
    categories = packet.get("categories", [])
    counts = packet.get("counts", {})
    official_sources = packet.get("official_sources") if isinstance(packet.get("official_sources"), list) else []
    source_rows = [["Источник", "Орган", "Статус", "Что сверить", "URL"]]
    for source in [entry for entry in official_sources if isinstance(entry, dict)]:
        source_rows.append(
            [
                str(source.get("title") or source.get("id") or "-"),
                str(source.get("authority") or "-"),
                str(source.get("status") or "-"),
                str(source.get("verification_use") or "-"),
                str(source.get("url") or "-"),
            ]
        )
    body: list[str] = [
        w_paragraph("Пакет юридической сверки Qurulush Hub", "Title", bold=True, size=32),
        w_paragraph("Разрешения, госпошлины, штрафы, уведомления, проверки и роли строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата выгрузки: {packet.get('exported_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {packet.get('exported_by', '-')}", size=20),
        w_paragraph("Статус данных", "Heading1", bold=True, size=26),
        w_paragraph(packet.get("source_note") or REFERENCE_SOURCE_NOTE, size=21),
        w_paragraph("Задача сверки", "Heading1", bold=True, size=26),
        w_paragraph(packet.get("purpose", ""), size=21),
        w_paragraph("Что проверяет юрист", "Heading1", bold=True, size=26),
        w_paragraph("; ".join(str(item) for item in packet.get("verification_scope", [])) + ".", size=20),
        w_paragraph("Официальные источники для сверки", "Heading1", bold=True, size=26),
        w_paragraph(packet.get("source_registry_note", ""), size=20),
        w_table(source_rows, widths=[3100, 2600, 1800, 4700, 3200], header_size=14, body_size=13),
        w_paragraph("Сводка по категориям", "Heading1", bold=True, size=26),
        w_table(
            [["Категория", "Позиций"]] + [[category, str(counts.get(category, 0))] for category in categories],
            widths=[6500, 1800],
        ),
    ]
    for index, category in enumerate(categories):
        if index == 0 or category == "Штрафы и нарушения":
            body.append(w_page_break())
        rows = [
            [
                "Требование",
                "Взаимодействие",
                "Ответственный",
                "Правовое основание",
                "Сумма/штраф подтвержден",
                "Источники-кандидаты",
                "Статус сверки",
            ]
        ]
        for item in [entry for entry in items if entry.get("category") == category]:
            sources = item.get("source_candidates") if isinstance(item.get("source_candidates"), list) else []
            source_text = "\n".join(str(source.get("id") or source.get("title") or "-") for source in sources if isinstance(source, dict)) or "Подобрать источник"
            rows.append(
                [
                    f"{item.get('title', '-')}\nКогда: {item.get('trigger', '-')}",
                    f"{item.get('interaction', '-')}\nДействие: {item.get('company_action', '-')}\nРиск: {item.get('risk', '-')}",
                    str(item.get("responsible", "-")),
                    "НПА/регламент: __________\nСтатья/пункт: __________\nСсылка: __________",
                    "Да / Нет / Не применимо",
                    source_text,
                    "needs_review\nПроверил: __________\nДата: __________\nКомментарий: __________",
                ]
            )
        body.append(w_paragraph(str(category), "Heading1", bold=True, size=26))
        body.append(w_table(rows, widths=[2200, 2800, 1600, 2300, 1400, 2200, 1900], header_size=15, body_size=15))
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="20"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


PASSPORT_LABELS = {
    "local_readiness": "Локальная готовность",
    "backup_verify": "Проверка backup",
    "production_readiness": "Production готовность",
    "users": "Пользователи",
    "active_sessions": "Активные сессии",
    "expired_active_sessions": "Просроченные активные сессии",
    "backups": "Резервные копии",
    "backup_manifests_total": "Manifest всего",
    "backup_manifests_valid": "Manifest валидные",
    "backup_manifests_repaired": "Manifest восстановлены",
    "backup_manifests_invalid": "Manifest с ошибками",
    "backup_max_age_hours": "Максимальный возраст backup часов",
    "backup_newest_age_seconds": "Возраст последнего backup секунд",
    "bootstrap_admin": "Боевой администратор",
    "schema_version": "Версия схемы",
    "objects": "Объекты",
    "requests": "Запросы",
    "tasks": "Поручения",
    "reference_items": "Пункты справочника",
    "documents": "Документы",
    "backup_file": "Файл backup",
    "backup_sha256": "SHA-256 backup",
    "backup_integrity": "Целостность backup",
    "https": "HTTPS",
    "corporate_auth": "Корпоративная авторизация",
    "sacc2_api": "Интеграция sacc2 ДГАСК",
    "eds": "ЭЦП",
    "payments": "Платежный шлюз",
    "object_storage": "Внешнее хранилище",
    "av_scan": "Антивирусная проверка",
    "backup_schedule": "Расписание backup",
    "backup_remote": "Удаленный backup",
    "reference_catalog": "Юридическая сверка справочника",
}


def passport_label(key: Any) -> str:
    text = str(key)
    return PASSPORT_LABELS.get(text, text.replace("_", " "))


def compact_checksum(value: Any) -> str:
    text = str(value or "")
    if len(text) <= 24:
        return text
    return f"{text[:16]}...{text[-12:]}"


def build_acceptance_passport_docx(passport: dict[str, Any]) -> bytes:
    readiness = passport.get("readiness", {}) if isinstance(passport.get("readiness"), dict) else {}
    counts = readiness.get("counts", {}) if isinstance(readiness.get("counts"), dict) else {}
    backup = passport.get("backup_verification") or {}
    summary = passport.get("summary") if isinstance(passport.get("summary"), list) else []
    blockers = passport.get("production_blockers") if isinstance(passport.get("production_blockers"), list) else []
    rows = [["Проверка", "Статус", "Деталь"]]
    for item in summary:
        if isinstance(item, dict):
            rows.append([passport_label(item.get("id", "-")), str(item.get("status", "-")), str(item.get("detail", "-"))])
    if not summary:
        rows.append(["Локальная приемка", "pass" if passport.get("local_acceptance") else "warning", "Локальная приемка"])
        rows.append(["Проверка backup", str(passport.get("backup_status", "-")), str(passport.get("backup_detail", "-"))])
        rows.append(["Production приемка", "pass" if passport.get("production_acceptance") else "warning", "Production приемка"])

    count_rows = [["Показатель", "Значение", "Комментарий"]]
    for key, value in counts.items():
        count_rows.append([passport_label(key), str(value), "Счетчик readiness"])
    if backup:
        count_rows.append(["Файл backup", str(backup.get("file", "-")), "Последняя проверенная копия"])
        count_rows.append(["SHA-256 backup", compact_checksum(backup.get("sha256", "-")), "Контрольная сумма"])
        count_rows.append(["Целостность backup", str(backup.get("integrity", "-")), "SQLite integrity"])

    body: list[str] = [
        w_paragraph("Паспорт приемки платформы строительной компании", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {passport.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Проверил: {passport.get('checked_by', '-')}", size=20),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Локальная приемка: {'пройдена' if passport.get('local_acceptance') else 'не полная'}. "
            f"Production приемка: {'пройдена' if passport.get('production_acceptance') else 'не пройдена'}. "
            f"Backup: {passport.get('backup_detail', '-')}.",
            size=21,
        ),
        w_paragraph("Сводка проверок", "Heading1", bold=True, size=26),
        w_table(rows),
        w_paragraph("Счетчики и backup", "Heading1", bold=True, size=26),
        w_table(count_rows),
        w_paragraph("Production blockers", "Heading1", bold=True, size=26),
        w_paragraph(", ".join(passport_label(item) for item in blockers) if blockers else "Нет production blockers.", size=21),
        w_paragraph("Примечание", "Heading1", bold=True, size=26),
        w_paragraph(
            "Документ фиксирует техническую приемку текущего контура. Production запуск считается готовым только после закрытия внешних интеграций, HTTPS, боевой авторизации, удаленного хранения резервных копий и юридической сверки справочника.",
            size=21,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_plan_docx(plan: dict[str, Any]) -> bytes:
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    blockers = plan.get("blockers") if isinstance(plan.get("blockers"), list) else []
    body: list[str] = [
        w_paragraph("План подключения боевого контура", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {plan.get('checked_at', utc_now())}", size=20),
        w_paragraph("Назначение документа", "Heading1", bold=True, size=26),
        w_paragraph(
            "Документ фиксирует, какие production-зависимости уже закрыты и какие настройки еще нужны для боевого запуска платформы строительной компании. "
            "Он рассчитан на директора, IT-исполнителя, юриста и бухгалтера, чтобы каждому был виден свой участок подключения.",
            size=21,
        ),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Production готовность: {'готово' if plan.get('production_ready') else 'не готово'}. "
            f"Закрыто пунктов: {plan.get('ready_count', 0)} из {plan.get('total', len(items))}. "
            f"Открытых блокеров: {plan.get('blocker_count', len(blockers))}.",
            size=21,
        ),
        w_paragraph("План работ", "Heading1", bold=True, size=26),
    ]
    for index, item in enumerate([entry for entry in items if isinstance(entry, dict)], start=1):
        variables = item.get("variables") if isinstance(item.get("variables"), list) else []
        body.extend(
            [
                w_paragraph(f"{index}. {item.get('title', item.get('id', '-'))}", "Heading1", bold=True, size=23),
                w_paragraph(f"Статус: {item.get('status', '-')}. {item.get('detail', '-')}", size=20),
                w_paragraph(f"Ответственный: {item.get('owner', '-')}", size=20),
                w_paragraph("Настройки: " + (", ".join(str(value) for value in variables) or "-"), size=20),
                w_paragraph(f"Следующий шаг: {item.get('next_step', '-')}", size=20),
            ]
        )
    body.extend(
        [
        w_paragraph("Открытые production blockers", "Heading1", bold=True, size=26),
        w_paragraph(", ".join(passport_label(item) for item in blockers) if blockers else "Нет production blockers.", size=21),
        w_paragraph("Контроль приемки", "Heading1", bold=True, size=26),
        w_paragraph(
            "После закрытия пунктов нужно запустить `ops/production_smoke_check.py --require-production`, затем `ops/go_no_go_check.py` с release archive, live URL и backup restore drill. "
            "Только успешный результат этих проверок подтверждает готовность к боевому запуску.",
            size=21,
        ),
        ]
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_interaction_map_docx(payload: dict[str, Any]) -> bytes:
    workflows = payload.get("workflows") if isinstance(payload.get("workflows"), list) else []
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    rows = [["Сценарий", "Источник", "Триггер", "Действие компании", "Роли", "Доказательство и риск"]]
    for item in [entry for entry in workflows if isinstance(entry, dict)]:
        roles = ", ".join(str(role) for role in item.get("company_roles", []) if role)
        status_flow = " -> ".join(str(status) for status in item.get("status_flow", []) if status)
        evidence_risk = f"Доказательство: {item.get('evidence_needed', '-')}\nРиск: {item.get('risk', '-')}\nСтатусы: {status_flow}"
        rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("source") or "-"),
                str(item.get("trigger") or "-"),
                str(item.get("company_action") or "-"),
                roles or "-",
                evidence_risk,
            ]
        )
    body: list[str] = [
        w_paragraph("Карта взаимодействия строительной компании с Минстроем и ДГАСК", "Title", bold=True, size=32),
        w_paragraph("Запросы уведомления проверки документы госпошлины штрафы и обмен sacc2", "Subtitle", size=22),
        w_paragraph(f"Дата выгрузки: {payload.get('exported_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {payload.get('exported_by', '-')}", size=20),
        w_paragraph("Назначение", "Heading1", bold=True, size=26),
        w_paragraph(payload.get("purpose") or "", size=21),
        w_paragraph(payload.get("source_note") or REFERENCE_SOURCE_NOTE, size=21),
        w_paragraph("Текущие счетчики платформы", "Heading1", bold=True, size=26),
        w_table(
            [
                ["Показатель", "Значение"],
                ["Открытые запросы", str(counts.get("open_requests", 0))],
                ["Уведомления", str(counts.get("notifications", 0))],
                ["Срочные уведомления", str(counts.get("urgent_notifications", 0))],
                ["Проверки", str(counts.get("inspections", 0))],
                ["Документы", str(counts.get("documents", 0))],
                ["Неоплаченные начисления", str(counts.get("unpaid_money_items", 0))],
                ["Штрафы", str(counts.get("fines", 0))],
            ],
            widths=[3600, 1800],
        ),
        w_paragraph("Сценарии взаимодействия", "Heading1", bold=True, size=26),
        w_table(rows, widths=[2200, 2100, 3000, 3600, 2200, 4200], header_size=14, body_size=14),
        w_paragraph("Контроль", "Heading1", bold=True, size=26),
        w_paragraph(
            "Каждый сценарий должен завершаться проверяемым доказательством: исходящий номер, файл, подпись, квитанция, JSON-ответ внешнего hook или audit-событие. Перед production запуском карту нужно сверить с официальными регламентами Минстроя / ДГАСК.",
            size=21,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="20"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_evidence_docx(register: dict[str, Any]) -> bytes:
    items = register.get("items") if isinstance(register.get("items"), list) else []
    rows = [["Production gate", "Gate status", "Evidence status", "Ответственный / доказательство"]]
    for item in [entry for entry in items if isinstance(entry, dict)]:
        variables = item.get("variables") if isinstance(item.get("variables"), list) else []
        note_parts = [
            f"Ответственный: {item.get('owner', '-')}",
            f"Дедлайн: {item.get('deadline') or '-'}",
            f"Доказательство: {item.get('evidence') or item.get('next_step') or '-'}",
        ]
        if variables:
            note_parts.append("Настройки: " + ", ".join(str(value) for value in variables))
        rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("gate_status") or "-"),
                str(item.get("evidence_label") or item.get("evidence_status") or "-"),
                "\n".join(note_parts),
            ]
        )
    if len(rows) == 1:
        rows.append(["-", "-", "-", "Нет production gates для выгрузки"])

    body: list[str] = [
        w_paragraph("Evidence-регистр production запуска", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {register.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {register.get('reported_by', '-')}", size=20),
        w_paragraph("Назначение документа", "Heading1", bold=True, size=26),
        w_paragraph(
            "Документ фиксирует доказательства по каждому production gate: кто отвечает, какой дедлайн поставлен, какие письма, ссылки, акты, договоры или регламенты подтверждают готовность.",
            size=21,
        ),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Production готовность: {'готово' if register.get('production_ready') else 'не готово'}. "
            f"Доказательства закрыты: {register.get('done_count', 0)} из {register.get('total', len(items))}. "
            f"Открыто: {register.get('open_count', 0)}. Production blockers: {register.get('blocker_count', 0)}.",
            size=21,
        ),
        w_paragraph("Реестр доказательств", "Heading1", bold=True, size=26),
        w_table(rows, widths=[2300, 1300, 2100, 3900], header_size=16, body_size=17),
        w_paragraph("Контроль приемки", "Heading1", bold=True, size=26),
        w_paragraph(
            "Статус `Доказательство приложено` не заменяет технический go/no-go: после закрытия регистра нужно отдельно пройти production smoke, go/no-go, backup restore drill и юридическую сверку справочника.",
            size=21,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_request_pack_docx(pack: dict[str, Any]) -> bytes:
    items = pack.get("items") if isinstance(pack.get("items"), list) else []
    rows = [["Production gate", "Трекер", "Кому / канал", "Что запросить", "Доказательство / заметка"]]
    for item in [entry for entry in items if isinstance(entry, dict)]:
        rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                (
                    f"{item.get('tracker_label', item.get('tracker_status', '-'))}\n"
                    f"Исх.: {item.get('outgoing_no') or '-'}\n"
                    f"Отправлено: {item.get('sent_at') or '-'}\n"
                    f"Ответ: {item.get('response_at') or '-'}"
                ),
                f"{item.get('stakeholder', '-')}\n{item.get('channel', '-')}",
                f"{item.get('subject', '-')}\n{item.get('request', '-')}",
                f"{item.get('required_evidence', '-')}\nКонтакт: {item.get('contact') or '-'}\nЗаметка: {item.get('tracker_note') or '-'}",
            ]
        )
    if len(rows) == 1:
        rows.append(["-", "-", "Все production gates закрыты или нет открытых запросов.", "-"])

    message_blocks: list[str] = []
    for index, item in enumerate([entry for entry in items if isinstance(entry, dict)], start=1):
        message_blocks.extend(
            [
                w_paragraph(f"{index}. {item.get('subject', item.get('title', '-'))}", "Heading1", bold=True, size=22),
                w_paragraph(item.get("draft_message", "-"), size=19),
            ]
        )

    body: list[str] = [
        w_paragraph("Пакет запросов для закрытия production blockers", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {pack.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {pack.get('reported_by', '-')}", size=20),
        w_paragraph("Назначение документа", "Heading1", bold=True, size=26),
        w_paragraph(
            "Документ превращает открытые production blockers в практические запросы: кому направить, что запросить и какое доказательство вернуть в evidence-регистр перед go/no-go.",
            size=21,
        ),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Открытых запросов: {pack.get('total', len(items))}. Production blockers: {pack.get('blocker_count', 0)}. "
            f"Отправлено: {pack.get('sent_count', 0)}. Ответ получен: {pack.get('answered_count', 0)}. Доказательства приложены: {pack.get('attached_count', 0)}. "
            f"Production готовность: {'готово' if pack.get('production_ready') else 'не готово'}.",
            size=21,
        ),
        w_paragraph("Реестр запросов", "Heading1", bold=True, size=26),
        w_table(rows, widths=[1800, 1700, 2200, 2700, 2200], header_size=15, body_size=15),
        w_paragraph("Готовые тексты запросов", "Heading1", bold=True, size=26),
        *message_blocks,
        w_paragraph("Контроль", "Heading1", bold=True, size=26),
        w_paragraph(
            "После получения ответа по каждому пункту нужно обновить evidence-регистр в платформе и повторно запустить production smoke/go-no-go. Документ не содержит секретов, паролей и API-ключей.",
            size=21,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_official_letters_docx(packet: dict[str, Any]) -> bytes:
    letters = packet.get("letters") if isinstance(packet.get("letters"), list) else []
    body: list[str] = [
        w_paragraph("Пакет официальных писем по production blockers", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата подготовки: {packet.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Подготовил: {packet.get('reported_by', '-')}", size=20),
        w_paragraph("Назначение", "Heading1", bold=True, size=26),
        w_paragraph(
            "Документ содержит готовые проекты обращений и внутренних заявок для закрытия production blockers перед запуском платформы. Перед отправкой нужно заменить подпись, исходящий номер и реквизиты компании.",
            size=21,
        ),
        w_paragraph("Сводка", "Heading1", bold=True, size=26),
        w_table(
            [["Показатель", "Значение"], ["Писем и заявок", str(packet.get("total", len(letters)))], ["Production blockers", str(packet.get("blocker_count", 0))]],
            widths=[4200, 2600],
        ),
    ]
    for letter in [entry for entry in letters if isinstance(entry, dict)]:
        rows = [
            ["Кому", str(letter.get("recipient") or "-")],
            ["Канал", str(letter.get("channel") or "-")],
            ["Тема", str(letter.get("subject") or "-")],
            ["Ответственный", str(letter.get("responsible") or "-")],
            ["Статус", str(letter.get("tracker_label") or letter.get("tracker_status") or "-")],
            ["Доказательство", str(letter.get("required_evidence") or "-")],
        ]
        body.extend(
            [
                w_page_break(),
                w_paragraph(f"Письмо {letter.get('letter_no', '-')}. {letter.get('title', '-')}", "Heading1", bold=True, size=26),
                w_table(rows, widths=[2300, 6500], header_size=17, body_size=18),
                w_paragraph("Текст обращения", "Heading1", bold=True, size=23),
                *[w_paragraph(line, size=21) for line in str(letter.get("body") or "").split("\n") if line.strip()],
                w_paragraph("Подпись", "Heading1", bold=True, size=23),
                *[w_paragraph(line, size=21) for line in str(letter.get("signature_block") or "").split("\n") if line.strip()],
            ]
        )
    if not letters:
        body.append(w_paragraph("Открытых писем нет: production blockers закрыты или request-pack пуст.", size=21))
    body.append(w_paragraph("Контроль", "Heading1", bold=True, size=26))
    body.append(
        w_paragraph(
            "После отправки письма внесите исходящий номер и дату в трекер запросов. После ответа приложите доказательство в evidence-регистр и повторите production smoke/go-no-go.",
            size=21,
        )
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_action_board_docx(board: dict[str, Any]) -> bytes:
    groups = board.get("groups") if isinstance(board.get("groups"), list) else []
    body: list[str] = [
        w_paragraph("Карточки закрытия production blockers по ролям", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {board.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {board.get('reported_by', '-')}", size=20),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Production готовность: {'готово' if board.get('production_ready') else 'не готово'}. "
            f"Blockers: {board.get('blocker_count', 0)}. Запросов: {board.get('request_total', 0)}. "
            f"Отправлено: {board.get('sent_count', 0)}. Ответы: {board.get('answered_count', 0)}. Доказательства: {board.get('attached_count', 0)}.",
            size=21,
        ),
        w_paragraph("Роли и действия", "Heading1", bold=True, size=26),
    ]
    for group in [entry for entry in groups if isinstance(entry, dict)]:
        rows = [["Gate", "Статус", "Ответственный", "Следующий шаг / доказательство"]]
        for item in [entry for entry in group.get("items", []) if isinstance(entry, dict)]:
            rows.append(
                [
                    str(item.get("title") or item.get("id") or "-"),
                    f"{item.get('tracker_label', item.get('tracker_status', '-'))}\n{item.get('gate_status', '-')}",
                    str(item.get("responsible") or item.get("stakeholder") or "-"),
                    f"{item.get('next_action', '-')}\nДоказательство: {item.get('evidence_needed', '-')}\nИсх.: {item.get('outgoing_no') or '-'}; отправлено: {item.get('sent_at') or '-'}; ответ: {item.get('response_at') or '-'}",
                ]
            )
        body.extend(
            [
                w_paragraph(str(group.get("title") or group.get("id") or "-"), "Heading1", bold=True, size=23),
                w_paragraph(
                    f"{group.get('focus', '')} Всего: {group.get('total', 0)}; открыто: {group.get('open_count', 0)}; отправлено: {group.get('sent_count', 0)}.",
                    size=20,
                ),
                w_table(rows, widths=[2200, 1900, 2300, 4000], header_size=16, body_size=16),
            ]
        )
    if not groups:
        body.append(w_paragraph("Открытых ролей нет: production blockers закрыты или request-pack пуст.", size=21))
    body.extend(
        [
            w_paragraph("Контроль", "Heading1", bold=True, size=26),
            w_paragraph(
                "Карточки по ролям используются как ежедневный план закрытия blockers. После каждого ответа обновите request tracker и evidence-регистр, затем повторите production smoke/go-no-go.",
                size=21,
            ),
        ]
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_launch_sequence_docx(sequence: dict[str, Any]) -> bytes:
    phases = sequence.get("phases") if isinstance(sequence.get("phases"), list) else []
    body: list[str] = [
        w_paragraph("Пошаговый план production-запуска", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {sequence.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Выгрузил: {sequence.get('reported_by', '-')}", size=20),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Production готовность: {'готово' if sequence.get('production_ready') else 'не готово'}. "
            f"Всего шагов: {sequence.get('total_steps', 0)}. Закрыто: {sequence.get('done_count', 0)}. "
            f"Открыто: {sequence.get('open_count', 0)}. Blockers: {sequence.get('blocker_count', 0)}.",
            size=21,
        ),
    ]
    current = sequence.get("current_step") if isinstance(sequence.get("current_step"), dict) else None
    if current:
        body.append(
            w_paragraph(
                f"Текущий следующий шаг: {current.get('step_no')}. {current.get('title')} - {current.get('next_action')}",
                size=21,
            )
        )
    for phase in [entry for entry in phases if isinstance(entry, dict)]:
        rows = [["Шаг", "Статус", "Ответственный", "Что сделать / доказательство"]]
        for step in [entry for entry in phase.get("steps", []) if isinstance(entry, dict)]:
            rows.append(
                [
                    f"{step.get('step_no')}. {step.get('title')}\nGate: {step.get('id')}",
                    f"{step.get('status_label', step.get('status', '-'))}\n{step.get('tracker_label', '-')}",
                    f"{step.get('owner', '-')}\nСторона: {step.get('stakeholder', '-')}",
                    f"{step.get('next_action', '-')}\nДоказательство: {step.get('evidence_needed', '-')}\nПеременные: {', '.join(str(value) for value in step.get('variables', []) if value) or '-'}",
                ]
            )
        body.extend(
            [
                w_paragraph(str(phase.get("title") or phase.get("id") or "-"), "Heading1", bold=True, size=23),
                w_paragraph(
                    f"{phase.get('focus', '')} Статус: {phase.get('status_label', phase.get('status', '-'))}. "
                    f"Закрыто: {phase.get('done_count', 0)} из {phase.get('total', 0)}. "
                    f"Критерий выхода: {phase.get('exit_criteria', '-')}",
                    size=20,
                ),
                w_table(rows, widths=[2400, 1600, 2300, 4200], header_size=16, body_size=16),
            ]
        )
    body.extend(
        [
            w_paragraph("Контроль", "Heading1", bold=True, size=26),
            w_paragraph(
                "Переходите к следующему этапу только после приложения доказательств по предыдущему. Финальный запуск допустим после успешного production smoke, go/no-go и паспорта приемки.",
                size=21,
            ),
        ]
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_cutover_docx(report: dict[str, Any]) -> bytes:
    stages = report.get("stages") if isinstance(report.get("stages"), list) else []
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    stage_rows = [["Gate", "Статус", "Блокеры и следующий шаг"]]
    for item in [entry for entry in stages if isinstance(entry, dict)]:
        stage_rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                str(item.get("status") or "-"),
                f"Блокеры: {item.get('blocking_issue_count', 0)}; предупреждения: {item.get('warning_issue_count', 0)}\n{item.get('next_step', '-')}",
            ]
        )
    issue_rows = [["Gate", "Ключ", "Проблема"]]
    for item in [entry for entry in issues if isinstance(entry, dict)]:
        issue_rows.append(
            [
                str(item.get("stage") or "-"),
                str(item.get("key") or item.get("id") or "-"),
                f"{item.get('title', '-')}: {item.get('detail', '-')}",
            ]
        )
    if len(issue_rows) == 1:
        issue_rows.append(["-", "-", "Блокеров нет"])

    body: list[str] = [
        w_paragraph("Production cutover отчет", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {report.get('checked_at', utc_now())}", size=20),
        w_paragraph(f"Домен: {report.get('domain', '-')}", size=20),
        w_paragraph("Назначение документа", "Heading1", bold=True, size=26),
        w_paragraph(
            "Документ фиксирует сводную проверку перед переносом платформы в боевой контур. "
            "Он объединяет домен, production .env, учетные записи, внешние интеграции, хранение файлов, бэкапы и юридический каталог в один go/no-go отчет для директора.",
            size=21,
        ),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Конфигурация cutover: {'готова' if report.get('configuration_ready', report.get('ready_for_production_cutover')) else 'не готова'}. "
            f"Финальная приемка: {'готова' if report.get('ready_for_final_acceptance') else 'требует проверки'}. "
            f"Готовность: {report.get('completion_percent', 0)}%. "
            f"Закрыто gates: {report.get('required_ready_count', 0)} из {report.get('required_total', len(stages))}. "
            f"Блокеры: {report.get('blocking_issue_count', 0)}. Предупреждения: {report.get('warning_issue_count', 0)}.",
            size=21,
        ),
        w_paragraph(f"Следующий шаг: {report.get('next_step', '-')}", size=21),
        w_paragraph("Production gates", "Heading1", bold=True, size=26),
        w_table(stage_rows, widths=[2600, 1300, 5600], body_size=18),
        w_paragraph("Блокеры и предупреждения", "Heading1", bold=True, size=26),
        w_table(issue_rows, widths=[1900, 2600, 5000], body_size=17),
        w_paragraph("Контроль безопасности", "Heading1", bold=True, size=26),
        w_paragraph(
            "Отчет не содержит значений паролей, API ключей и shell команд. В документ выводятся только названия gates, ключи настройки, статусы и действия для закрытия блокеров.",
            size=21,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def build_production_launch_checklist_docx(checklist: dict[str, Any]) -> bytes:
    stages = checklist.get("stages") if isinstance(checklist.get("stages"), list) else []
    commands = checklist.get("commands") if isinstance(checklist.get("commands"), list) else []
    stage_rows = [["Этап", "Статус и ответственный", "Доказательство и следующий шаг"]]
    for item in [entry for entry in stages if isinstance(entry, dict)]:
        stage_rows.append(
            [
                str(item.get("title") or item.get("id") or "-"),
                f"{item.get('status', '-')}\n{item.get('owner', '-')}",
                f"{item.get('evidence', '-')}\n{item.get('next_step', '-')}",
            ]
        )
    command_paragraphs: list[str] = []
    for item in [entry for entry in commands if isinstance(entry, dict)]:
        raw_command = str(item.get("command") or "-")
        if str(item.get("id") or "") == "live_smoke":
            raw_command = "python3 ops/production_smoke_check.py --base-url https://YOUR-DOMAIN/ --email OWNER --password '***' --require-production"
        elif str(item.get("id") or "") == "go_no_go":
            raw_command = "python3 ops/go_no_go_check.py --release RELEASE.zip --env /etc/qurulush-hub/company-platform.env --base-url https://YOUR-DOMAIN/ --email OWNER --password '***' --backups backups --hook-contract-smoke --require-production"
        command_paragraphs.append(
            w_paragraph(
                str(item.get("title") or item.get("id") or "-"),
                "Heading1",
                bold=True,
                size=21,
            )
        )
        command_paragraphs.append(w_paragraph(raw_command, size=18))

    body: list[str] = [
        w_paragraph("Чеклист production запуска", "Title", bold=True, size=32),
        w_paragraph("Qurulush Hub кабинет строительной компании", "Subtitle", size=22),
        w_paragraph(f"Дата проверки: {checklist.get('checked_at', utc_now())}", size=20),
        w_paragraph("Назначение документа", "Heading1", bold=True, size=26),
        w_paragraph(
            "Документ фиксирует порядок вывода платформы в боевой режим. Он показывает, какие этапы должен закрыть директор, DevOps, IT, бухгалтер и юрист, какие доказательства готовности нужны и какие команды запуска подтверждают итоговую приемку.",
            size=21,
        ),
        w_paragraph("Итог", "Heading1", bold=True, size=26),
        w_paragraph(
            f"Production готовность: {'готово' if checklist.get('production_ready') else 'не готово'}. "
            f"Открытых блокеров: {checklist.get('blocker_count', 0)}.",
            size=21,
        ),
        w_paragraph("Этапы запуска", "Heading1", bold=True, size=26),
        w_table(stage_rows, widths=[2400, 2200, 4700], header_size=17, body_size=18),
        w_paragraph("Команды приемки", "Heading1", bold=True, size=26),
        w_paragraph(
            "Команды ниже запускаются после заполнения production env и подключения внешних сервисов. Пароли и ключи не вставляются в документ.",
            size=21,
        ),
        *command_paragraphs,
        w_paragraph("Открытые blockers", "Heading1", bold=True, size=26),
        w_paragraph(
            ", ".join(passport_label(item) for item in checklist.get("blockers", [])) if checklist.get("blockers") else "Нет production blockers.",
            size=21,
        ),
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="900" w:bottom="1080" w:left="900" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
        "</w:styles>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", styles_xml)
    return buffer.getvalue()


def external_request_item(data: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    source = str(data.get("source", "")).strip() or "ДГАСК"
    title = str(data.get("title", "")).strip()
    text = str(data.get("text", "")).strip()
    due = str(data.get("due", "")).strip() or "Нужен срок"
    owner = str(data.get("owner", "")).strip() or "Главный инженер"
    status = str(data.get("status", "needs_company")).strip()
    try:
        obj = int(data.get("object") or 0)
    except (TypeError, ValueError) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "object must be a number") from exc
    if source not in EXCHANGE_SOURCES:
        raise ApiError(HTTPStatus.BAD_REQUEST, "unknown exchange source")
    if status not in EXCHANGE_STATUSES:
        raise ApiError(HTTPStatus.BAD_REQUEST, "unknown request status")
    if not title or not text or not obj:
        raise ApiError(HTTPStatus.BAD_REQUEST, "source, title, text and object are required")
    if not object_exists(state, obj):
        raise ApiError(HTTPStatus.BAD_REQUEST, "object not found")
    return {
        "id": f"EXT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2).upper()}",
        "title": title,
        "object": obj,
        "from": source,
        "owner": owner,
        "due": due,
        "status": status,
        "text": text,
        "history": [{"time": utc_now(), "actor": source, "text": "Импортировано из внешнего контура"}],
    }


def public_state_payload() -> dict[str, Any]:
    payload = deepcopy(SEED)
    payload.pop("users", None)
    payload.setdefault("chat_messages", [])
    return payload


def init_db(db_path: Path = DEFAULT_DB) -> None:
    with open_db(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              payload TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              email TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              role TEXT NOT NULL,
              password_salt TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              email TEXT NOT NULL,
              expires_at REAL NOT NULL,
              created_at TEXT NOT NULL,
              revoked_at TEXT,
              FOREIGN KEY(email) REFERENCES users(email)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS login_attempts (
              email TEXT PRIMARY KEY,
              failed_count INTEGER NOT NULL,
              first_failed_at REAL NOT NULL,
              locked_until REAL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO schema_meta (key, value, updated_at)
            VALUES ('schema_version', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value = excluded.value,
              updated_at = excluded.updated_at
            """,
            (str(SCHEMA_VERSION), utc_now()),
        )
        exists = conn.execute("SELECT 1 FROM app_state WHERE id = 1").fetchone()
        revoke_expired_sessions(conn)
        if not exists:
            conn.execute(
                "INSERT INTO app_state (id, payload, updated_at) VALUES (1, ?, ?)",
                (json.dumps(public_state_payload(), ensure_ascii=False), utc_now()),
            )
        users_exist = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        if not users_exist:
            for user in SEED["users"]:
                salt, password_hash = hash_password(user["password"])
                conn.execute(
                    """
                    INSERT INTO users (email, name, role, password_salt, password_hash, active, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (user["email"], user["name"], user["role"], salt, password_hash, utc_now()),
                )
        apply_bootstrap_users(conn)


def load_state(db_path: Path) -> dict[str, Any]:
    init_db(db_path)
    with open_db(db_path) as conn:
        row = conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if not row:
        return public_state_payload()
    state = public_state_payload()
    state.update(json.loads(row["payload"]))
    state["roles"] = public_state_payload()["roles"]
    state.pop("users", None)
    state.setdefault("chat_messages", [])
    normalize_team_assignments(state)
    normalize_money_records(state)
    return state


def save_state(state: dict[str, Any], db_path: Path) -> None:
    clean_state = deepcopy(state)
    clean_state.pop("users", None)
    with open_db(db_path) as conn:
        conn.execute(
            "UPDATE app_state SET payload = ?, updated_at = ? WHERE id = 1",
            (json.dumps(clean_state, ensure_ascii=False), utc_now()),
        )


def find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((item for item in items if str(item.get("id")) == str(item_id)), None)


def object_exists(state: dict[str, Any], object_id: int) -> bool:
    return any(int(obj["id"]) == int(object_id) for obj in state["objects"])


def has_perm(user: dict[str, Any], perm: str) -> bool:
    perms = ROLE_PERMS.get(user["role"], set())
    return "all" in perms or perm in perms


def role_id_by_title(title: str) -> str | None:
    return next((role["id"] for role in SEED["roles"] if role["title"] == title), None)


def role_title(role_id: str) -> str:
    return next((role["title"] for role in SEED["roles"] if role["id"] == role_id), role_id)


def object_label(state: dict[str, Any], object_ids: list[int] | None) -> str:
    if object_ids is None:
        return "Все объекты"
    names = [str(obj["name"]) for obj in state.get("objects", []) if int(obj["id"]) in set(object_ids)]
    return "; ".join(names) or "Нет назначенных объектов"


def normalize_object_ids(value: Any, state: dict[str, Any]) -> list[int]:
    valid = {int(obj["id"]) for obj in state.get("objects", [])}
    if not isinstance(value, list):
        return []
    clean: list[int] = []
    for item in value:
        try:
            obj = int(item)
        except (TypeError, ValueError):
            continue
        if obj in valid and obj not in clean:
            clean.append(obj)
    return clean


def normalize_team_assignments(state: dict[str, Any]) -> None:
    team = state.setdefault("team", [])
    known_emails = {str(item.get("email", "")).lower() for item in team if item.get("email")}
    known_names = {str(item.get("name", "")) for item in team}
    for seed_item in SEED.get("team", []):
        seed_email = str(seed_item.get("email", "")).lower()
        if seed_email and seed_email not in known_emails and seed_item.get("name") not in known_names:
            team.append(deepcopy(seed_item))
            known_emails.add(seed_email)
            known_names.add(str(seed_item.get("name", "")))
    for item in team:
        role_id = role_id_by_title(str(item.get("role", "")))
        default = ROLE_OBJECT_DEFAULTS.get(role_id or "", None)
        if "object_ids" not in item:
            item["object_ids"] = [] if default is None else list(default)
        else:
            item["object_ids"] = normalize_object_ids(item.get("object_ids"), state)
        if default is None and not item["object_ids"]:
            item["objects"] = "Все объекты"
        elif not item.get("objects") or item.get("objects") in {"По назначению", "3 объекта", "2 объекта", "1 объект"}:
            item["objects"] = object_label(state, item["object_ids"])


def normalize_money_records(state: dict[str, Any]) -> None:
    seed_money = {item["id"]: item for item in SEED.get("money", [])}
    for item in state.get("money", []):
        item.setdefault("history", [])
        if item.get("status") != "Оплачено":
            continue
        seed_item = seed_money.get(item.get("id"), {})
        item.setdefault("payment_no", seed_item.get("payment_no") or f"LEGACY-{item.get('id')}")
        item.setdefault("paid_at", seed_item.get("paid_at") or "legacy")
        item.setdefault("paid_by", seed_item.get("paid_by") or "legacy")


def team_row_for_user(team: list[dict[str, Any]], user: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in team
            if item.get("email") == user.get("email") or item.get("name") == user.get("name")
        ),
        None,
    )


def allowed_object_ids(state: dict[str, Any], user: dict[str, Any]) -> set[int] | None:
    if has_perm(user, "all"):
        return None
    row = team_row_for_user(state.get("team", []), user)
    role_default = ROLE_OBJECT_DEFAULTS.get(user["role"], None)
    if row and not row.get("object_ids") and str(row.get("objects", "")) == "Все объекты":
        return None
    if row and row.get("object_ids"):
        return set(normalize_object_ids(row.get("object_ids"), state))
    if role_default is None:
        return None
    return set(role_default)


def can_access_object(state: dict[str, Any], user: dict[str, Any], object_id: Any) -> bool:
    allowed = allowed_object_ids(state, user)
    if allowed is None:
        return True
    try:
        return int(object_id) in allowed
    except (TypeError, ValueError):
        return False


def require_object_access(state: dict[str, Any], user: dict[str, Any], object_id: Any) -> None:
    if not can_access_object(state, user, object_id):
        raise ApiError(HTTPStatus.FORBIDDEN, "object access required")


def own_team_rows(team: list[dict[str, Any]], user: dict[str, Any]) -> list[dict[str, Any]]:
    row = team_row_for_user(team, user)
    if row:
        return [row]
    return [
        {
            "id": "CURRENT",
            "name": user["name"],
            "role": role_title(user["role"]),
            "email": user["email"],
            "access": "Текущая роль",
            "objects": "По назначению",
            "last": "текущая сессия",
        }
    ]


def filter_state_for_user(state: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    scoped = deepcopy(state)
    scoped.pop("users", None)
    normalize_team_assignments(scoped)
    if has_perm(user, "all"):
        return scoped

    allowed = allowed_object_ids(scoped, user)
    can_requests = has_perm(user, "requests:reply") or has_perm(user, "requests:create")
    can_documents = has_perm(user, "documents:read") or has_perm(user, "documents:upload")
    can_money = has_perm(user, "money:pay") or has_perm(user, "money:appeal")
    can_tasks = has_perm(user, "tasks:create") or has_perm(user, "tasks:update")

    if allowed is not None:
        scoped["objects"] = [item for item in scoped.get("objects", []) if int(item.get("id", 0)) in allowed]
        scoped["requests"] = [item for item in scoped.get("requests", []) if int(item.get("object", 0)) in allowed]
        scoped["documents"] = [item for item in scoped.get("documents", []) if int(item.get("object", 0)) in allowed]
        scoped["inspections"] = [item for item in scoped.get("inspections", []) if int(item.get("object", 0)) in allowed]
        scoped["money"] = [item for item in scoped.get("money", []) if int(item.get("object", 0)) in allowed]
        scoped["tasks"] = [item for item in scoped.get("tasks", []) if int(item.get("object", 0)) in allowed]

    if not can_requests:
        scoped["requests"] = []
    if not can_documents:
        scoped["documents"] = []
    if not has_perm(user, "inspections:prepare"):
        scoped["inspections"] = []
    if not can_money:
        scoped["money"] = []
    if not can_tasks:
        scoped["tasks"] = []

    scoped["team"] = own_team_rows(scoped.get("team", []), user)
    scoped["audit"] = [
        item
        for item in scoped.get("audit", [])
        if item.get("actor") in {user["name"], role_title(user["role"]), "Система"}
        and (allowed is None or item.get("object") is None or int(item.get("object", 0)) in allowed)
    ]
    return scoped


def parse_platform_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw or raw in {"-", "Закрыто", "На рассмотрении"}:
        return None
    lowered = raw.lower()
    today = datetime.now(timezone.utc).astimezone().date()
    if lowered == "сегодня":
        return today
    if lowered == "завтра":
        return date.fromordinal(today.toordinal() + 1)
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def calendar_status(due_date: date | None, done: bool = False) -> tuple[str, int | None, str]:
    if done:
        return "done", None, "Закрыто"
    if due_date is None:
        return "unscheduled", None, "Без срока"
    today = datetime.now(timezone.utc).astimezone().date()
    days_left = due_date.toordinal() - today.toordinal()
    if days_left < 0:
        return "overdue", days_left, "Просрочено"
    if days_left == 0:
        return "today", days_left, "Сегодня"
    if days_left <= 3:
        return "soon", days_left, "Скоро"
    return "planned", days_left, "Запланировано"


def calendar_item(
    item_id: str,
    kind: str,
    title: str,
    object_id: Any,
    owner: str,
    due: Any,
    status_text: str,
    source: str,
    done: bool = False,
) -> dict[str, Any]:
    due_date = parse_platform_date(due)
    status, days_left, urgency = calendar_status(due_date, done)
    return {
        "id": item_id,
        "kind": kind,
        "title": str(title or ""),
        "object": object_id,
        "owner": str(owner or "-"),
        "due": str(due or "-"),
        "due_date": due_date.isoformat() if due_date else "",
        "days_left": days_left,
        "urgency": urgency,
        "calendar_status": status,
        "status": str(status_text or ""),
        "source": str(source or ""),
    }


def calendar_payload(state: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    scoped = filter_state_for_user(state, user)
    items: list[dict[str, Any]] = []
    for task in scoped.get("tasks", []):
        items.append(
            calendar_item(
                str(task.get("id") or ""),
                "Поручение",
                str(task.get("title") or ""),
                task.get("object"),
                str(task.get("owner") or ""),
                task.get("due"),
                str(task.get("status") or ""),
                str(task.get("source") or ""),
                done=str(task.get("status")) == "done",
            )
        )
    for request in scoped.get("requests", []):
        items.append(
            calendar_item(
                str(request.get("id") or ""),
                "Запрос",
                str(request.get("title") or ""),
                request.get("object"),
                str(request.get("owner") or request.get("from") or ""),
                request.get("due"),
                str(request.get("status") or ""),
                str(request.get("from") or ""),
                done=str(request.get("status")) == "done",
            )
        )
    for doc in scoped.get("documents", scoped.get("docs", [])):
        items.append(
            calendar_item(
                str(doc.get("id") or ""),
                "Документ",
                str(doc.get("title") or ""),
                doc.get("object"),
                str(doc.get("owner") or ""),
                doc.get("due"),
                str(doc.get("status") or ""),
                "Разрешительный документ",
                done=str(doc.get("status")) in {"Принят", "Действует"},
            )
        )
    for index, inspection in enumerate(scoped.get("inspections", []), start=1):
        items.append(
            calendar_item(
                str(inspection.get("id") or f"INSP-{index}"),
                "Проверка",
                str(inspection.get("title") or ""),
                inspection.get("object"),
                str(inspection.get("type") or "Проверка"),
                inspection.get("time"),
                str(inspection.get("status") or ""),
                "Инспектор / ДГАСК",
                done=str(inspection.get("status")) == "Материалы отправлены",
            )
        )
    for money in scoped.get("money", []):
        items.append(
            calendar_item(
                str(money.get("id") or ""),
                "Платеж / штраф",
                str(money.get("title") or ""),
                money.get("object"),
                str(money.get("owner") or ""),
                money.get("due"),
                str(money.get("status") or ""),
                f"{int(money.get('amount') or 0):,} сом".replace(",", " "),
                done=str(money.get("status")) == "Оплачено",
            )
        )
    rank = {"overdue": 0, "today": 1, "soon": 2, "planned": 3, "unscheduled": 4, "done": 5}
    items.sort(key=lambda item: (rank.get(str(item.get("calendar_status")), 9), item.get("due_date") or "9999-99-99", item.get("kind") or ""))
    open_items = [item for item in items if item.get("calendar_status") not in {"done"}]
    by_status: dict[str, int] = {}
    for item in items:
        key = str(item.get("calendar_status") or "unknown")
        by_status[key] = by_status.get(key, 0) + 1
    return {
        "format": "qurulush-calendar-v1",
        "generated_at": utc_now(),
        "generated_by": user["name"],
        "role": role_title(user["role"]),
        "items": items,
        "open_count": len(open_items),
        "by_status": by_status,
        "current_item": open_items[0] if open_items else None,
    }


def ai_assistant_reply(state: dict[str, Any], user: dict[str, Any], message: str) -> str:
    calendar = calendar_payload(state, user)
    items = calendar.get("items", [])
    open_items = [item for item in items if item.get("calendar_status") not in {"done"}]
    urgent = [item for item in open_items if item.get("calendar_status") in {"overdue", "today", "soon"}]
    scoped = filter_state_for_user(state, user)
    open_requests = [item for item in scoped.get("requests", []) if item.get("status") in {"needs_company", "review", "informed"}]
    unpaid = [item for item in scoped.get("money", []) if item.get("status") != "Оплачено"]
    production_hint = " Production-gates смотрите в разделе `Готовность запуска`." if has_perm(user, "all") else ""
    text = message.lower()
    if "кален" in text or "срок" in text or "сегодня" in text or "проср" in text:
        if urgent:
            top = urgent[:3]
            lines = [
                f"{item['urgency']}: {item['kind']} {item['id']} - {item['title']} ({item.get('due')}, {object_label(scoped, [int(item['object'])]) if item.get('object') else 'без объекта'})."
                for item in top
            ]
            return "По срокам сначала закройте:\n" + "\n".join(lines) + production_hint
        return "По календарю критических сроков нет. Проверьте плановые элементы и назначьте владельцев без срока." + production_hint
    if "штраф" in text or "плат" in text or "госпош" in text:
        if unpaid:
            top = unpaid[:3]
            return "По платежам и штрафам в работе: " + "; ".join(f"{item.get('id')}: {item.get('title')} - {item.get('status')}, срок {item.get('due')}" for item in top) + "."
        return "Неоплаченных платежей в вашем доступе не вижу."
    if "запрос" in text or "инспектор" in text or "дгаск" in text:
        if open_requests:
            top = open_requests[:3]
            return "По запросам ДГАСК в работе: " + "; ".join(f"{item.get('id')}: {item.get('title')} - срок {item.get('due')}" for item in top) + ". Назначьте внутреннее поручение и приложите доказательство ответа."
        return "Открытых запросов ДГАСК в вашем доступе сейчас нет."
    if urgent:
        item = urgent[0]
        return f"Главный следующий шаг: {item['kind']} {item['id']} - {item['title']}. Срок: {item.get('due')}. Ответственный: {item.get('owner')}. После выполнения приложите доказательство в карточку." + production_hint
    return f"Я вижу {len(open_items)} открытых календарных элементов, {len(open_requests)} запросов и {len(unpaid)} платежей/штрафов в вашем доступе. Напишите 'что по срокам', 'что по ДГАСК' или 'что по штрафам', и я разложу приоритеты." + production_hint


def chat_payload(state: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    messages = state.setdefault("chat_messages", [])
    allowed = allowed_object_ids(state, user)
    visible: list[dict[str, Any]] = []
    for item in messages:
        obj = item.get("object")
        if allowed is not None and obj not in {None, ""}:
            try:
                if int(obj) not in allowed:
                    continue
            except (TypeError, ValueError):
                continue
        visible.append({key: value for key, value in item.items() if key not in {"token_hash", "stored_file"}})
    return {
        "format": "qurulush-internal-chat-v1",
        "generated_at": utc_now(),
        "generated_by": user["name"],
        "role": role_title(user["role"]),
        "messages": visible[-80:],
    }


def future_roadmap_payload(actor: str) -> dict[str, Any]:
    return {
        "format": "qurulush-future-roadmap-v1",
        "generated_at": utc_now(),
        "generated_by": actor,
        "source_note": (
            "Платежные провайдеры нужно сверять по действующим реестрам НБКР и договорам банка/платежной организации. "
            "Каталог ниже задает архитектуру интеграции, а не заменяет юридическую и платежную проверку."
        ),
        "modules": [
            {
                "id": "field_mobile_app",
                "title": "Мобильная field-версия для работников на объекте",
                "purpose": "Легкий мобильный контур для прораба, бригадира и исполнителя: устранение замечаний, фотофиксация, быстрый отчет и отправка доказательств в платформу.",
                "users": ["Прораб", "Бригадир", "Главный инженер", "Исполнитель работ"],
                "workflows": [
                    "Открыть назначенные замечания и поручения по объекту.",
                    "Сделать фото до/после устранения, сжать файл и привязать к карточке замечания.",
                    "Отправить статус устранения, комментарий, геометку/время и фото в единый audit.",
                    "Работать при слабой связи через offline queue с последующей синхронизацией.",
                    "Получать push/чат-уведомления по срокам, проверкам, запросам инспектора и повторным замечаниям.",
                ],
                "integration_contract": [
                    "Использовать тот же объектно-ролевой доступ, что и основная платформа.",
                    "Переиспользовать /api/tasks/{id}/update для статусов устранения.",
                    "Переиспользовать /api/documents/{id}/upload для фото и документов после подключения production storage/AV.",
                    "Переиспользовать /api/inspections/{index}/prepare для подготовки проверки.",
                    "Переиспользовать /api/chat и /api/calendar для полевого чата, ИИ-подсказок и сроков.",
                ],
                "production_requirements": [
                    "PWA или отдельное мобильное приложение с камерой, сжатием фото и offline queue.",
                    "Object-scoped токены и запрет просмотра чужих объектов.",
                    "Production storage, AV scan и лимиты размера файла до включения массовой фотофиксации.",
                    "Журналирование каждого фото, статуса, автора, времени и связанного замечания.",
                ],
                "next_steps": [
                    "Согласовать мобильные роли: кто видит замечания, кто закрывает, кто только фотографирует.",
                    "Добавить мобильный upload endpoint с multipart, thumbnail и проверкой AV/storage.",
                    "Собрать PWA shell и проверить на телефоне с плохой связью.",
                ],
            },
            {
                "id": "kg_payment_orchestration",
                "title": "Платежи Кыргызстана для госпошлин, штрафов и начислений",
                "purpose": "Единый платежный слой: при уведомлении об оплате бухгалтер или директор видит счет, выбирает канал, подтверждает оплату и получает callback/квитанцию в audit.",
                "official_sources": [
                    {"title": "НБКР: реестр операторов платежных систем и платежных организаций", "url": "https://www.nbkr.kg/index1.jsp?item=97&lang=RUS"},
                    {"title": "НБКР: реестр операторов взаимодействия", "url": "https://www.nbkr.kg/index1.jsp?item=3488&lang=RUS"},
                    {"title": "НБКР: нормативные документы по платежным системам", "url": "https://www.nbkr.kg/contout.jsp?item=106&lang=RUS"},
                    {"title": "Элкарт / Межбанковский процессинговый центр", "url": "https://elcart.kg/"},
                    {"title": "MegaPay business/payment example", "url": "https://megapay.kg/"},
                ],
                "payment_methods": [
                    "Банковский счет и интернет-банкинг компании.",
                    "Карта Элкарт/банк-эквайринг через МПЦ или банк-партнер.",
                    "QR/deeplink в мобильный банк или электронный кошелек.",
                    "Платежная организация/агрегатор из действующего реестра НБКР.",
                    "Ручная бухгалтерская отметка с квитанцией, если provider callback недоступен.",
                ],
                "process": [
                    "Платформа получает уведомление о госпошлине, штрафе или начислении.",
                    "Создается invoice/payment intent с объектом, основанием, суммой, сроком и ответственным.",
                    "Бухгалтер или директор нажимает 'Оплатить' и подтверждает канал оплаты.",
                    "Провайдер возвращает payment id, статус, квитанцию или callback.",
                    "Платформа сверяет сумму/назначение, сохраняет квитанцию и закрывает оплату только после подтверждения.",
                ],
                "controls": [
                    "Нет автоматического списания без явного подтверждения уполномоченного пользователя.",
                    "Секреты провайдера не хранятся во frontend и не попадают в launch bundle.",
                    "Каждая операция имеет audit event, provider id, payment id, сумму, назначение и статус сверки.",
                    "Спорные штрафы могут уйти в обжалование вместо оплаты.",
                ],
                "next_steps": [
                    "Выбрать банк/агрегатора и получить merchant/API договор.",
                    "Сверить полный список актуальных провайдеров по реестрам НБКР на дату подключения.",
                    "Реализовать provider registry, invoice API, redirect/deeplink, callback и reconciliation job.",
                ],
            },
        ],
    }


def env_present(*names: str) -> bool:
    return any(bool(os.environ.get(name, "").strip()) for name in names)


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


PLACEHOLDER_ENV_TOKENS = (
    "change_me",
    "changeme",
    "placeholder",
    "provider.example",
    "example.test",
    "example.com",
    "dummy",
    "todo",
    "yyyy-mm-dd",
    "полученный-официальный-ключ",
)


def value_looks_placeholder(value: str) -> bool:
    cleaned = value.strip().lower()
    if not cleaned:
        return False
    if cleaned in {"secret", "token", "password", "key", "provider-name", "test-eds"}:
        return True
    return any(token in cleaned for token in PLACEHOLDER_ENV_TOKENS)


def suspicious_production_env_values() -> list[str]:
    suspicious: list[str] = []
    for name in (
        "QH_BOOTSTRAP_ADMIN_EMAIL",
        "QH_BOOTSTRAP_ADMIN_PASSWORD",
        "QH_BOOTSTRAP_ADMIN_NAME",
        "QH_SACC2_API_URL",
        "QH_SACC2_API_KEY",
        "SACC2_API_KEY",
        "QH_SACC2_SYNC_CMD",
        "QH_SACC2_STATUS_MAP",
        "QH_EDS_PROVIDER",
        "QH_EDS_API_URL",
        "QH_EDS_SIGN_CMD",
        "QH_PAYMENT_GATEWAY_URL",
        "QH_PAYMENT_GATEWAY_CMD",
        "QH_STORAGE_URL",
        "QH_STORAGE_SYNC_CMD",
        "QH_AV_SCANNER",
        "QH_AV_SCANNER_CMD",
        "QH_BACKUP_REMOTE_URL",
        "QH_BACKUP_REMOTE_CMD",
        "QH_REFERENCE_VERIFIED_AT",
        "QH_LEGAL_CATALOG_VERIFIED_AT",
    ):
        value = os.environ.get(name, "").strip()
        if value and value_looks_placeholder(value):
            suspicious.append(name)
    for name in ("QH_SACC2_API_KEY", "SACC2_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value and len(value) < 16:
            suspicious.append(f"{name} слишком короткий")
    return sorted(set(suspicious))


PRODUCTION_ENV_REQUIRED_KEYS = (
    "QH_BOOTSTRAP_ADMIN_EMAIL",
    "QH_BOOTSTRAP_ADMIN_PASSWORD",
    "QH_BOOTSTRAP_ADMIN_NAME",
    "QH_BOOTSTRAP_ADMIN_ROLE",
    "QH_DISABLE_DEMO_USERS",
    "QH_REQUIRE_PRODUCTION",
    "QH_REQUIRE_HOOK_JSON",
    "QH_SACC2_API_URL",
    "QH_SACC2_API_KEY",
    "QH_SACC2_SYNC_CMD",
    "QH_SACC2_STATUS_MAP",
    "QH_EDS_PROVIDER",
    "QH_EDS_API_URL",
    "QH_EDS_SIGN_CMD",
    "QH_PAYMENT_GATEWAY_URL",
    "QH_PAYMENT_GATEWAY_CMD",
    "QH_STORAGE_MODE",
    "QH_STORAGE_URL",
    "QH_STORAGE_SYNC_CMD",
    "QH_AV_SCANNER",
    "QH_BACKUP_INTERVAL_MINUTES",
    "QH_BACKUP_ON_START",
    "QH_BACKUP_REMOTE_URL",
    "QH_BACKUP_REMOTE_CMD",
    "QH_REFERENCE_VERIFIED_AT",
)


def env_validation_issue(issue_id: str, title: str, status: str, detail: str, key: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": issue_id, "title": title, "status": status, "detail": detail}
    if key:
        payload["key"] = key
    return payload


def parse_env_text(raw: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    values: dict[str, str] = {}
    issues: list[dict[str, Any]] = []
    if not raw.strip():
        issues.append(env_validation_issue("env_empty", "Production .env", "fail", "Вставьте содержимое production .env для проверки"))
        return values, issues
    for line_no, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            issues.append(env_validation_issue(f"env_line_{line_no}", "Формат строки", "fail", f"Строка {line_no}: ожидается KEY=VALUE"))
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            issues.append(env_validation_issue(f"env_key_{line_no}", "Название переменной", "fail", f"Строка {line_no}: некорректное название ключа"))
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values, issues


def production_env_value(values: dict[str, str], key: str) -> str:
    return str(values.get(key, "")).strip()


def validate_production_env_text(raw: str) -> dict[str, Any]:
    values, issues = parse_env_text(raw)
    present_keys = sorted(values)

    for key in PRODUCTION_ENV_REQUIRED_KEYS:
        value = production_env_value(values, key)
        if not value:
            issues.append(env_validation_issue(f"missing_{key.lower()}", "Обязательная переменная", "missing", f"Заполните ключ {key}", key))
        elif value_looks_placeholder(value):
            issues.append(env_validation_issue(f"placeholder_{key.lower()}", "Заглушка в production .env", "missing", f"Замените placeholder-значение для {key}", key))

    for key, expected in (
        ("QH_DISABLE_DEMO_USERS", "1"),
        ("QH_REQUIRE_PRODUCTION", "1"),
        ("QH_REQUIRE_HOOK_JSON", "1"),
        ("QH_BACKUP_ON_START", "1"),
    ):
        value = production_env_value(values, key)
        if value and value.lower() not in {expected, "true", "yes", "on"}:
            issues.append(env_validation_issue(f"strict_{key.lower()}", "Production guard", "fail", f"{key} должен быть включен для боевого запуска", key))

    email = production_env_value(values, "QH_BOOTSTRAP_ADMIN_EMAIL")
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        issues.append(env_validation_issue("bootstrap_email_format", "Email администратора", "fail", "QH_BOOTSTRAP_ADMIN_EMAIL должен быть корректным email", "QH_BOOTSTRAP_ADMIN_EMAIL"))
    password = production_env_value(values, "QH_BOOTSTRAP_ADMIN_PASSWORD")
    if password and len(password) < 12:
        issues.append(env_validation_issue("bootstrap_password_length", "Пароль администратора", "fail", "QH_BOOTSTRAP_ADMIN_PASSWORD должен быть не короче 12 символов", "QH_BOOTSTRAP_ADMIN_PASSWORD"))
    role = production_env_value(values, "QH_BOOTSTRAP_ADMIN_ROLE")
    if role and role not in ROLE_PERMS:
        issues.append(env_validation_issue("bootstrap_role_unknown", "Роль администратора", "fail", "QH_BOOTSTRAP_ADMIN_ROLE должен совпадать с ролью платформы", "QH_BOOTSTRAP_ADMIN_ROLE"))

    for key in ("QH_SACC2_API_URL", "QH_EDS_API_URL", "QH_PAYMENT_GATEWAY_URL"):
        value = production_env_value(values, key)
        if value and not value.startswith("https://"):
            issues.append(env_validation_issue(f"https_{key.lower()}", "HTTPS endpoint", "fail", f"{key} должен использовать https://", key))
    for key in ("QH_SACC2_API_KEY",):
        value = production_env_value(values, key)
        if value and len(value) < 16:
            issues.append(env_validation_issue(f"short_{key.lower()}", "API-ключ", "fail", f"{key} выглядит слишком коротким", key))

    storage_mode = production_env_value(values, "QH_STORAGE_MODE").lower()
    if storage_mode and storage_mode == "local":
        issues.append(env_validation_issue("storage_mode_local", "Хранилище документов", "fail", "QH_STORAGE_MODE должен указывать внешний режим хранения", "QH_STORAGE_MODE"))
    backup_interval = production_env_value(values, "QH_BACKUP_INTERVAL_MINUTES")
    if backup_interval:
        try:
            if int(backup_interval) <= 0:
                raise ValueError
        except ValueError:
            issues.append(env_validation_issue("backup_interval_invalid", "Расписание бэкапов", "fail", "QH_BACKUP_INTERVAL_MINUTES должен быть положительным числом", "QH_BACKUP_INTERVAL_MINUTES"))
    verified_at = production_env_value(values, "QH_REFERENCE_VERIFIED_AT")
    if verified_at:
        try:
            datetime.strptime(verified_at, "%Y-%m-%d")
        except ValueError:
            issues.append(env_validation_issue("reference_date_invalid", "Юридическая сверка", "fail", "QH_REFERENCE_VERIFIED_AT должен быть датой YYYY-MM-DD после сверки", "QH_REFERENCE_VERIFIED_AT"))

    by_id: dict[str, dict[str, Any]] = {}
    for item in issues:
        by_id[str(item["id"])] = item
    sanitized_issues = list(by_id.values())
    ready = not sanitized_issues
    return {
        "format": "qurulush-production-env-validation-v1",
        "checked_at": utc_now(),
        "ready": ready,
        "ok": ready,
        "checked_keys": present_keys,
        "required_keys": list(PRODUCTION_ENV_REQUIRED_KEYS),
        "missing_count": sum(1 for item in sanitized_issues if item.get("status") == "missing"),
        "fail_count": sum(1 for item in sanitized_issues if item.get("status") == "fail"),
        "issue_count": len(sanitized_issues),
        "issues": sanitized_issues,
    }


def validate_auth_cutover_payload(raw: str, active_emails: set[str] | None = None) -> dict[str, Any]:
    values, parse_issues = parse_env_text(raw)
    issues: list[dict[str, Any]] = list(parse_issues)
    active_emails = active_emails or set()
    seed_emails = {str(user["email"]).lower() for user in SEED["users"]}

    email = production_env_value(values, "QH_BOOTSTRAP_ADMIN_EMAIL").lower()
    password = production_env_value(values, "QH_BOOTSTRAP_ADMIN_PASSWORD")
    name = production_env_value(values, "QH_BOOTSTRAP_ADMIN_NAME")
    role = production_env_value(values, "QH_BOOTSTRAP_ADMIN_ROLE") or "ceo"
    disable_demo = production_env_value(values, "QH_DISABLE_DEMO_USERS").lower()

    for key, value in (
        ("QH_BOOTSTRAP_ADMIN_EMAIL", email),
        ("QH_BOOTSTRAP_ADMIN_PASSWORD", password),
        ("QH_BOOTSTRAP_ADMIN_NAME", name),
    ):
        if not value:
            issues.append(env_validation_issue(f"auth_missing_{key.lower()}", "Боевой администратор", "missing", f"Заполните {key}", key))
        elif value_looks_placeholder(value):
            issues.append(env_validation_issue(f"auth_placeholder_{key.lower()}", "Боевой администратор", "missing", f"Замените placeholder в {key}", key))

    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        issues.append(env_validation_issue("auth_email_format", "Email администратора", "fail", "QH_BOOTSTRAP_ADMIN_EMAIL должен быть корректным email", "QH_BOOTSTRAP_ADMIN_EMAIL"))
    if email and email in seed_emails:
        issues.append(env_validation_issue("auth_email_demo", "Боевой администратор", "fail", "Email bootstrap-администратора не должен совпадать с demo-аккаунтом", "QH_BOOTSTRAP_ADMIN_EMAIL"))
    if password and len(password) < 12:
        issues.append(env_validation_issue("auth_password_length", "Пароль администратора", "fail", "Пароль bootstrap-администратора должен быть не короче 12 символов", "QH_BOOTSTRAP_ADMIN_PASSWORD"))
    if role not in ROLE_PERMS:
        issues.append(env_validation_issue("auth_role_unknown", "Роль администратора", "fail", "QH_BOOTSTRAP_ADMIN_ROLE должен совпадать с ролью платформы", "QH_BOOTSTRAP_ADMIN_ROLE"))
    if disable_demo not in {"1", "true", "yes", "on"}:
        issues.append(env_validation_issue("auth_disable_demo", "Отключение demo-учеток", "fail", "Для production задайте QH_DISABLE_DEMO_USERS=1", "QH_DISABLE_DEMO_USERS"))

    active_demo_users = sorted(seed_emails & {email.lower() for email in active_emails})
    if active_demo_users:
        issues.append(
            env_validation_issue(
                "auth_current_demo_active",
                "Текущая база",
                "warning",
                f"В текущей базе активных demo-аккаунтов: {len(active_demo_users)}; после production restart с QH_DISABLE_DEMO_USERS=1 они должны быть отключены.",
            )
        )

    blocking_issues = [item for item in issues if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-auth-cutover-validation-v1",
        "checked_at": utc_now(),
        "ready_for_cutover": not blocking_issues,
        "bootstrap_email": email,
        "bootstrap_role": role if role in ROLE_PERMS else "",
        "demo_accounts_known": len(seed_emails),
        "active_demo_count": len(active_demo_users),
        "issue_count": len(issues),
        "blocking_issue_count": len(blocking_issues),
        "issues": list({str(item["id"]): item for item in issues}.values()),
        "next_step": (
            "Сохраните production .env на сервере и перезапустите сервис с QH_REQUIRE_PRODUCTION=1."
            if not blocking_issues
            else "Заполните bootstrap-администратора, включите QH_DISABLE_DEMO_USERS=1 и используйте недемо email."
        ),
    }


def production_account_cutover_payload(conn: sqlite3.Connection, state: dict[str, Any], actor: str) -> dict[str, Any]:
    seed_emails = {str(user["email"]).lower() for user in SEED["users"]}
    rows = conn.execute(
        """
        SELECT email, name, role, active, created_at
        FROM users
        ORDER BY active DESC, role ASC, email ASC
        """
    ).fetchall()
    team_by_email = {
        str(item.get("email", "")).strip().lower(): item
        for item in state.get("team", [])
        if isinstance(item, dict) and item.get("email")
    }
    users: list[dict[str, Any]] = []
    active_demo_count = 0
    active_real_count = 0
    inactive_demo_count = 0
    role_counts: dict[str, dict[str, int]] = {
        str(role["id"]): {"real": 0, "demo": 0, "inactive_demo": 0}
        for role in SEED["roles"]
    }
    for row in rows:
        email = str(row["email"]).strip().lower()
        role_id = str(row["role"] or "")
        active = bool(row["active"])
        is_demo = email in seed_emails
        is_real = not is_demo
        if active and is_demo:
            active_demo_count += 1
        if active and is_real:
            active_real_count += 1
        if not active and is_demo:
            inactive_demo_count += 1
        counts = role_counts.setdefault(role_id, {"real": 0, "demo": 0, "inactive_demo": 0})
        if active and is_real:
            counts["real"] += 1
        elif active and is_demo:
            counts["demo"] += 1
        elif is_demo:
            counts["inactive_demo"] += 1
        team_row = team_by_email.get(email, {})
        users.append(
            {
                "email": email,
                "name": str(row["name"] or ""),
                "role": role_id,
                "role_title": role_title(role_id),
                "active": active,
                "account_type": "demo" if is_demo else "real",
                "object_scope": str(team_row.get("objects") or ("Все объекты" if role_id in {"ceo", "chief_engineer", "accountant", "lawyer"} else "Не назначено")),
                "created_at": str(row["created_at"] or ""),
            }
        )

    required_roles = {"ceo", "chief_engineer", "foreman", "brigadier", "accountant", "lawyer"}
    role_coverage: list[dict[str, Any]] = []
    missing_real_roles: list[str] = []
    demo_only_roles: list[str] = []
    for role in SEED["roles"]:
        role_id = str(role["id"])
        counts = role_counts.get(role_id, {"real": 0, "demo": 0, "inactive_demo": 0})
        real_count = int(counts.get("real", 0))
        demo_count = int(counts.get("demo", 0))
        required = role_id in required_roles
        if required and not real_count:
            missing_real_roles.append(role_id)
            if demo_count:
                demo_only_roles.append(role_id)
        role_coverage.append(
            {
                "id": role_id,
                "title": str(role["title"]),
                "required": required,
                "real_active_count": real_count,
                "demo_active_count": demo_count,
                "inactive_demo_count": int(counts.get("inactive_demo", 0)),
                "status": "ready" if real_count else ("demo_only" if demo_count else "missing"),
            }
        )

    blockers: list[dict[str, Any]] = []
    if active_demo_count:
        blockers.append(
            {
                "id": "active_demo_users",
                "title": "Активные demo-аккаунты",
                "detail": f"Осталось активных demo-пользователей: {active_demo_count}. Для production включите QH_DISABLE_DEMO_USERS=1 после создания реального администратора.",
            }
        )
    if missing_real_roles:
        blockers.append(
            {
                "id": "missing_real_roles",
                "title": "Не закрыты реальные роли",
                "detail": "Нет активных недемо-аккаунтов для ролей: " + ", ".join(role_title(role_id) for role_id in missing_real_roles),
            }
        )
    if not active_real_count:
        blockers.append(
            {
                "id": "no_real_users",
                "title": "Нет реальных пользователей",
                "detail": "Добавьте хотя бы одного сотрудника на корпоративный email перед отключением demo-доступов.",
            }
        )

    next_steps = [
        "Создать bootstrap-администратора на реальный корпоративный email.",
        "Пригласить директора, главного инженера, прораба, бригадира, бухгалтера и юриста с назначением объектов.",
        "Проверить вход каждого реального пользователя и смену временного пароля.",
        "Включить QH_DISABLE_DEMO_USERS=1 и перезапустить production-сервис.",
        "Повторно открыть этот отчет: active_demo_count должен стать 0, а все обязательные роли - ready.",
    ]

    ready_for_account_cutover = not blockers
    return {
        "format": "qurulush-production-account-cutover-v1",
        "checked_at": utc_now(),
        "reported_by": actor,
        "ready_for_account_cutover": ready_for_account_cutover,
        "counts": {
            "active_total": sum(1 for item in users if item["active"]),
            "active_real": active_real_count,
            "active_demo": active_demo_count,
            "inactive_demo": inactive_demo_count,
            "required_roles": len(required_roles),
            "roles_ready": sum(1 for item in role_coverage if item["required"] and item["status"] == "ready"),
            "missing_real_roles": len(missing_real_roles),
        },
        "role_coverage": role_coverage,
        "users": users,
        "blockers": blockers,
        "demo_only_roles": demo_only_roles,
        "next_steps": next_steps,
        "next_step": "Учетные записи готовы к production cutover." if ready_for_account_cutover else next_steps[0],
    }


HOOK_CONTRACT_REQUIREMENTS = (
    {
        "id": "sacc2",
        "title": "sacc2 / ДГАСК",
        "command": "QH_SACC2_SYNC_CMD",
        "markers": ("{payload}",),
        "allowed_statuses": ("ok", "synced"),
    },
    {
        "id": "eds",
        "title": "ЭЦП",
        "command": "QH_EDS_SIGN_CMD",
        "markers": ("{payload}",),
        "allowed_statuses": ("ok", "signed"),
    },
    {
        "id": "payment_gateway",
        "title": "Платежный шлюз",
        "command": "QH_PAYMENT_GATEWAY_CMD",
        "markers": ("{payload}",),
        "allowed_statuses": ("ok", "confirmed", "paid"),
    },
    {
        "id": "storage",
        "title": "Хранилище документов",
        "command": "QH_STORAGE_SYNC_CMD",
        "markers": ("{file}",),
        "allowed_statuses": ("ok", "stored", "uploaded", "synced"),
    },
    {
        "id": "av_scanner",
        "title": "Антивирусная проверка",
        "command": "QH_AV_SCANNER",
        "markers": ("{file}",),
        "allowed_statuses": ("ok", "clean"),
    },
    {
        "id": "backup_remote",
        "title": "Удаленный backup",
        "command": "QH_BACKUP_REMOTE_CMD",
        "markers": ("{backup}", "{manifest}"),
        "allowed_statuses": ("ok", "stored", "uploaded", "synced"),
    },
)


def validate_hook_contracts_payload(raw: str) -> dict[str, Any]:
    values, issues = parse_env_text(raw)
    hook_items: list[dict[str, Any]] = []

    require_json = production_env_value(values, "QH_REQUIRE_HOOK_JSON").lower()
    if require_json not in {"1", "true", "yes", "on"}:
        issues.append(env_validation_issue("hooks_require_json", "JSON-контракты hooks", "fail", "Для production задайте QH_REQUIRE_HOOK_JSON=1", "QH_REQUIRE_HOOK_JSON"))

    for requirement in HOOK_CONTRACT_REQUIREMENTS:
        command_key = str(requirement["command"])
        raw_command = production_env_value(values, command_key)
        item_issues: list[dict[str, Any]] = []
        if not raw_command:
            item_issues.append(env_validation_issue(f"hook_missing_{requirement['id']}", str(requirement["title"]), "missing", f"Заполните {command_key}", command_key))
        elif value_looks_placeholder(raw_command):
            item_issues.append(env_validation_issue(f"hook_placeholder_{requirement['id']}", str(requirement["title"]), "missing", f"Замените placeholder в {command_key}", command_key))
        else:
            try:
                parts = shlex.split(raw_command)
            except ValueError:
                parts = []
                item_issues.append(env_validation_issue(f"hook_syntax_{requirement['id']}", str(requirement["title"]), "fail", f"{command_key} должен быть корректной shell-like командой", command_key))
            if not parts:
                item_issues.append(env_validation_issue(f"hook_empty_{requirement['id']}", str(requirement["title"]), "fail", f"{command_key} не должен быть пустым", command_key))
            for marker in requirement["markers"]:
                if marker not in raw_command:
                    item_issues.append(env_validation_issue(f"hook_marker_{requirement['id']}_{marker.strip('{}')}", str(requirement["title"]), "fail", f"{command_key} должен содержать маркер {marker}", command_key))
        issues.extend(item_issues)
        hook_items.append(
            {
                "id": requirement["id"],
                "title": requirement["title"],
                "command_key": command_key,
                "required_markers": list(requirement["markers"]),
                "allowed_statuses": list(requirement["allowed_statuses"]),
                "status": "pass" if not item_issues else "fail",
                "issue_count": len(item_issues),
            }
        )

    deduped = list({str(item["id"]): item for item in issues}.values())
    blocking_issues = [item for item in deduped if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-hook-contract-validation-v1",
        "checked_at": utc_now(),
        "ready_for_hook_smoke": not blocking_issues,
        "hook_count": len(hook_items),
        "ready_hook_count": sum(1 for item in hook_items if item["status"] == "pass"),
        "issue_count": len(deduped),
        "blocking_issue_count": len(blocking_issues),
        "issues": deduped,
        "hooks": hook_items,
        "next_step": (
            "Запустите ops/hook_contract_smoke.py с защищенным production env и проверьте реальные JSON-ответы hooks."
            if not blocking_issues
            else "Заполните hook-команды, включите QH_REQUIRE_HOOK_JSON=1 и добавьте обязательные маркеры payload/file/backup/manifest."
        ),
    }


def parse_sacc2_status_map(raw_map: str) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not raw_map.strip():
        issues.append(env_validation_issue("sacc2_status_map_missing", "Регламент статусов sacc2", "missing", "Заполните QH_SACC2_STATUS_MAP", "QH_SACC2_STATUS_MAP"))
        return {}, issues
    try:
        parsed = json.loads(raw_map)
    except json.JSONDecodeError:
        issues.append(env_validation_issue("sacc2_status_map_json", "Регламент статусов sacc2", "fail", "QH_SACC2_STATUS_MAP должен быть JSON-объектом", "QH_SACC2_STATUS_MAP"))
        return {}, issues
    if not isinstance(parsed, dict):
        issues.append(env_validation_issue("sacc2_status_map_object", "Регламент статусов sacc2", "fail", "QH_SACC2_STATUS_MAP должен быть JSON-объектом", "QH_SACC2_STATUS_MAP"))
        return {}, issues
    normalized: dict[str, list[str]] = {}
    for platform_status in sorted(EXCHANGE_STATUSES):
        raw_value = parsed.get(platform_status)
        if isinstance(raw_value, str) and raw_value.strip():
            normalized[platform_status] = [raw_value.strip()]
        elif isinstance(raw_value, list) and all(isinstance(item, str) and item.strip() for item in raw_value):
            normalized[platform_status] = [item.strip() for item in raw_value]
        else:
            issues.append(env_validation_issue(f"sacc2_status_map_{platform_status}", "Регламент статусов sacc2", "fail", f"Добавьте внешние статусы для {platform_status}", "QH_SACC2_STATUS_MAP"))
    return normalized, issues


def validate_sacc2_exchange_payload(raw: str) -> dict[str, Any]:
    values, issues = parse_env_text(raw)
    api_url = production_env_value(values, "QH_SACC2_API_URL")
    api_key = production_env_value(values, "QH_SACC2_API_KEY") or production_env_value(values, "SACC2_API_KEY")
    command = production_env_value(values, "QH_SACC2_SYNC_CMD")
    require_json = production_env_value(values, "QH_REQUIRE_HOOK_JSON").lower()

    if not api_url:
        issues.append(env_validation_issue("sacc2_api_url_missing", "sacc2 API URL", "missing", "Заполните QH_SACC2_API_URL", "QH_SACC2_API_URL"))
    elif value_looks_placeholder(api_url):
        issues.append(env_validation_issue("sacc2_api_url_placeholder", "sacc2 API URL", "missing", "Замените placeholder в QH_SACC2_API_URL", "QH_SACC2_API_URL"))
    elif not api_url.startswith("https://"):
        issues.append(env_validation_issue("sacc2_api_url_https", "sacc2 API URL", "fail", "QH_SACC2_API_URL должен использовать https://", "QH_SACC2_API_URL"))
    elif "sacc2.avn.kg" not in urlparse(api_url).netloc:
        issues.append(env_validation_issue("sacc2_api_url_confirm", "sacc2 API URL", "warning", "Подтвердите, что URL выдан официальным контуром sacc2 / ДГАСК", "QH_SACC2_API_URL"))

    if not api_key:
        issues.append(env_validation_issue("sacc2_api_key_missing", "sacc2 API-ключ", "missing", "Заполните QH_SACC2_API_KEY", "QH_SACC2_API_KEY"))
    elif value_looks_placeholder(api_key) or len(api_key) < 16:
        issues.append(env_validation_issue("sacc2_api_key_unsafe", "sacc2 API-ключ", "fail", "QH_SACC2_API_KEY выглядит как заглушка или слишком короткий ключ", "QH_SACC2_API_KEY"))

    if not command:
        issues.append(env_validation_issue("sacc2_command_missing", "sacc2 sync-команда", "missing", "Заполните QH_SACC2_SYNC_CMD", "QH_SACC2_SYNC_CMD"))
    elif value_looks_placeholder(command):
        issues.append(env_validation_issue("sacc2_command_placeholder", "sacc2 sync-команда", "missing", "Замените placeholder в QH_SACC2_SYNC_CMD", "QH_SACC2_SYNC_CMD"))
    else:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
            issues.append(env_validation_issue("sacc2_command_syntax", "sacc2 sync-команда", "fail", "QH_SACC2_SYNC_CMD должен быть корректной shell-like командой", "QH_SACC2_SYNC_CMD"))
        if not parts:
            issues.append(env_validation_issue("sacc2_command_empty", "sacc2 sync-команда", "fail", "QH_SACC2_SYNC_CMD не должен быть пустым", "QH_SACC2_SYNC_CMD"))
        if "{payload}" not in command:
            issues.append(env_validation_issue("sacc2_command_payload_marker", "sacc2 sync-команда", "fail", "QH_SACC2_SYNC_CMD должен содержать маркер {payload}", "QH_SACC2_SYNC_CMD"))

    if require_json not in {"1", "true", "yes", "on"}:
        issues.append(env_validation_issue("sacc2_require_hook_json", "JSON-ответ sacc2", "fail", "Для production задайте QH_REQUIRE_HOOK_JSON=1", "QH_REQUIRE_HOOK_JSON"))

    status_map, status_issues = parse_sacc2_status_map(production_env_value(values, "QH_SACC2_STATUS_MAP"))
    issues.extend(status_issues)
    deduped = list({str(item["id"]): item for item in issues}.values())
    blocking_issues = [item for item in deduped if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-sacc2-exchange-validation-v1",
        "checked_at": utc_now(),
        "ready_for_sacc2_smoke": not blocking_issues,
        "api_url_host": urlparse(api_url).netloc if api_url else "",
        "status_map": status_map,
        "platform_statuses": sorted(EXCHANGE_STATUSES),
        "allowed_hook_statuses": ["ok", "synced"],
        "issue_count": len(deduped),
        "blocking_issue_count": len(blocking_issues),
        "issues": deduped,
        "next_step": (
            "Запустите sacc2 hook dry-run и согласуйте регламент статусов с ДГАСК/Минстроем."
            if not blocking_issues
            else "Заполните QH_SACC2_API_URL, QH_SACC2_API_KEY, QH_SACC2_SYNC_CMD и QH_SACC2_STATUS_MAP."
        ),
    }


def validate_eds_integration_payload(raw: str) -> dict[str, Any]:
    values, issues = parse_env_text(raw)
    provider = production_env_value(values, "QH_EDS_PROVIDER")
    api_url = production_env_value(values, "QH_EDS_API_URL")
    command = production_env_value(values, "QH_EDS_SIGN_CMD")
    require_json = production_env_value(values, "QH_REQUIRE_HOOK_JSON").lower()

    if not provider:
        issues.append(env_validation_issue("eds_provider_missing", "Провайдер ЭЦП", "missing", "Заполните QH_EDS_PROVIDER", "QH_EDS_PROVIDER"))
    elif value_looks_placeholder(provider):
        issues.append(env_validation_issue("eds_provider_placeholder", "Провайдер ЭЦП", "missing", "Замените placeholder в QH_EDS_PROVIDER", "QH_EDS_PROVIDER"))

    if not api_url:
        issues.append(env_validation_issue("eds_api_url_missing", "EDS API URL", "missing", "Заполните QH_EDS_API_URL", "QH_EDS_API_URL"))
    elif value_looks_placeholder(api_url):
        issues.append(env_validation_issue("eds_api_url_placeholder", "EDS API URL", "missing", "Замените placeholder в QH_EDS_API_URL", "QH_EDS_API_URL"))
    elif not api_url.startswith("https://"):
        issues.append(env_validation_issue("eds_api_url_https", "EDS API URL", "fail", "QH_EDS_API_URL должен использовать https://", "QH_EDS_API_URL"))

    if not command:
        issues.append(env_validation_issue("eds_command_missing", "Команда подписи ЭЦП", "missing", "Заполните QH_EDS_SIGN_CMD", "QH_EDS_SIGN_CMD"))
    elif value_looks_placeholder(command):
        issues.append(env_validation_issue("eds_command_placeholder", "Команда подписи ЭЦП", "missing", "Замените placeholder в QH_EDS_SIGN_CMD", "QH_EDS_SIGN_CMD"))
    else:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
            issues.append(env_validation_issue("eds_command_syntax", "Команда подписи ЭЦП", "fail", "QH_EDS_SIGN_CMD должен быть корректной shell-like командой", "QH_EDS_SIGN_CMD"))
        if not parts:
            issues.append(env_validation_issue("eds_command_empty", "Команда подписи ЭЦП", "fail", "QH_EDS_SIGN_CMD не должен быть пустым", "QH_EDS_SIGN_CMD"))
        if "{payload}" not in command:
            issues.append(env_validation_issue("eds_command_payload_marker", "Команда подписи ЭЦП", "fail", "QH_EDS_SIGN_CMD должен содержать маркер {payload}", "QH_EDS_SIGN_CMD"))

    if require_json not in {"1", "true", "yes", "on"}:
        issues.append(env_validation_issue("eds_require_hook_json", "JSON-ответ ЭЦП", "fail", "Для production задайте QH_REQUIRE_HOOK_JSON=1", "QH_REQUIRE_HOOK_JSON"))

    deduped = list({str(item["id"]): item for item in issues}.values())
    blocking_issues = [item for item in deduped if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-eds-integration-validation-v1",
        "checked_at": utc_now(),
        "ready_for_eds_smoke": not blocking_issues,
        "provider": provider if provider and not value_looks_placeholder(provider) else "",
        "api_url_host": urlparse(api_url).netloc if api_url else "",
        "command_key": "QH_EDS_SIGN_CMD",
        "required_payload_fields": ["document_id", "title", "file_sha256", "comment", "signed_by_email", "eds_provider", "eds_api_url"],
        "allowed_hook_statuses": ["ok", "signed"],
        "issue_count": len(deduped),
        "blocking_issue_count": len(blocking_issues),
        "issues": deduped,
        "next_step": (
            "Запустите ЭЦП hook dry-run, подпишите тестовый документ и проверьте audit trail."
            if not blocking_issues
            else "Заполните QH_EDS_PROVIDER, QH_EDS_API_URL, QH_EDS_SIGN_CMD и включите QH_REQUIRE_HOOK_JSON=1."
        ),
    }


def validate_payment_gateway_payload(raw: str) -> dict[str, Any]:
    values, issues = parse_env_text(raw)
    gateway_url = production_env_value(values, "QH_PAYMENT_GATEWAY_URL")
    command = production_env_value(values, "QH_PAYMENT_GATEWAY_CMD")
    require_json = production_env_value(values, "QH_REQUIRE_HOOK_JSON").lower()

    if not gateway_url:
        issues.append(env_validation_issue("payment_gateway_url_missing", "Платежный gateway URL", "missing", "Заполните QH_PAYMENT_GATEWAY_URL", "QH_PAYMENT_GATEWAY_URL"))
    elif value_looks_placeholder(gateway_url):
        issues.append(env_validation_issue("payment_gateway_url_placeholder", "Платежный gateway URL", "missing", "Замените placeholder в QH_PAYMENT_GATEWAY_URL", "QH_PAYMENT_GATEWAY_URL"))
    elif not gateway_url.startswith("https://"):
        issues.append(env_validation_issue("payment_gateway_url_https", "Платежный gateway URL", "fail", "QH_PAYMENT_GATEWAY_URL должен использовать https://", "QH_PAYMENT_GATEWAY_URL"))

    if not command:
        issues.append(env_validation_issue("payment_gateway_command_missing", "Команда платежного шлюза", "missing", "Заполните QH_PAYMENT_GATEWAY_CMD", "QH_PAYMENT_GATEWAY_CMD"))
    elif value_looks_placeholder(command):
        issues.append(env_validation_issue("payment_gateway_command_placeholder", "Команда платежного шлюза", "missing", "Замените placeholder в QH_PAYMENT_GATEWAY_CMD", "QH_PAYMENT_GATEWAY_CMD"))
    else:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
            issues.append(env_validation_issue("payment_gateway_command_syntax", "Команда платежного шлюза", "fail", "QH_PAYMENT_GATEWAY_CMD должен быть корректной shell-like командой", "QH_PAYMENT_GATEWAY_CMD"))
        if not parts:
            issues.append(env_validation_issue("payment_gateway_command_empty", "Команда платежного шлюза", "fail", "QH_PAYMENT_GATEWAY_CMD не должен быть пустым", "QH_PAYMENT_GATEWAY_CMD"))
        if "{payload}" not in command:
            issues.append(env_validation_issue("payment_gateway_command_payload_marker", "Команда платежного шлюза", "fail", "QH_PAYMENT_GATEWAY_CMD должен содержать маркер {payload}", "QH_PAYMENT_GATEWAY_CMD"))

    if require_json not in {"1", "true", "yes", "on"}:
        issues.append(env_validation_issue("payment_gateway_require_hook_json", "JSON-ответ платежей", "fail", "Для production задайте QH_REQUIRE_HOOK_JSON=1", "QH_REQUIRE_HOOK_JSON"))

    deduped = list({str(item["id"]): item for item in issues}.values())
    blocking_issues = [item for item in deduped if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-payment-gateway-validation-v1",
        "checked_at": utc_now(),
        "ready_for_payment_smoke": not blocking_issues,
        "gateway_host": urlparse(gateway_url).netloc if gateway_url else "",
        "command_key": "QH_PAYMENT_GATEWAY_CMD",
        "required_payload_fields": ["payment_id", "title", "object", "amount", "payment_no", "receipt", "paid_by_email", "gateway_url"],
        "allowed_hook_statuses": ["ok", "confirmed", "paid"],
        "issue_count": len(deduped),
        "blocking_issue_count": len(blocking_issues),
        "issues": deduped,
        "next_step": (
            "Запустите payment hook dry-run и оплатите тестовую госпошлину/штраф через staging-шлюз."
            if not blocking_issues
            else "Заполните QH_PAYMENT_GATEWAY_URL, QH_PAYMENT_GATEWAY_CMD и включите QH_REQUIRE_HOOK_JSON=1."
        ),
    }


def validate_storage_integration_payload(raw: str) -> dict[str, Any]:
    values, issues = parse_env_text(raw)
    mode = production_env_value(values, "QH_STORAGE_MODE").lower()
    storage_url = production_env_value(values, "QH_STORAGE_URL")
    command = production_env_value(values, "QH_STORAGE_SYNC_CMD")
    require_json = production_env_value(values, "QH_REQUIRE_HOOK_JSON").lower()

    if not mode:
        issues.append(env_validation_issue("storage_mode_missing", "Режим хранилища", "missing", "Заполните QH_STORAGE_MODE", "QH_STORAGE_MODE"))
    elif value_looks_placeholder(mode):
        issues.append(env_validation_issue("storage_mode_placeholder", "Режим хранилища", "missing", "Замените placeholder в QH_STORAGE_MODE", "QH_STORAGE_MODE"))
    elif mode == "local":
        issues.append(env_validation_issue("storage_mode_local", "Режим хранилища", "fail", "Для production нужен внешний режим хранения, не local", "QH_STORAGE_MODE"))

    if not storage_url:
        issues.append(env_validation_issue("storage_url_missing", "Адрес хранилища", "missing", "Заполните QH_STORAGE_URL", "QH_STORAGE_URL"))
    elif value_looks_placeholder(storage_url):
        issues.append(env_validation_issue("storage_url_placeholder", "Адрес хранилища", "missing", "Замените placeholder в QH_STORAGE_URL", "QH_STORAGE_URL"))
    elif not re.match(r"^(s3|https|gs|azure|file)://", storage_url):
        issues.append(env_validation_issue("storage_url_scheme", "Адрес хранилища", "fail", "QH_STORAGE_URL должен начинаться с s3://, https://, gs://, azure:// или file://", "QH_STORAGE_URL"))

    if not command:
        issues.append(env_validation_issue("storage_command_missing", "Команда синхронизации", "missing", "Заполните QH_STORAGE_SYNC_CMD", "QH_STORAGE_SYNC_CMD"))
    elif value_looks_placeholder(command):
        issues.append(env_validation_issue("storage_command_placeholder", "Команда синхронизации", "missing", "Замените placeholder в QH_STORAGE_SYNC_CMD", "QH_STORAGE_SYNC_CMD"))
    else:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
            issues.append(env_validation_issue("storage_command_syntax", "Команда синхронизации", "fail", "QH_STORAGE_SYNC_CMD должен быть корректной shell-like командой", "QH_STORAGE_SYNC_CMD"))
        if not parts:
            issues.append(env_validation_issue("storage_command_empty", "Команда синхронизации", "fail", "QH_STORAGE_SYNC_CMD не должен быть пустым", "QH_STORAGE_SYNC_CMD"))
        if "{file}" not in command:
            issues.append(env_validation_issue("storage_command_file_marker", "Команда синхронизации", "fail", "QH_STORAGE_SYNC_CMD должен содержать маркер {file}", "QH_STORAGE_SYNC_CMD"))

    if require_json not in {"1", "true", "yes", "on"}:
        issues.append(env_validation_issue("storage_require_hook_json", "JSON-ответ хранилища", "fail", "Для production задайте QH_REQUIRE_HOOK_JSON=1", "QH_REQUIRE_HOOK_JSON"))

    deduped = list({str(item["id"]): item for item in issues}.values())
    blocking_issues = [item for item in deduped if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-storage-integration-validation-v1",
        "checked_at": utc_now(),
        "ready_for_storage_smoke": not blocking_issues,
        "storage_mode": mode if mode and not value_looks_placeholder(mode) else "",
        "storage_scheme": storage_url.split(":", 1)[0] if ":" in storage_url else "",
        "command_key": "QH_STORAGE_SYNC_CMD",
        "required_markers": ["{file}", "{doc_id}", "{filename}", "{storage_url}"],
        "allowed_hook_statuses": ["ok", "stored", "uploaded", "synced"],
        "issue_count": len(deduped),
        "blocking_issue_count": len(blocking_issues),
        "issues": deduped,
        "next_step": (
            "Запустите storage hook dry-run и загрузите тестовый документ с проверкой storage_synced_at."
            if not blocking_issues
            else "Заполните QH_STORAGE_MODE, QH_STORAGE_URL, QH_STORAGE_SYNC_CMD и включите QH_REQUIRE_HOOK_JSON=1."
        ),
    }


def validate_av_scanner_payload(raw: str) -> dict[str, Any]:
    values, issues = parse_env_text(raw)
    command = production_env_value(values, "QH_AV_SCANNER_CMD") or production_env_value(values, "QH_AV_SCANNER")
    command_key = "QH_AV_SCANNER_CMD" if production_env_value(values, "QH_AV_SCANNER_CMD") else "QH_AV_SCANNER"
    require_json = production_env_value(values, "QH_REQUIRE_HOOK_JSON").lower()

    if not command:
        issues.append(env_validation_issue("av_command_missing", "Команда AV-сканера", "missing", "Заполните QH_AV_SCANNER или QH_AV_SCANNER_CMD", "QH_AV_SCANNER"))
    elif value_looks_placeholder(command):
        issues.append(env_validation_issue("av_command_placeholder", "Команда AV-сканера", "missing", "Замените placeholder в команде AV-сканера", command_key))
    else:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
            issues.append(env_validation_issue("av_command_syntax", "Команда AV-сканера", "fail", "Команда AV-сканера должна быть корректной shell-like командой", command_key))
        if not parts:
            issues.append(env_validation_issue("av_command_empty", "Команда AV-сканера", "fail", "Команда AV-сканера не должна быть пустой", command_key))
        if "{file}" not in command:
            issues.append(env_validation_issue("av_command_file_marker", "Команда AV-сканера", "fail", "Команда AV-сканера должна содержать маркер {file}", command_key))

    if require_json not in {"1", "true", "yes", "on"}:
        issues.append(env_validation_issue("av_require_hook_json", "JSON-ответ AV", "fail", "Для production задайте QH_REQUIRE_HOOK_JSON=1", "QH_REQUIRE_HOOK_JSON"))

    deduped = list({str(item["id"]): item for item in issues}.values())
    blocking_issues = [item for item in deduped if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-av-scanner-validation-v1",
        "checked_at": utc_now(),
        "ready_for_av_smoke": not blocking_issues,
        "command_key": command_key,
        "required_markers": ["{file}"],
        "required_behavior": ["scan_before_store", "reject_nonzero_exit", "no_file_persist_on_reject"],
        "issue_count": len(deduped),
        "blocking_issue_count": len(blocking_issues),
        "issues": deduped,
        "next_step": (
            "Запустите AV hook dry-run и загрузите чистый/запрещенный тестовый файл, проверив отказ до сохранения."
            if not blocking_issues
            else "Заполните QH_AV_SCANNER или QH_AV_SCANNER_CMD с маркером {file} и включите QH_REQUIRE_HOOK_JSON=1."
        ),
    }


def validate_backup_schedule_payload(raw: str) -> dict[str, Any]:
    values, issues = parse_env_text(raw)
    minutes = production_env_value(values, "QH_BACKUP_INTERVAL_MINUTES")
    seconds = production_env_value(values, "QH_BACKUP_INTERVAL_SECONDS")
    schedule = production_env_value(values, "QH_BACKUP_SCHEDULE")
    on_start = production_env_value(values, "QH_BACKUP_ON_START").lower()
    max_age = production_env_value(values, "QH_BACKUP_MAX_AGE_HOURS")
    selected = seconds or minutes or schedule

    if not selected:
        issues.append(env_validation_issue("backup_schedule_missing", "Расписание бэкапов", "missing", "Заполните QH_BACKUP_INTERVAL_MINUTES, QH_BACKUP_INTERVAL_SECONDS или QH_BACKUP_SCHEDULE", "QH_BACKUP_INTERVAL_MINUTES"))
    elif seconds:
        try:
            if int(seconds) <= 0:
                raise ValueError
        except ValueError:
            issues.append(env_validation_issue("backup_schedule_seconds_invalid", "Расписание бэкапов", "fail", "QH_BACKUP_INTERVAL_SECONDS должен быть положительным числом", "QH_BACKUP_INTERVAL_SECONDS"))
    elif minutes:
        try:
            if int(minutes) <= 0:
                raise ValueError
        except ValueError:
            issues.append(env_validation_issue("backup_schedule_minutes_invalid", "Расписание бэкапов", "fail", "QH_BACKUP_INTERVAL_MINUTES должен быть положительным числом", "QH_BACKUP_INTERVAL_MINUTES"))
    else:
        try:
            backup_interval_seconds_from_env_text(schedule)
        except ValueError:
            issues.append(env_validation_issue("backup_schedule_format_invalid", "Расписание бэкапов", "fail", "QH_BACKUP_SCHEDULE должен быть hourly, daily или duration вроде 30m", "QH_BACKUP_SCHEDULE"))

    if on_start not in {"1", "true", "yes", "on"}:
        issues.append(env_validation_issue("backup_on_start_disabled", "Первый бэкап при старте", "fail", "Для production задайте QH_BACKUP_ON_START=1", "QH_BACKUP_ON_START"))
    if max_age:
        try:
            if float(max_age.replace(",", ".")) <= 0:
                raise ValueError
        except ValueError:
            issues.append(env_validation_issue("backup_max_age_invalid", "Порог свежести бэкапа", "fail", "QH_BACKUP_MAX_AGE_HOURS должен быть положительным числом", "QH_BACKUP_MAX_AGE_HOURS"))

    deduped = list({str(item["id"]): item for item in issues}.values())
    blocking_issues = [item for item in deduped if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-backup-schedule-validation-v1",
        "checked_at": utc_now(),
        "ready_for_backup_schedule": not blocking_issues,
        "schedule_source": "seconds" if seconds else "minutes" if minutes else "schedule" if schedule else "",
        "schedule_value": selected if selected and not value_looks_placeholder(selected) else "",
        "on_start": on_start in {"1", "true", "yes", "on"},
        "max_age_hours": max_age or "24",
        "issue_count": len(deduped),
        "blocking_issue_count": len(blocking_issues),
        "issues": deduped,
        "next_step": (
            "Запустите сервис и проверьте первый бэкап при старте, затем свежесть копии через /api/readiness."
            if not blocking_issues
            else "Настройте интервал бэкапов, QH_BACKUP_ON_START=1 и порог свежести."
        ),
    }


def backup_interval_seconds_from_env_text(raw: str) -> int:
    value = raw.strip().lower()
    if value in {"hourly", "hour"}:
        return 60 * 60
    if value in {"daily", "day"}:
        return 24 * 60 * 60
    match = re.match(r"^(\d+)\s*([smhd])$", value)
    if not match:
        raise ValueError("invalid backup schedule")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("invalid backup schedule")
    unit = match.group(2)
    return amount * {"s": 1, "m": 60, "h": 60 * 60, "d": 24 * 60 * 60}[unit]


def validate_backup_remote_payload(raw: str) -> dict[str, Any]:
    values, issues = parse_env_text(raw)
    remote_url = production_env_value(values, "QH_BACKUP_REMOTE_URL")
    command = production_env_value(values, "QH_BACKUP_REMOTE_CMD")
    require_json = production_env_value(values, "QH_REQUIRE_HOOK_JSON").lower()

    if not remote_url:
        issues.append(env_validation_issue("backup_remote_url_missing", "Удаленный backup URL", "missing", "Заполните QH_BACKUP_REMOTE_URL", "QH_BACKUP_REMOTE_URL"))
    elif value_looks_placeholder(remote_url):
        issues.append(env_validation_issue("backup_remote_url_placeholder", "Удаленный backup URL", "missing", "Замените placeholder в QH_BACKUP_REMOTE_URL", "QH_BACKUP_REMOTE_URL"))
    elif not re.match(r"^(s3|https|gs|azure|file)://", remote_url):
        issues.append(env_validation_issue("backup_remote_url_scheme", "Удаленный backup URL", "fail", "QH_BACKUP_REMOTE_URL должен начинаться с s3://, https://, gs://, azure:// или file://", "QH_BACKUP_REMOTE_URL"))

    if not command:
        issues.append(env_validation_issue("backup_remote_command_missing", "Команда удаленного backup", "missing", "Заполните QH_BACKUP_REMOTE_CMD", "QH_BACKUP_REMOTE_CMD"))
    elif value_looks_placeholder(command):
        issues.append(env_validation_issue("backup_remote_command_placeholder", "Команда удаленного backup", "missing", "Замените placeholder в QH_BACKUP_REMOTE_CMD", "QH_BACKUP_REMOTE_CMD"))
    else:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
            issues.append(env_validation_issue("backup_remote_command_syntax", "Команда удаленного backup", "fail", "QH_BACKUP_REMOTE_CMD должен быть корректной shell-like командой", "QH_BACKUP_REMOTE_CMD"))
        if not parts:
            issues.append(env_validation_issue("backup_remote_command_empty", "Команда удаленного backup", "fail", "QH_BACKUP_REMOTE_CMD не должен быть пустым", "QH_BACKUP_REMOTE_CMD"))
        for marker in ("{backup}", "{manifest}"):
            if marker not in command:
                issues.append(env_validation_issue(f"backup_remote_command_{marker.strip('{}')}_marker", "Команда удаленного backup", "fail", f"QH_BACKUP_REMOTE_CMD должен содержать маркер {marker}", "QH_BACKUP_REMOTE_CMD"))

    if require_json not in {"1", "true", "yes", "on"}:
        issues.append(env_validation_issue("backup_remote_require_hook_json", "JSON-ответ remote backup", "fail", "Для production задайте QH_REQUIRE_HOOK_JSON=1", "QH_REQUIRE_HOOK_JSON"))

    deduped = list({str(item["id"]): item for item in issues}.values())
    blocking_issues = [item for item in deduped if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-backup-remote-validation-v1",
        "checked_at": utc_now(),
        "ready_for_remote_backup_smoke": not blocking_issues,
        "remote_scheme": remote_url.split(":", 1)[0] if ":" in remote_url else "",
        "command_key": "QH_BACKUP_REMOTE_CMD",
        "required_markers": ["{backup}", "{manifest}", "{remote_url}"],
        "allowed_hook_statuses": ["ok", "stored", "uploaded", "synced"],
        "issue_count": len(deduped),
        "blocking_issue_count": len(blocking_issues),
        "issues": deduped,
        "next_step": (
            "Запустите remote backup hook dry-run и затем restore-drill из удаленной копии."
            if not blocking_issues
            else "Заполните QH_BACKUP_REMOTE_URL, QH_BACKUP_REMOTE_CMD и включите QH_REQUIRE_HOOK_JSON=1."
        ),
    }


def validate_cutover_legal_catalog(values: dict[str, str]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    verified_at = production_env_value(values, "QH_REFERENCE_VERIFIED_AT") or production_env_value(values, "QH_LEGAL_CATALOG_VERIFIED_AT")
    if not verified_at:
        issues.append(
            env_validation_issue(
                "legal_catalog_verified_at_missing",
                "Юридическая сверка справочника",
                "missing",
                "Заполните QH_REFERENCE_VERIFIED_AT после проверки перечня разрешений, госпошлин и штрафов.",
                "QH_REFERENCE_VERIFIED_AT",
            )
        )
    elif value_looks_placeholder(verified_at):
        issues.append(
            env_validation_issue(
                "legal_catalog_verified_at_placeholder",
                "Юридическая сверка справочника",
                "missing",
                "Замените placeholder в QH_REFERENCE_VERIFIED_AT на дату фактической сверки.",
                "QH_REFERENCE_VERIFIED_AT",
            )
        )
    else:
        try:
            datetime.strptime(verified_at, "%Y-%m-%d")
        except ValueError:
            issues.append(
                env_validation_issue(
                    "legal_catalog_verified_at_invalid",
                    "Юридическая сверка справочника",
                    "fail",
                    "QH_REFERENCE_VERIFIED_AT должен быть датой YYYY-MM-DD после сверки с официальными источниками.",
                    "QH_REFERENCE_VERIFIED_AT",
                )
            )
    blocking_issues = [item for item in issues if item.get("status") in {"missing", "fail"}]
    return {
        "format": "qurulush-legal-catalog-cutover-validation-v1",
        "checked_at": utc_now(),
        "ready_for_legal_catalog": not blocking_issues,
        "issue_count": len(issues),
        "blocking_issue_count": len(blocking_issues),
        "issues": issues,
        "next_step": (
            "Зафиксируйте дату юридической сверки справочника в production .env и приложите пакет сверки."
            if blocking_issues
            else "Каталог отмечен как сверенный; приложите Word-пакет юридической сверки к acceptance."
        ),
    }


def cutover_safe_issues(report: dict[str, Any], stage_id: str) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for item in report.get("issues", []):
        if not isinstance(item, dict):
            continue
        safe_item = {
            "id": str(item.get("id") or f"{stage_id}_issue"),
            "stage": stage_id,
            "title": str(item.get("title") or stage_id),
            "status": str(item.get("status") or "fail"),
            "detail": str(item.get("detail") or ""),
        }
        if item.get("key"):
            safe_item["key"] = str(item.get("key"))
        safe.append(safe_item)
    return safe


def cutover_stage(stage_id: str, title: str, ready: bool, report: dict[str, Any], next_step: str | None = None) -> dict[str, Any]:
    issues = cutover_safe_issues(report, stage_id)
    blocking_issues = [item for item in issues if item.get("status") in {"missing", "fail"}]
    warnings = [item for item in issues if item.get("status") == "warning"]
    status = "pass" if ready and not warnings else "warning" if ready else "fail"
    return {
        "id": stage_id,
        "title": title,
        "status": status,
        "ready": bool(ready),
        "blocking_issue_count": len(blocking_issues),
        "warning_issue_count": len(warnings),
        "issue_count": len(issues),
        "next_step": next_step or str(report.get("next_step") or ""),
    }


def validate_production_cutover_payload(
    raw: str,
    domain: str,
    public_url: str = "",
    port: int = 8781,
    active_emails: set[str] | None = None,
    probe_live: bool = False,
) -> dict[str, Any]:
    values, parse_issues = parse_env_text(raw)
    domain_report = validate_domain_https_payload(domain, public_url, port, probe_live)
    env_report = validate_production_env_text(raw)
    auth_report = validate_auth_cutover_payload(raw, active_emails)
    hook_report = validate_hook_contracts_payload(raw)
    sacc2_report = validate_sacc2_exchange_payload(raw)
    eds_report = validate_eds_integration_payload(raw)
    payment_report = validate_payment_gateway_payload(raw)
    storage_report = validate_storage_integration_payload(raw)
    av_report = validate_av_scanner_payload(raw)
    backup_schedule_report = validate_backup_schedule_payload(raw)
    backup_remote_report = validate_backup_remote_payload(raw)
    legal_report = validate_cutover_legal_catalog(values)

    if parse_issues:
        legal_report["issues"] = list({str(item["id"]): item for item in [*parse_issues, *legal_report.get("issues", [])]}.values())
        legal_report["issue_count"] = len(legal_report["issues"])
        legal_report["blocking_issue_count"] = sum(1 for item in legal_report["issues"] if item.get("status") in {"missing", "fail"})
        legal_report["ready_for_legal_catalog"] = legal_report["blocking_issue_count"] == 0

    domain_ready = bool(domain_report.get("ready_for_live_https") if probe_live else domain_report.get("ready_for_deployment_files"))
    stages = [
        cutover_stage("domain_https", "Домен и HTTPS", domain_ready, domain_report),
        cutover_stage("production_env", "Production .env", bool(env_report.get("ready")), env_report),
        cutover_stage("auth_cutover", "Боевые учетные записи", bool(auth_report.get("ready_for_cutover")), auth_report),
        cutover_stage("hook_contracts", "JSON-контракты hooks", bool(hook_report.get("ready_for_hook_smoke")), hook_report),
        cutover_stage("sacc2", "Интеграция sacc2 / ДГАСК", bool(sacc2_report.get("ready_for_sacc2_smoke")), sacc2_report),
        cutover_stage("eds", "ЭЦП / электронное подписание", bool(eds_report.get("ready_for_eds_smoke")), eds_report),
        cutover_stage("payments", "Платежи, госпошлины и штрафы", bool(payment_report.get("ready_for_payment_smoke")), payment_report),
        cutover_stage("storage", "Production-файловое хранилище", bool(storage_report.get("ready_for_storage_smoke")), storage_report),
        cutover_stage("av", "Антивирусная проверка файлов", bool(av_report.get("ready_for_av_smoke")), av_report),
        cutover_stage("backup_schedule", "Расписание бэкапов", bool(backup_schedule_report.get("ready_for_backup_schedule")), backup_schedule_report),
        cutover_stage("backup_remote", "Удаленное хранение бэкапов", bool(backup_remote_report.get("ready_for_remote_backup_smoke")), backup_remote_report),
        cutover_stage("legal_catalog", "Каталог разрешений, пошлин и штрафов", bool(legal_report.get("ready_for_legal_catalog")), legal_report),
    ]
    issues: list[dict[str, Any]] = []
    for stage, report in zip(
        stages,
        [
            domain_report,
            env_report,
            auth_report,
            hook_report,
            sacc2_report,
            eds_report,
            payment_report,
            storage_report,
            av_report,
            backup_schedule_report,
            backup_remote_report,
            legal_report,
        ],
    ):
        issues.extend(cutover_safe_issues(report, stage["id"]))

    if not probe_live:
        issues.append(
            {
                "id": "live_probe_not_run",
                "stage": "domain_https",
                "title": "Live DNS/TLS/headers",
                "status": "warning",
                "detail": "Live-проверка не запускалась; включите Live DNS/TLS/headers перед боевым cutover.",
                "key": "deploymentProbeLive",
            }
        )
        for stage in stages:
            if stage["id"] == "domain_https" and stage["status"] == "pass":
                stage["status"] = "warning"
                stage["warning_issue_count"] += 1
                stage["issue_count"] += 1

    blocking_issues = [item for item in issues if item.get("status") in {"missing", "fail"}]
    warning_issues = [item for item in issues if item.get("status") == "warning"]
    required_ready_count = sum(1 for item in stages if item["ready"])
    completion_percent = round(required_ready_count / len(stages) * 100) if stages else 100
    configuration_ready = not blocking_issues
    final_acceptance_ready = configuration_ready and not warning_issues
    next_stage = next((item for item in stages if not item["ready"]), None)
    next_warning = warning_issues[0] if warning_issues else None
    return {
        "format": "qurulush-production-cutover-validation-v1",
        "checked_at": utc_now(),
        "cutover_scope": "configuration_validation",
        "ready_for_production_cutover": configuration_ready,
        "configuration_ready": configuration_ready,
        "ready_for_final_acceptance": final_acceptance_ready,
        "final_acceptance_required": not final_acceptance_ready,
        "completion_percent": completion_percent,
        "required_ready_count": required_ready_count,
        "required_total": len(stages),
        "blocking_issue_count": len(blocking_issues),
        "warning_issue_count": len(warning_issues),
        "stage_count": len(stages),
        "stages": stages,
        "issues": list({str(item["stage"]) + ":" + str(item["id"]): item for item in issues}.values()),
        "live_probe_requested": bool(probe_live),
        "domain": domain.strip().lower(),
        "public_url": str(domain_report.get("public_url") or public_url),
        "next_step": (
            "Все обязательные gates закрыты. Запустите финальный go/no-go и production smoke на сервере."
            if final_acceptance_ready
            else f"Конфигурация заполнена, но перед финальной приемкой закройте предупреждение: {next_warning.get('title')}. {next_warning.get('detail')}"
            if configuration_ready and next_warning
            else f"Закройте блокер: {next_stage['title']}. {next_stage['next_step'] if next_stage else ''}"
        ),
    }


def replace_command_markers(command: list[str], replacements: dict[str, str]) -> list[str]:
    prepared: list[str] = []
    for part in command:
        value = part
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        prepared.append(value)
    return prepared


def bootstrap_admin_settings() -> dict[str, str] | None:
    values = {
        "email": os.environ.get("QH_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower(),
        "password": os.environ.get("QH_BOOTSTRAP_ADMIN_PASSWORD", "").strip(),
        "name": os.environ.get("QH_BOOTSTRAP_ADMIN_NAME", "").strip() or "Администратор компании",
        "role": os.environ.get("QH_BOOTSTRAP_ADMIN_ROLE", "").strip() or "ceo",
    }
    if not any(values[key] for key in ("email", "password")):
        return None
    if not values["email"] or not values["password"]:
        raise RuntimeError("QH_BOOTSTRAP_ADMIN_EMAIL and QH_BOOTSTRAP_ADMIN_PASSWORD must be provided together")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", values["email"]):
        raise RuntimeError("QH_BOOTSTRAP_ADMIN_EMAIL must be a valid email")
    if len(values["password"]) < 12:
        raise RuntimeError("QH_BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters")
    if values["role"] not in ROLE_PERMS:
        raise RuntimeError("QH_BOOTSTRAP_ADMIN_ROLE must match a known role id")
    return values


def ensure_team_account(conn: sqlite3.Connection, email: str, name: str, role_id: str) -> None:
    row = conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
    if not row:
        return
    state = public_state_payload()
    state.update(json.loads(row["payload"]))
    team = state.setdefault("team", [])
    role_title_value = role_title(role_id)
    existing = next((item for item in team if str(item.get("email", "")).lower() == email), None)
    if existing:
        existing.update({"name": name, "role": role_title_value, "active": True})
    else:
        team.insert(
            0,
            {
                "id": f"USR-{len(team) + 1}",
                "name": name,
                "email": email,
                "role": role_title_value,
                "access": "Bootstrap",
                "objects": "Все объекты",
                "object_ids": [],
                "last": "bootstrap",
            },
        )
    state.pop("users", None)
    conn.execute("UPDATE app_state SET payload = ?, updated_at = ? WHERE id = 1", (json.dumps(state, ensure_ascii=False), utc_now()))


def apply_bootstrap_users(conn: sqlite3.Connection) -> None:
    settings = bootstrap_admin_settings()
    disable_demo = env_truthy("QH_DISABLE_DEMO_USERS")
    if disable_demo and not settings:
        raise RuntimeError("QH_DISABLE_DEMO_USERS requires QH_BOOTSTRAP_ADMIN_EMAIL and QH_BOOTSTRAP_ADMIN_PASSWORD")
    if settings:
        salt, password_hash = hash_password(settings["password"])
        conn.execute(
            """
            INSERT INTO users (email, name, role, password_salt, password_hash, active, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(email) DO UPDATE SET
              name = excluded.name,
              role = excluded.role,
              password_salt = excluded.password_salt,
              password_hash = excluded.password_hash,
              active = 1
            """,
            (settings["email"], settings["name"], settings["role"], salt, password_hash, utc_now()),
        )
        ensure_team_account(conn, settings["email"], settings["name"], settings["role"])
    if disable_demo:
        seed_emails = [user["email"] for user in SEED["users"] if not settings or user["email"] != settings["email"]]
        conn.executemany("UPDATE users SET active = 0 WHERE email = ?", [(email,) for email in seed_emails])


def readiness_item(
    item_id: str,
    title: str,
    status: str,
    detail: str,
    production_required: bool = True,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "status": status,
        "detail": detail,
        "production_required": production_required,
    }


def command_executable_check(command: list[str] | None, missing_detail: str) -> tuple[bool, str]:
    if not command:
        return False, missing_detail
    executable = command[0]
    if any(marker in executable for marker in ("{file}", "{payload}", "{backup}", "{manifest}")):
        return False, f"Executable команды не должен быть placeholder: {executable}"
    if Path(executable).name != executable:
        candidate = Path(executable).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return True, f"Команда доступна: {executable}"
        if candidate.exists():
            return False, f"Команда не исполняется: {executable}"
        return False, f"Команда не найдена: {executable}"
    resolved = shutil.which(executable)
    if resolved:
        return True, f"Команда доступна: {resolved}"
    return False, f"Команда не найдена в PATH: {executable}"


def command_gate(command_getter: Any, missing_detail: str) -> tuple[bool, str]:
    try:
        return command_executable_check(command_getter(), missing_detail)
    except ApiError as exc:
        return False, exc.message


def readiness_report(db_path: Path, upload_root: Path, backup_root: Path, scheme: str, tls_error: str | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}

    try:
        active_emails: set[str] = set()
        bootstrap_email = os.environ.get("QH_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        integrity_ok, integrity_detail = sqlite_integrity_status(db_path)
        checks.append(
            readiness_item(
                "sqlite_integrity",
                "Целостность SQLite",
                "pass" if integrity_ok else "fail",
                integrity_detail,
            )
        )
        init_db(db_path)
        with open_db(db_path) as conn:
            revoke_expired_sessions(conn)
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            missing_tables = sorted(REQUIRED_TABLES - tables)
            users = conn.execute("SELECT email, password_salt, password_hash FROM users WHERE active = 1").fetchall()
            active_emails = {str(row["email"]) for row in users}
            state_row = conn.execute("SELECT payload FROM app_state WHERE id = 1").fetchone()
            schema_row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
            sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE revoked_at IS NULL").fetchone()[0]
            expired_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE expires_at < ? AND revoked_at IS NULL", (utc_ts(),)).fetchone()[0]
            backup_manifest_check, backup_manifest_detail, backup_manifest_counts = backup_manifest_status(backup_root, repair=True)
            backup_freshness_check, backup_freshness_detail, backup_freshness_counts = backup_freshness_status(backup_root)
            backups_count = len(list_sqlite_backups(backup_root))
        counts["users"] = len(users)
        counts["active_sessions"] = int(sessions)
        counts["expired_active_sessions"] = int(expired_sessions)
        counts["backups"] = backups_count
        counts["backup_manifests_total"] = int(backup_manifest_counts["total"])
        counts["backup_manifests_valid"] = int(backup_manifest_counts["valid"])
        counts["backup_manifests_repaired"] = int(backup_manifest_counts["repaired"])
        counts["backup_manifests_invalid"] = int(backup_manifest_counts["invalid"])
        counts["backup_max_age_hours"] = backup_freshness_counts["max_age_hours"]
        counts["backup_newest_age_seconds"] = backup_freshness_counts["newest_age_seconds"]
        counts["bootstrap_admin"] = 1 if bootstrap_email and bootstrap_email in active_emails else 0
        schema_version = str(schema_row["value"]) if schema_row else ""
        counts["schema_version"] = schema_version
        if state_row:
            try:
                state_payload = public_state_payload()
                state_payload.update(json.loads(state_row["payload"]))
                counts["objects"] = len(state_payload.get("objects", []))
                counts["requests"] = len(state_payload.get("requests", []))
                counts["tasks"] = len(state_payload.get("tasks", []))
                counts["reference_items"] = len(state_payload.get("reference", []))
                counts["documents"] = len(state_payload.get("documents", state_payload.get("docs", [])))
            except json.JSONDecodeError:
                counts["state_payload_error"] = "invalid json"
        if missing_tables:
            checks.append(readiness_item("db_schema", "Схема SQLite", "fail", "Нет таблиц: " + ", ".join(missing_tables)))
        else:
            checks.append(readiness_item("db_schema", "Схема SQLite", "pass", "Все обязательные таблицы созданы"))
        if schema_version == str(SCHEMA_VERSION):
            checks.append(readiness_item("schema_version", "Версия схемы SQLite", "pass", f"Текущая версия: {schema_version}"))
        else:
            checks.append(readiness_item("schema_version", "Версия схемы SQLite", "fail", f"Ожидалась версия {SCHEMA_VERSION}, текущая: {schema_version or 'не указана'}"))
        if state_row:
            checks.append(readiness_item("app_state", "Состояние платформы", "pass", "Основные данные сохранены в SQLite"))
        else:
            checks.append(readiness_item("app_state", "Состояние платформы", "fail", "Не найден payload app_state"))
        weak_hashes = [
            row["email"]
            for row in users
            if len(str(row["password_salt"])) != 32 or len(str(row["password_hash"])) != 64 or str(row["password_hash"]) == LOCAL_DEMO_PASSWORD
        ]
        if users and not weak_hashes:
            checks.append(readiness_item("password_storage", "Пароли пользователей", "pass", "Пароли хранятся как PBKDF2-хеши с солью"))
        else:
            checks.append(readiness_item("password_storage", "Пароли пользователей", "fail", "Найдены некорректные записи паролей"))
        if int(expired_sessions) == 0:
            checks.append(readiness_item("session_maintenance", "Обслуживание сессий", "pass", "Просроченных активных сессий нет"))
        else:
            checks.append(readiness_item("session_maintenance", "Обслуживание сессий", "fail", f"Просроченные активные сессии: {expired_sessions}"))
        checks.append(readiness_item("backup_manifests", "Manifest резервных копий", backup_manifest_check, backup_manifest_detail, backup_manifest_check != "warning"))
        checks.append(readiness_item("backup_freshness", "Свежесть резервной копии", backup_freshness_check, backup_freshness_detail, backup_freshness_check != "warning"))
    except Exception as exc:
        checks.append(readiness_item("sqlite", "SQLite", "fail", f"База недоступна: {exc}"))

    for item_id, title, folder in (
        ("uploads", "Хранилище документов", upload_root),
        ("backups", "Каталог резервных копий", backup_root),
    ):
        exists = folder.exists() and folder.is_dir()
        writable = os.access(folder, os.W_OK) if exists else False
        status = "pass" if exists and writable else "fail"
        detail = str(folder) if status == "pass" else f"Каталог недоступен для записи: {folder}"
        checks.append(readiness_item(item_id, title, status, detail))

    if counts.get("backups", 0):
        checks.append(readiness_item("manual_backup", "Резервная копия", "pass", f"Найдено копий: {counts['backups']}"))
    else:
        checks.append(readiness_item("manual_backup", "Резервная копия", "warning", "Создайте первый бэкап перед вводом данных", False))

    if tls_error:
        checks.append(readiness_item("https", "HTTPS", "fail", tls_error))
    else:
        checks.append(
            readiness_item(
                "https",
                "HTTPS",
                "pass" if scheme == "https" else "warning",
                "Сервер запущен в HTTPS-режиме" if scheme == "https" else "Для production нужен доменный TLS-сертификат",
            )
        )

    seed_emails = {user["email"] for user in SEED["users"]}
    active_seed_users = seed_emails.issubset(active_emails)
    checks.append(
        readiness_item(
            "corporate_auth",
            "Корпоративные учетные записи",
            "warning" if active_seed_users else "pass",
            "Демо-аккаунты нужно заменить перед боевым запуском" if active_seed_users else "Демо-аккаунты уже не выглядят как единственный контур входа",
        )
    )
    bootstrap_configured = bool(os.environ.get("QH_BOOTSTRAP_ADMIN_EMAIL", "").strip())
    checks.append(
        readiness_item(
            "bootstrap_admin",
            "Боевой администратор",
            "pass" if bootstrap_configured and counts.get("bootstrap_admin") else "warning",
            "Bootstrap-администратор активен" if bootstrap_configured and counts.get("bootstrap_admin") else "Для production задайте QH_BOOTSTRAP_ADMIN_EMAIL и QH_BOOTSTRAP_ADMIN_PASSWORD",
        )
    )
    suspicious_env = suspicious_production_env_values()
    checks.append(
        readiness_item(
            "production_env_values",
            "Production-переменные без placeholder",
            "pass" if not suspicious_env else "missing",
            "Placeholder-значения не найдены" if not suspicious_env else "Проверьте переменные: " + ", ".join(suspicious_env),
        )
    )
    checks.append(
        readiness_item(
            "hook_json_contracts",
            "JSON-контракты внешних hooks",
            "pass" if require_hook_json_contract() else "missing",
            "Включен QH_REQUIRE_HOOK_JSON=1" if require_hook_json_contract() else "Для production включите QH_REQUIRE_HOOK_JSON=1, чтобы hooks возвращали машинно-проверяемый JSON",
        )
    )

    backup_interval = backup_interval_seconds_from_env()
    backup_schedule_detail = f"Автобэкап каждые {backup_interval} сек." if backup_interval else "Нужно задать QH_BACKUP_INTERVAL_MINUTES или QH_BACKUP_SCHEDULE"
    storage_command_ready, storage_command_detail = command_gate(storage_sync_command, "Нужна QH_STORAGE_SYNC_CMD для внешней синхронизации документов")
    external_storage_ready = os.environ.get("QH_STORAGE_MODE", "").strip().lower() not in {"", "local"} and storage_command_ready
    sacc2_command_ready, sacc2_command_detail = command_gate(sacc2_sync_command, "Нужна QH_SACC2_SYNC_CMD")
    eds_command_ready, eds_command_detail = command_gate(eds_sign_command, "Нужна QH_EDS_SIGN_CMD")
    payment_command_ready, payment_command_detail = command_gate(payment_gateway_command, "Нужна QH_PAYMENT_GATEWAY_CMD")
    av_command_ready, av_command_detail = command_gate(av_scanner_command, "Нужен AV-сканер для проверки загружаемых документов до сохранения")
    backup_remote_ready, backup_remote_detail = command_gate(backup_remote_command, "Нужна QH_BACKUP_REMOTE_CMD для выгрузки копий вне сервера")
    sacc2_ready = bool(sacc2_api_url()) and sacc2_api_key_configured() and sacc2_command_ready
    eds_ready = env_present("QH_EDS_PROVIDER") and env_present("QH_EDS_API_URL") and eds_command_ready
    external_checks = [
        ("sacc2_api", "Интеграция sacc2 / ДГАСК", sacc2_ready, sacc2_command_detail if bool(sacc2_api_url()) and sacc2_api_key_configured() else "Нужны официальный API URL, ключ, QH_SACC2_SYNC_CMD и регламент статусов"),
        ("eds", "ЭЦП / электронное подписание", eds_ready, eds_command_detail if env_present("QH_EDS_PROVIDER") and env_present("QH_EDS_API_URL") else "Нужны QH_EDS_PROVIDER, QH_EDS_API_URL и QH_EDS_SIGN_CMD"),
        ("payments", "Платежный шлюз", payment_command_ready, payment_command_detail),
        ("object_storage", "Production-файловое хранилище", external_storage_ready, storage_command_detail if os.environ.get("QH_STORAGE_MODE", "").strip().lower() not in {"", "local"} else "Нужны QH_STORAGE_MODE и QH_STORAGE_SYNC_CMD для внешней синхронизации документов"),
        ("av_scan", "Антивирусная проверка файлов", av_command_ready, av_command_detail),
        ("backup_schedule", "Расписание бэкапов", backup_interval is not None, backup_schedule_detail),
        ("backup_remote", "Удаленное хранение бэкапов", backup_remote_ready, backup_remote_detail),
    ]
    for item_id, title, passed, missing_detail in external_checks:
        checks.append(readiness_item(item_id, title, "pass" if passed else "missing", "Настроено" if passed else missing_detail))

    reference_verified = env_present("QH_REFERENCE_VERIFIED_AT", "QH_LEGAL_CATALOG_VERIFIED_AT")
    checks.append(
        readiness_item(
            "reference_catalog",
            "Справочник требований",
            "pass" if reference_verified else "warning",
            "Справочник сверён с действующими НПА" if reference_verified else "Рабочий каталог есть, но перед production нужна юридическая сверка НПА, тарифов, форм и сроков",
        )
    )

    production_ready = all(not item["production_required"] or item["status"] == "pass" for item in checks)
    local_ready = all(item["status"] != "fail" for item in checks if item["id"] in {"sqlite_integrity", "db_schema", "schema_version", "app_state", "password_storage", "session_maintenance", "backup_manifests", "backup_freshness", "uploads", "backups"})
    return {
        "checked_at": utc_now(),
        "scheme": scheme,
        "local_ready": local_ready,
        "production_ready": production_ready,
        "counts": counts,
        "checks": checks,
    }


def acceptance_passport(db_path: Path, upload_root: Path, backup_root: Path, scheme: str, actor: str) -> dict[str, Any]:
    report = readiness_report(db_path, upload_root, backup_root, scheme)
    backups = list_sqlite_backups(backup_root)
    latest_backup: dict[str, Any] | None = backups[0] if backups else None
    backup_verification: dict[str, Any] | None = None
    backup_status = "warning"
    backup_detail = "Резервные копии ещё не созданы"
    if latest_backup:
        try:
            backup_verification = verify_backup_for_restore(backup_root, str(latest_backup["file"]))
            backup_status = "pass"
            backup_detail = f"Последняя копия проверена: {latest_backup['file']}"
        except Exception as exc:
            backup_status = "fail"
            backup_detail = f"Последняя копия не прошла проверку: {exc}"

    production_blocker_ids = [item["id"] for item in production_blockers(report)]
    local_acceptance = bool(report.get("local_ready")) and backup_status == "pass"
    production_acceptance = bool(report.get("production_ready")) and backup_status == "pass"
    return {
        "format": "qurulush-acceptance-passport-v1",
        "checked_at": utc_now(),
        "checked_by": actor,
        "scheme": scheme,
        "local_acceptance": local_acceptance,
        "production_acceptance": production_acceptance,
        "backup_status": backup_status,
        "backup_detail": backup_detail,
        "latest_backup": latest_backup,
        "backup_verification": backup_verification,
        "readiness": {
            "local_ready": report.get("local_ready"),
            "production_ready": report.get("production_ready"),
            "counts": report.get("counts", {}),
        },
        "production_blockers": production_blocker_ids,
        "summary": [
            {"id": "local_readiness", "status": "pass" if report.get("local_ready") else "fail", "detail": "Локальный контур готов" if report.get("local_ready") else "Есть ошибки локального контура"},
            {"id": "backup_verify", "status": backup_status, "detail": backup_detail},
            {"id": "production_readiness", "status": "pass" if report.get("production_ready") else "warning", "detail": "Production-гейты закрыты" if report.get("production_ready") else "Остались production-гейты: " + (", ".join(production_blocker_ids) or "нет")},
        ],
    }


def production_blockers(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in report.get("checks", [])
        if item.get("production_required") and item.get("status") != "pass"
    ]


def production_blocker_message(report: dict[str, Any]) -> str:
    blockers = production_blockers(report)
    if not blockers:
        return ""
    details = [f"{item.get('id')}: {item.get('detail')}" for item in blockers]
    return "Production readiness failed: " + "; ".join(details)


def production_preflight_scheme(tls_cert: Path | None, tls_key: Path | None) -> tuple[str, str | None]:
    if not tls_cert and not tls_key:
        return "http", None
    if not tls_cert or not tls_key:
        return "http", "tls_cert and tls_key must be provided together"
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(tls_cert), str(tls_key))
    except Exception as exc:
        return "http", f"TLS-сертификат или ключ не читается: {exc}"
    return "https", None


def format_readiness_report(report: dict[str, Any]) -> str:
    labels = {"pass": "OK", "warning": "WARN", "missing": "MISSING", "fail": "FAIL"}
    counts = report.get("counts", {})
    count_parts = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
    lines = [
        "Qurulush Hub production preflight",
        f"checked_at: {report.get('checked_at')}",
        f"scheme: {report.get('scheme')}",
        f"local_ready: {'yes' if report.get('local_ready') else 'no'}",
        f"production_ready: {'yes' if report.get('production_ready') else 'no'}",
        f"counts: {count_parts}",
        "checks:",
    ]
    for item in report.get("checks", []):
        label = labels.get(str(item.get("status")), str(item.get("status", "")).upper())
        required = " required" if item.get("production_required") else ""
        lines.append(f"- [{label}{required}] {item.get('title')} ({item.get('id')}): {item.get('detail')}")
    blockers = production_blockers(report)
    if blockers:
        lines.append("production_blockers:")
        for item in blockers:
            lines.append(f"- {item.get('id')}: {item.get('detail')}")
    else:
        lines.append("production_blockers: none")
    return "\n".join(lines)


def run_preflight(
    db_path: Path,
    upload_root: Path,
    backup_root: Path,
    tls_cert: Path | None = None,
    tls_key: Path | None = None,
    require_production: bool = False,
    json_output: bool = False,
) -> int:
    init_db(db_path)
    upload_root.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    scheme, tls_error = production_preflight_scheme(tls_cert, tls_key)
    report = readiness_report(db_path, upload_root, backup_root, scheme, tls_error)
    if json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_readiness_report(report))
    if require_production:
        message = production_blocker_message(report)
        if message:
            print(message, file=sys.stderr)
            return 2
    return 0


def health_payload(db_path: Path, scheme: str) -> dict[str, Any]:
    db_ready = False
    try:
        init_db(db_path)
        with open_db(db_path) as conn:
            conn.execute("SELECT 1")
        db_ready = True
    except Exception:
        db_ready = False
    return {
        "ok": db_ready,
        "scheme": scheme,
        "storage": "sqlite",
        "db_ready": db_ready,
        "time": utc_now(),
    }


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(SimpleHTTPRequestHandler):
    server_version = "QurulushCompanyPlatform/1.0"
    security_headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'",
    }

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        if parsed == "/":
            parsed = "/index.html"
        parsed = unquote(parsed).lstrip("/")
        target = (WEB_ROOT / parsed).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            return str((WEB_ROOT / "__not_found__").resolve())
        return str(target)

    def log_message(self, fmt: str, *args: Any) -> None:
        if not getattr(self.server, "quiet", False):
            super().log_message(fmt, *args)

    def end_headers(self) -> None:
        for name, value in self.security_headers.items():
            self.send_header(name, value)
        if getattr(self.server, "scheme", "http") == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        super().end_headers()

    @property
    def db_path(self) -> Path:
        return self.server.db_path  # type: ignore[attr-defined]

    @property
    def upload_root(self) -> Path:
        return self.server.upload_root  # type: ignore[attr-defined]

    @property
    def backup_root(self) -> Path:
        return self.server.backup_root  # type: ignore[attr-defined]

    def send_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json_dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_local_file(self, path: Path, download_name: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "file not found")
        body = path.read_bytes()
        filename = safe_filename(download_name or path.name)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename.encode("ascii", "ignore").decode("ascii") or "document"}"')
        self.end_headers()
        self.wfile.write(body)

    def send_download(self, body: bytes, filename: str, content_type: str) -> None:
        cleaned = safe_filename(filename)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{cleaned.encode("ascii", "ignore").decode("ascii") or "download"}"')
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid Content-Length") from exc
        if length > max_json_body_bytes():
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "JSON payload is too large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid JSON") from exc
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON object expected")
        return data

    def current_user(self) -> dict[str, Any]:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise ApiError(HTTPStatus.UNAUTHORIZED, "missing bearer token")
        token = auth.removeprefix("Bearer ").strip()
        if not token:
            raise ApiError(HTTPStatus.UNAUTHORIZED, "invalid token")
        token_digest = hash_token(token)
        with open_db(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT users.email, users.name, users.role, sessions.expires_at
                FROM sessions
                JOIN users ON users.email = sessions.email
                WHERE sessions.token_hash = ?
                  AND sessions.revoked_at IS NULL
                  AND users.active = 1
                """,
                (token_digest,),
            ).fetchone()
        if not row:
            raise ApiError(HTTPStatus.UNAUTHORIZED, "invalid token")
        if float(row["expires_at"]) < utc_ts():
            with open_db(self.db_path) as conn:
                revoke_expired_sessions(conn)
            raise ApiError(HTTPStatus.UNAUTHORIZED, "token expired")
        return {"email": row["email"], "name": row["name"], "role": row["role"]}

    def current_token_hash(self) -> str:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise ApiError(HTTPStatus.UNAUTHORIZED, "missing bearer token")
        token = auth.removeprefix("Bearer ").strip()
        if not token:
            raise ApiError(HTTPStatus.UNAUTHORIZED, "invalid token")
        return hash_token(token)

    def require(self, perm: str) -> dict[str, Any]:
        user = self.current_user()
        if not has_perm(user, perm):
            raise ApiError(HTTPStatus.FORBIDDEN, f"permission required: {perm}")
        return user

    def route_get(self, path: str) -> bool:
        if path == "/api/health":
            self.send_json(HTTPStatus.OK, health_payload(self.db_path, getattr(self.server, "scheme", "http")))
            return True
        if path == "/api/state":
            user = self.current_user()
            state = load_state(self.db_path)
            safe = filter_state_for_user(state, user)
            safe["docs"] = safe.get("documents", safe.get("docs", []))
            self.send_json(HTTPStatus.OK, {"ok": True, "user": user, "data": safe})
            return True
        if path == "/api/calendar":
            user = self.current_user()
            state = load_state(self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": calendar_payload(state, user)})
            return True
        if path == "/api/chat":
            user = self.current_user()
            state = load_state(self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": chat_payload(state, user)})
            return True
        if path == "/api/access/matrix":
            user = self.require("all")
            state = load_state(self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": access_matrix_payload(state, user["name"])})
            return True
        if path == "/api/access/matrix.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            self.send_download(
                build_access_matrix_docx(access_matrix_payload(state, user["name"])),
                "qurulush-company-access-matrix.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/readiness":
            user = self.require("all")
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            report["checked_by"] = user["name"]
            self.send_json(HTTPStatus.OK, {"ok": True, "data": report})
            return True
        if path == "/api/external/sacc2-status":
            user = self.require("all")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": sacc2_public_status_payload(user["name"])})
            return True
        if path == "/api/external/sacc2-status.docx":
            user = self.require("all")
            self.send_download(
                build_sacc2_public_status_docx(sacc2_public_status_payload(user["name"])),
                "qurulush-sacc2-public-status.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/acceptance/passport":
            user = self.require("all")
            passport = acceptance_passport(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"), user["name"])
            self.send_json(HTTPStatus.OK, {"ok": True, "data": passport})
            return True
        if path == "/api/acceptance/passport.docx":
            user = self.require("all")
            passport = acceptance_passport(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"), user["name"])
            self.send_download(
                build_acceptance_passport_docx(passport),
                "qurulush-acceptance-passport.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/acceptance/evidence":
            user = self.require("all")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": latest_acceptance_evidence_payload(user["name"])})
            return True
        if path == "/api/acceptance/evidence.json":
            user = self.require("all")
            payload = latest_acceptance_evidence_payload(user["name"])
            self.send_download(
                json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                "qurulush-acceptance-evidence-current.json",
                "application/json; charset=utf-8",
            )
            return True
        if path == "/api/acceptance/completion-audit":
            user = self.require("all")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": latest_completion_audit_payload(user["name"])})
            return True
        if path == "/api/acceptance/completion-audit.json":
            user = self.require("all")
            payload = latest_completion_audit_payload(user["name"])
            self.send_download(
                json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                "qurulush-completion-audit-current.json",
                "application/json; charset=utf-8",
            )
            return True
        if path == "/api/production/plan":
            user = self.require("all")
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_connection_plan(report)})
            return True
        if path == "/api/production/future-roadmap":
            user = self.require("all")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": future_roadmap_payload(user["name"])})
            return True
        if path == "/api/production/qa-evidence":
            user = self.require("all")
            state = load_state(self.db_path)
            scheme = getattr(self.server, "scheme", "http")
            host = re.sub(r"[^A-Za-z0-9.:\-\[\]]", "", self.headers.get("Host", "127.0.0.1:8782").strip()) or "127.0.0.1:8782"
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, scheme)
            passport = acceptance_passport(self.db_path, self.upload_root, self.backup_root, scheme, user["name"])
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_qa_evidence_payload(state, report, passport, user["name"], f"{scheme}://{host}/")})
            return True
        if path == "/api/production/qa-evidence.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            scheme = getattr(self.server, "scheme", "http")
            host = re.sub(r"[^A-Za-z0-9.:\-\[\]]", "", self.headers.get("Host", "127.0.0.1:8782").strip()) or "127.0.0.1:8782"
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, scheme)
            passport = acceptance_passport(self.db_path, self.upload_root, self.backup_root, scheme, user["name"])
            self.send_download(
                build_production_qa_evidence_docx(production_qa_evidence_payload(state, report, passport, user["name"], f"{scheme}://{host}/")),
                "qurulush-qa-evidence.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/status-board":
            user = self.require("all")
            state = load_state(self.db_path)
            scheme = getattr(self.server, "scheme", "http")
            host = re.sub(r"[^A-Za-z0-9.:\-\[\]]", "", self.headers.get("Host", "127.0.0.1:8782").strip()) or "127.0.0.1:8782"
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, scheme)
            passport = acceptance_passport(self.db_path, self.upload_root, self.backup_root, scheme, user["name"])
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_status_board_payload(state, report, passport, user["name"], f"{scheme}://{host}/")})
            return True
        if path == "/api/production/status-board.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            scheme = getattr(self.server, "scheme", "http")
            host = re.sub(r"[^A-Za-z0-9.:\-\[\]]", "", self.headers.get("Host", "127.0.0.1:8782").strip()) or "127.0.0.1:8782"
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, scheme)
            passport = acceptance_passport(self.db_path, self.upload_root, self.backup_root, scheme, user["name"])
            self.send_download(
                build_production_status_board_docx(production_status_board_payload(state, report, passport, user["name"], f"{scheme}://{host}/")),
                "qurulush-production-status-board.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/evidence":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_evidence_payload(state, report, user["name"])})
            return True
        if path == "/api/production/evidence.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_download(
                build_production_evidence_docx(production_evidence_payload(state, report, user["name"])),
                "qurulush-production-evidence-register.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/request-pack":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_request_pack_payload(state, report, user["name"])})
            return True
        if path == "/api/production/request-pack.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_download(
                build_production_request_pack_docx(production_request_pack_payload(state, report, user["name"])),
                "qurulush-production-request-pack.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/official-letters":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_official_letters_payload(state, report, user["name"])})
            return True
        if path == "/api/production/official-letters.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_download(
                build_production_official_letters_docx(production_official_letters_payload(state, report, user["name"])),
                "qurulush-production-official-letters.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/action-board":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_action_board_payload(state, report, user["name"])})
            return True
        if path == "/api/production/action-board.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_download(
                build_production_action_board_docx(production_action_board_payload(state, report, user["name"])),
                "qurulush-production-action-board.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/launch-sequence":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_launch_sequence_payload(state, report, user["name"])})
            return True
        if path == "/api/production/launch-sequence.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_download(
                build_production_launch_sequence_docx(production_launch_sequence_payload(state, report, user["name"])),
                "qurulush-production-launch-sequence.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/remaining-work":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_remaining_work_payload(state, report, user["name"])})
            return True
        if path == "/api/production/remaining-work.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_download(
                build_production_remaining_work_docx(production_remaining_work_payload(state, report, user["name"])),
                "qurulush-production-remaining-work.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/top-actions":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_top_actions_payload(state, report, user["name"])})
            return True
        if path == "/api/production/top-actions.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_download(
                build_production_top_actions_docx(production_top_actions_payload(state, report, user["name"])),
                "qurulush-production-top-actions.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/alerts":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_alerts_payload(state, report, user["name"])})
            return True
        if path == "/api/production/account-cutover":
            user = self.require("all")
            state = load_state(self.db_path)
            with open_db(self.db_path) as conn:
                payload = production_account_cutover_payload(conn, state, user["name"])
            self.send_json(HTTPStatus.OK, {"ok": True, "data": payload})
            return True
        if path == "/api/production/account-cutover.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            with open_db(self.db_path) as conn:
                payload = production_account_cutover_payload(conn, state, user["name"])
            self.send_download(
                build_production_account_cutover_docx(payload),
                "qurulush-production-account-cutover.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/plan.docx":
            self.require("all")
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_download(
                build_production_plan_docx(production_connection_plan(report)),
                "qurulush-production-plan.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/env.example":
            self.require("all")
            self.send_download(
                production_env_template_bytes(),
                "company-platform.env.example",
                "text/plain; charset=utf-8",
            )
            return True
        if path == "/api/interaction/map":
            user = self.require("all")
            state = load_state(self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": interaction_map_payload(state, user["name"])})
            return True
        if path == "/api/interaction/map.docx":
            user = self.require("all")
            state = load_state(self.db_path)
            self.send_download(
                build_interaction_map_docx(interaction_map_payload(state, user["name"])),
                "qurulush-dgask-interaction-map.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/production/launch-bundle.zip":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            passport = acceptance_passport(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"), user["name"])
            with open_db(self.db_path) as conn:
                account_cutover = production_account_cutover_payload(conn, state, user["name"])
            scheme = getattr(self.server, "scheme", "http")
            host = re.sub(r"[^A-Za-z0-9.:\-\[\]]", "", self.headers.get("Host", "127.0.0.1:8782").strip()) or "127.0.0.1:8782"
            self.send_download(
                build_production_launch_bundle(state, report, passport, user["name"], account_cutover, f"{scheme}://{host}/"),
                "qurulush-production-launch-bundle.zip",
                "application/zip",
            )
            return True
        if path == "/api/production/checklist":
            self.require("all")
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": production_launch_checklist(report)})
            return True
        if path == "/api/production/checklist.docx":
            self.require("all")
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            self.send_download(
                build_production_launch_checklist_docx(production_launch_checklist(report)),
                "qurulush-production-launch-checklist.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/sessions":
            self.require("all")
            current_digest = self.current_token_hash()
            with open_db(self.db_path) as conn:
                payload = session_control_payload(conn, current_digest)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": payload})
            return True
        if path == "/api/exchange/export":
            user = self.require("all")
            state = load_state(self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": exchange_export_payload(state, user["name"])})
            return True
        if path == "/api/audit/export":
            user = self.require("all")
            state = load_state(self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": audit_export_payload(state, user["name"])})
            return True
        if path == "/api/reference/export":
            user = self.current_user()
            state = load_state(self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": reference_export_payload(state, user["name"])})
            return True
        if path == "/api/reference/export.docx":
            user = self.current_user()
            state = load_state(self.db_path)
            payload = reference_export_payload(state, user["name"])
            self.send_download(
                build_reference_docx(payload),
                "qurulush-reference-catalog.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/legal/verification-packet":
            user = self.current_user()
            if not has_perm(user, "legal:verify"):
                raise ApiError(HTTPStatus.FORBIDDEN, "Недостаточно прав для юридической сверки")
            state = load_state(self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": legal_verification_packet_payload(state, user["name"])})
            return True
        if path == "/api/legal/verification-packet.docx":
            user = self.current_user()
            if not has_perm(user, "legal:verify"):
                raise ApiError(HTTPStatus.FORBIDDEN, "Недостаточно прав для юридической сверки")
            state = load_state(self.db_path)
            packet = legal_verification_packet_payload(state, user["name"])
            self.send_download(
                build_legal_verification_packet_docx(packet),
                "qurulush-legal-verification-packet.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True
        if path == "/api/backups":
            self.require("all")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": list_sqlite_backups(self.backup_root)})
            return True
        if path.startswith("/api/documents/") and path.endswith("/file"):
            user = self.require("documents:read")
            doc_id = unquote(path.split("/")[3])
            state = load_state(self.db_path)
            doc = find_item(state["documents"], doc_id)
            if not doc or not doc.get("stored_file"):
                raise ApiError(HTTPStatus.NOT_FOUND, "document file not found")
            require_object_access(state, user, doc.get("object"))
            stored_name = safe_filename(str(doc["stored_file"]))
            target = (self.upload_root / stored_name).resolve()
            if self.upload_root.resolve() not in target.parents:
                raise ApiError(HTTPStatus.BAD_REQUEST, "invalid upload path")
            self.send_local_file(target, str(doc.get("file") or stored_name))
            return True
        return False

    def route_post(self, path: str) -> bool:
        data = self.read_json()
        if path == "/api/auth/login":
            email = str(data.get("email", "")).strip().lower()
            password = str(data.get("password", ""))
            login_error: ApiError | None = None
            with open_db(self.db_path) as conn:
                ensure_login_not_locked(conn, email)
                row = conn.execute(
                    "SELECT email, name, role, password_salt, password_hash FROM users WHERE email = ? AND active = 1",
                    (email,),
                ).fetchone()
                if not row or not verify_password(password, row["password_salt"], row["password_hash"]):
                    locked = record_failed_login(conn, email)
                    status = HTTPStatus.TOO_MANY_REQUESTS if locked else HTTPStatus.UNAUTHORIZED
                    message = "too many login attempts; try later" if locked else "wrong email or password"
                    login_error = ApiError(status, message)
                    user = None
                    token = ""
                    expires_at = 0.0
                else:
                    clear_login_attempts(conn, email)
                    user = {"email": row["email"], "name": row["name"], "role": row["role"]}
                    token = secrets.token_urlsafe(24)
                    expires_at = utc_ts() + SESSION_SECONDS
                    revoke_expired_sessions(conn)
                    conn.execute(
                        """
                        INSERT INTO sessions (token_hash, email, expires_at, created_at, revoked_at)
                        VALUES (?, ?, ?, ?, NULL)
                        """,
                        (hash_token(token), user["email"], expires_at, utc_now()),
                    )
            if login_error:
                raise login_error
            self.send_json(HTTPStatus.OK, {"ok": True, "token": token, "user": user, "expires_at": expires_at})
            return True

        if path == "/api/auth/logout":
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth.removeprefix("Bearer ").strip()
                if token:
                    with open_db(self.db_path) as conn:
                        conn.execute("UPDATE sessions SET revoked_at = ? WHERE token_hash = ?", (utc_now(), hash_token(token)))
            self.send_json(HTTPStatus.OK, {"ok": True})
            return True

        if path == "/api/auth/change-password":
            user = self.current_user()
            current_password = str(data.get("currentPassword", ""))
            new_password = str(data.get("newPassword", ""))
            if len(new_password) < 8:
                raise ApiError(HTTPStatus.BAD_REQUEST, "new password must be at least 8 characters")
            if current_password == new_password:
                raise ApiError(HTTPStatus.BAD_REQUEST, "new password must be different")
            with open_db(self.db_path) as conn:
                row = conn.execute(
                    "SELECT password_salt, password_hash FROM users WHERE email = ? AND active = 1",
                    (user["email"],),
                ).fetchone()
                if not row or not verify_password(current_password, row["password_salt"], row["password_hash"]):
                    raise ApiError(HTTPStatus.UNAUTHORIZED, "current password is wrong")
                salt, password_hash = hash_password(new_password)
                conn.execute(
                    "UPDATE users SET password_salt = ?, password_hash = ? WHERE email = ?",
                    (salt, password_hash, user["email"]),
                )
                conn.execute(
                    """
                    UPDATE sessions
                    SET revoked_at = ?
                    WHERE email = ? AND token_hash != ? AND revoked_at IS NULL
                    """,
                    (utc_now(), user["email"], self.current_token_hash()),
                )
            self.send_json(HTTPStatus.OK, {"ok": True, "data": {"email": user["email"], "changed_at": utc_now()}})
            return True

        if path == "/api/production/deployment-files.zip":
            user = self.require("all")
            domain = str(data.get("domain", "")).strip()
            admin_email = str(data.get("admin_email") or data.get("adminEmail") or user["email"]).strip()
            port_value = data.get("port", 8781)
            try:
                port = int(port_value)
            except (TypeError, ValueError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "port must be a number") from exc
            self.send_download(
                build_deployment_files_bundle(domain=domain, admin_email=admin_email, port=port),
                "qurulush-deployment-files.zip",
                "application/zip",
            )
            return True

        if path == "/api/production/domain/validate":
            self.require("all")
            domain = str(data.get("domain", "")).strip()
            public_url = str(data.get("public_url") or data.get("publicUrl") or "").strip()
            port_value = data.get("port", 8781)
            try:
                port = int(port_value)
            except (TypeError, ValueError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "port must be a number") from exc
            probe_live = bool(data.get("probe_live") or data.get("probeLive"))
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_domain_https_payload(domain, public_url, port, probe_live)})
            return True

        if path == "/api/production/env/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_production_env_text(env_text)})
            return True

        if path == "/api/production/auth-cutover/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            with open_db(self.db_path) as conn:
                active_emails = {str(row["email"]).lower() for row in conn.execute("SELECT email FROM users WHERE active = 1").fetchall()}
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_auth_cutover_payload(env_text, active_emails)})
            return True

        if path == "/api/production/hooks/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_hook_contracts_payload(env_text)})
            return True

        if path == "/api/production/sacc2/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_sacc2_exchange_payload(env_text)})
            return True

        if path == "/api/production/eds/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_eds_integration_payload(env_text)})
            return True

        if path == "/api/production/payments/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_payment_gateway_payload(env_text)})
            return True

        if path == "/api/production/storage/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_storage_integration_payload(env_text)})
            return True

        if path == "/api/production/av/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_av_scanner_payload(env_text)})
            return True

        if path == "/api/production/backups/schedule/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_backup_schedule_payload(env_text)})
            return True

        if path == "/api/production/backups/remote/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            self.send_json(HTTPStatus.OK, {"ok": True, "data": validate_backup_remote_payload(env_text)})
            return True

        if path == "/api/production/cutover/validate":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            domain = str(data.get("domain", "")).strip()
            public_url = str(data.get("public_url") or data.get("publicUrl") or "").strip()
            port_value = data.get("port", 8781)
            try:
                port = int(port_value)
            except (TypeError, ValueError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "port must be a number") from exc
            probe_live = bool(data.get("probe_live") or data.get("probeLive"))
            with open_db(self.db_path) as conn:
                active_emails = {str(row["email"]).lower() for row in conn.execute("SELECT email FROM users WHERE active = 1").fetchall()}
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "data": validate_production_cutover_payload(env_text, domain, public_url, port, active_emails, probe_live),
                },
            )
            return True

        if path == "/api/production/cutover.docx":
            self.require("all")
            env_text = str(data.get("env_text") or data.get("envText") or "")
            domain = str(data.get("domain", "")).strip()
            public_url = str(data.get("public_url") or data.get("publicUrl") or "").strip()
            port_value = data.get("port", 8781)
            try:
                port = int(port_value)
            except (TypeError, ValueError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "port must be a number") from exc
            probe_live = bool(data.get("probe_live") or data.get("probeLive"))
            with open_db(self.db_path) as conn:
                active_emails = {str(row["email"]).lower() for row in conn.execute("SELECT email FROM users WHERE active = 1").fetchall()}
            report = validate_production_cutover_payload(env_text, domain, public_url, port, active_emails, probe_live)
            self.send_download(
                build_production_cutover_docx(report),
                "qurulush-production-cutover-report.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return True

        if path == "/api/production/evidence":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            payload = update_production_evidence(state, data, report, user)
            gate = next((item for item in payload.get("items", []) if item.get("id") == clean_evidence_text(data.get("id") or data.get("gate_id") or data.get("gateId"), 80)), {})
            self.add_audit(state, user["name"], f"Обновлен production evidence: {gate.get('title', data.get('id', '-'))}", None)
            self.add_notification(state, "Production", "Evidence-регистр обновлен", f"{gate.get('title', data.get('id', '-'))}: {gate.get('evidence_label', '-')}")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": payload})
            return True

        if path == "/api/production/request-pack/tracker":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            payload = update_production_request_tracker(state, data, report, user)
            gate_id = clean_evidence_text(data.get("id") or data.get("gate_id") or data.get("gateId"), 80)
            gate = next((item for item in payload.get("request_pack", {}).get("items", []) if item.get("id") == gate_id), {})
            self.add_audit(state, user["name"], f"Обновлен production request tracker: {gate.get('title', gate_id)}", None)
            self.add_notification(state, "Production", "Request-pack обновлен", f"{gate.get('title', gate_id)}: {gate.get('tracker_label', '-')}")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": payload})
            return True

        if path == "/api/production/alerts/generate":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            payload = generate_production_alert_notifications(state, report, user["name"])
            self.add_audit(state, user["name"], f"Сформированы production alerts: {payload.get('created_count', 0)}", None)
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": payload, "notifications": state.get("notifications", [])})
            return True

        if path == "/api/external/sacc2-status/attach":
            user = self.require("all")
            state = load_state(self.db_path)
            report = readiness_report(self.db_path, self.upload_root, self.backup_root, getattr(self.server, "scheme", "http"))
            payload = attach_sacc2_public_status_to_launch(state, report, user)
            self.add_audit(state, user["name"], "Статус sacc2 зафиксирован в request-pack/evidence", None)
            self.add_notification(state, "Production", "Статус sacc2 зафиксирован", payload.get("tracker_label", payload.get("tracker_status", "-")))
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": payload})
            return True

        if path == "/api/sessions/revoke-expired":
            self.require("all")
            current_digest = self.current_token_hash()
            with open_db(self.db_path) as conn:
                revoked = revoke_expired_sessions(conn)
                payload = session_control_payload(conn, current_digest)
                payload["revoked_count"] = revoked
            self.send_json(HTTPStatus.OK, {"ok": True, "data": payload})
            return True

        if path == "/api/sessions/revoke-others":
            self.require("all")
            current_digest = self.current_token_hash()
            with open_db(self.db_path) as conn:
                revoked = revoke_other_sessions(conn, current_digest)
                payload = session_control_payload(conn, current_digest)
                payload["revoked_count"] = revoked
            self.send_json(HTTPStatus.OK, {"ok": True, "data": payload})
            return True

        if path == "/api/state/reset":
            self.require("all")
            save_state(public_state_payload(), self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": "reset"})
            return True

        if path == "/api/chat":
            user = self.current_user()
            message = str(data.get("message", "")).strip()
            if not message:
                raise ApiError(HTTPStatus.BAD_REQUEST, "message is required")
            if len(message) > 1200:
                raise ApiError(HTTPStatus.BAD_REQUEST, "message is too long")
            obj_raw = data.get("object")
            obj: int | None = None
            if obj_raw is not None and obj_raw != "":
                try:
                    obj = int(obj_raw)
                except (TypeError, ValueError) as exc:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "object must be a number") from exc
            state = load_state(self.db_path)
            if obj is not None:
                if not object_exists(state, obj):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "object not found")
                require_object_access(state, user, obj)
            messages = state.setdefault("chat_messages", [])
            user_message = {
                "id": f"CHAT-{len(messages) + 1}",
                "time": utc_now(),
                "author": user["name"],
                "role": role_title(user["role"]),
                "type": "user",
                "object": obj,
                "text": message,
            }
            assistant_text = ai_assistant_reply(state, user, message)
            assistant_message = {
                "id": f"CHAT-{len(messages) + 2}",
                "time": utc_now(),
                "author": "Qurulush AI",
                "role": "ИИ-помощник",
                "type": "assistant",
                "object": obj,
                "text": assistant_text,
            }
            messages.extend([user_message, assistant_message])
            del messages[:-120]
            self.add_audit(state, user["name"], "Сообщение во внутреннем чате с ИИ", obj)
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.CREATED, {"ok": True, "data": chat_payload(state, user), "assistant": assistant_message})
            return True

        if path == "/api/backups":
            user = self.require("all")
            backup = create_sqlite_backup(self.db_path, self.backup_root, user["name"])
            self.send_json(HTTPStatus.CREATED, {"ok": True, "data": backup})
            return True

        if path == "/api/backups/restore":
            user = self.require("all")
            file_name = str(data.get("file", "")).strip()
            if not file_name:
                raise ApiError(HTTPStatus.BAD_REQUEST, "backup file is required")
            result = restore_app_state_from_backup(self.db_path, self.backup_root, file_name, user["name"])
            self.send_json(HTTPStatus.OK, {"ok": True, "data": result})
            return True

        if path == "/api/backups/verify":
            self.require("all")
            file_name = str(data.get("file", "")).strip()
            if not file_name:
                raise ApiError(HTTPStatus.BAD_REQUEST, "backup file is required")
            result = verify_backup_for_restore(self.backup_root, file_name)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": result})
            return True

        if path == "/api/backups/restore-drill":
            self.require("all")
            file_name = str(data.get("file", "")).strip()
            if not file_name:
                raise ApiError(HTTPStatus.BAD_REQUEST, "backup file is required")
            result = restore_drill_from_backup(self.backup_root, file_name)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": result})
            return True

        if path == "/api/sacc2/sync":
            user = self.require("all")
            state = load_state(self.db_path)
            result = sync_state_with_sacc2(state, user)
            state.setdefault("integrations", {})["sacc2"] = result
            self.add_audit(state, user["name"], "Синхронизирован пакет с sacc2 / ДГАСК", None)
            self.add_notification(state, "ДГАСК", "Синхронизация sacc2 выполнена", f"{result['requests']} запросов · {result['documents']} документов")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": result})
            return True

        if path == "/api/exchange/incoming":
            user = self.require("all")
            state = load_state(self.db_path)
            item = external_request_item(data, state)
            state["requests"].insert(0, item)
            self.add_audit(state, user["name"], f"Импортирован внешний запрос {item['id']} от {item['from']}", item.get("object"))
            self.add_notification(state, item["from"], "Внешний запрос импортирован", f"{item['title']} · срок: {item['due']}")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.CREATED, {"ok": True, "data": item})
            return True

        if path == "/api/objects":
            user = self.require("objects:create")
            name = str(data.get("name", "")).strip()
            address = str(data.get("address", "")).strip()
            stage = str(data.get("stage", "Котлован")).strip() or "Котлован"
            if not name or not address:
                raise ApiError(HTTPStatus.BAD_REQUEST, "name and address are required")
            state = load_state(self.db_path)
            next_id = max((int(obj["id"]) for obj in state["objects"]), default=0) + 1
            item = {
                "id": next_id,
                "name": name,
                "address": address,
                "stage": stage,
                "progress": 5,
                "docs": 0,
                "risk": "medium",
                "inspector": "Не назначен",
                "status": "Новый",
            }
            state["objects"].append(item)
            allowed = allowed_object_ids(state, user)
            if allowed is not None:
                row = team_row_for_user(state.get("team", []), user)
                if row is not None:
                    row.setdefault("object_ids", [])
                    if next_id not in row["object_ids"]:
                        row["object_ids"].append(next_id)
                    row["objects"] = object_label(state, row["object_ids"])
            self.add_audit(state, user["name"], f"Добавлен объект {name}", next_id)
            self.add_notification(state, "Система", "Новый объект", name)
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.CREATED, {"ok": True, "data": item})
            return True

        if path == "/api/requests":
            user = self.require("requests:create")
            title = str(data.get("title", "")).strip()
            text = str(data.get("text", "")).strip()
            obj = int(data.get("object") or 0)
            if not title or not text or not obj:
                raise ApiError(HTTPStatus.BAD_REQUEST, "title, text and object are required")
            state = load_state(self.db_path)
            if not object_exists(state, obj):
                raise ApiError(HTTPStatus.BAD_REQUEST, "object not found")
            require_object_access(state, user, obj)
            item = {
                "id": f"REQ-{1000 + len(state['requests']) + 1}",
                "title": title,
                "object": obj,
                "from": "Компания",
                "owner": user["name"],
                "due": "На рассмотрении",
                "status": "review",
                "text": text,
                "history": [{"time": utc_now(), "actor": user["name"], "text": "Создано обращение компании"}],
            }
            state["requests"].insert(0, item)
            self.add_audit(state, user["name"], f"Создано обращение {item['id']}", obj)
            self.add_notification(state, "Компания", "Обращение отправлено", title)
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.CREATED, {"ok": True, "data": item})
            return True

        if path == "/api/tasks":
            user = self.require("tasks:create")
            title = str(data.get("title", "")).strip()
            text = str(data.get("text", "")).strip()
            owner = str(data.get("owner", "Прораб")).strip() or "Прораб"
            due = str(data.get("due", "Сегодня")).strip() or "Сегодня"
            priority = str(data.get("priority", "medium")).strip()
            source = str(data.get("source", "Внутреннее поручение")).strip() or "Внутреннее поручение"
            try:
                obj = int(data.get("object") or 0)
            except (TypeError, ValueError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "object must be a number") from exc
            if not title or not text or not obj:
                raise ApiError(HTTPStatus.BAD_REQUEST, "title, text and object are required")
            if priority not in TASK_PRIORITIES:
                raise ApiError(HTTPStatus.BAD_REQUEST, "unknown task priority")
            state = load_state(self.db_path)
            if not object_exists(state, obj):
                raise ApiError(HTTPStatus.BAD_REQUEST, "object not found")
            require_object_access(state, user, obj)
            task_count = len(state.setdefault("tasks", [])) + 1
            item = {
                "id": f"TASK-{task_count}",
                "title": title,
                "object": obj,
                "owner": owner,
                "due": due,
                "status": "new",
                "priority": priority,
                "source": source,
                "text": text,
                "evidence": "",
                "history": [{"time": utc_now(), "actor": user["name"], "text": "Поручение создано"}],
            }
            state["tasks"].insert(0, item)
            self.add_audit(state, user["name"], f"Создано поручение {item['id']}: {title}", obj)
            self.add_notification(state, "Компания", "Новое поручение", f"{title} · {object_label(state, [obj])}")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.CREATED, {"ok": True, "data": item})
            return True

        if path.startswith("/api/tasks/") and path.endswith("/update"):
            user = self.require("tasks:update")
            task_id = path.split("/")[3]
            status = str(data.get("status", "")).strip()
            evidence = str(data.get("evidence", "")).strip()
            if status not in TASK_STATUSES:
                raise ApiError(HTTPStatus.BAD_REQUEST, "unknown task status")
            if status == "done" and not evidence:
                raise ApiError(HTTPStatus.BAD_REQUEST, "evidence is required when task is done")
            state = load_state(self.db_path)
            item = find_item(state.setdefault("tasks", []), task_id)
            if not item:
                raise ApiError(HTTPStatus.NOT_FOUND, "task not found")
            require_object_access(state, user, item.get("object"))
            item["status"] = status
            if evidence:
                item["evidence"] = evidence
            item.setdefault("history", []).append(
                {
                    "time": utc_now(),
                    "actor": user["name"],
                    "text": f"Статус: {status}" + (f"; подтверждение: {evidence}" if evidence else ""),
                }
            )
            self.add_audit(state, user["name"], f"Обновлено поручение {task_id}: {status}", item.get("object"))
            self.add_notification(state, "Компания", "Поручение обновлено", f"{item['title']} · {status}")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": item})
            return True

        if path.startswith("/api/requests/") and path.endswith("/reply"):
            user = self.require("requests:reply")
            req_id = path.split("/")[3]
            text = str(data.get("text", "")).strip()
            if not text:
                raise ApiError(HTTPStatus.BAD_REQUEST, "reply text is required")
            state = load_state(self.db_path)
            item = find_item(state["requests"], req_id)
            if not item:
                raise ApiError(HTTPStatus.NOT_FOUND, "request not found")
            require_object_access(state, user, item.get("object"))
            item["status"] = "done"
            item["due"] = "Закрыто"
            item["response"] = text
            item.setdefault("history", []).append({"time": utc_now(), "actor": user["name"], "text": text})
            self.add_audit(state, user["name"], f"Отправлен ответ по запросу {req_id}", item.get("object"))
            self.add_notification(state, "Компания", "Ответ отправлен", f"{req_id}: {item['title']}")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": item})
            return True

        if path.startswith("/api/documents/") and path.endswith("/upload"):
            user = self.require("documents:upload")
            doc_id = path.split("/")[3]
            filename = str(data.get("fileName") or data.get("file") or "").strip()
            content_b64 = str(data.get("contentBase64") or "").strip()
            if not filename:
                raise ApiError(HTTPStatus.BAD_REQUEST, "file is required")
            state = load_state(self.db_path)
            doc = find_item(state["documents"], doc_id)
            if not doc:
                raise ApiError(HTTPStatus.NOT_FOUND, "document not found")
            require_object_access(state, user, doc.get("object"))
            if content_b64:
                stored = store_uploaded_file(self.upload_root, doc_id, filename, content_b64)
                doc.update(stored)
                doc.setdefault("versions", []).append(
                    {
                        "id": f"VER-{len(doc.get('versions', [])) + 1}",
                        "uploaded_at": utc_now(),
                        "uploaded_by": user["name"],
                        **stored,
                    }
                )
            else:
                cleaned = validate_upload_filename(filename)
                doc["file"] = cleaned
                doc.pop("stored_file", None)
                doc.pop("file_url", None)
                doc.pop("file_size", None)
                doc.pop("file_sha256", None)
                doc.setdefault("versions", []).append(
                    {
                        "id": f"VER-{len(doc.get('versions', [])) + 1}",
                        "uploaded_at": utc_now(),
                        "uploaded_by": user["name"],
                        "file": cleaned,
                        "file_size": None,
                        "file_sha256": None,
                    }
                )
            doc["status"] = "На проверке"
            doc["due"] = "Отправлено"
            self.add_audit(state, user["name"], f"Загружен документ {doc['title']}", doc.get("object"))
            self.add_notification(state, "Компания", "Документ отправлен", doc["title"])
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": doc})
            return True

        if path.startswith("/api/documents/") and path.endswith("/sign"):
            user = self.require("documents:sign")
            doc_id = path.split("/")[3]
            comment = str(data.get("comment", "")).strip() or "Подписано ответственным лицом"
            state = load_state(self.db_path)
            doc = find_item(state["documents"], doc_id)
            if not doc:
                raise ApiError(HTTPStatus.NOT_FOUND, "document not found")
            require_object_access(state, user, doc.get("object"))
            if not doc.get("file"):
                raise ApiError(HTTPStatus.BAD_REQUEST, "document file is required before signing")
            signature = sign_document_with_eds(doc, user, comment)
            doc.update(signature)
            doc["status"] = "Подписан"
            doc.setdefault("history", []).append(
                {
                    "time": signature["signed_at"],
                    "actor": user["name"],
                    "text": f"ЭЦП: {comment}",
                }
            )
            self.add_audit(state, user["name"], f"Подписан документ {doc_id}", doc.get("object"))
            self.add_notification(state, "ЭЦП", "Документ подписан", f"{doc['title']} · {user['name']}")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": doc})
            return True

        if path == "/api/team":
            user = self.require("all")
            name = str(data.get("name", "")).strip()
            role = str(data.get("role", "")).strip()
            email = str(data.get("email", "")).strip().lower()
            password = str(data.get("password", "")).strip()
            if not name or not role:
                raise ApiError(HTTPStatus.BAD_REQUEST, "name and role are required")
            state = load_state(self.db_path)
            role_titles = {item["title"] for item in state["roles"]}
            if role not in role_titles:
                raise ApiError(HTTPStatus.BAD_REQUEST, "unknown role")
            role_id = role_id_by_title(role)
            if not role_id:
                raise ApiError(HTTPStatus.BAD_REQUEST, "unknown role")
            default_scope = ROLE_OBJECT_DEFAULTS.get(role_id, None)
            requested_objects = data.get("objectIds")
            if requested_objects is not None and not isinstance(requested_objects, list):
                raise ApiError(HTTPStatus.BAD_REQUEST, "objectIds must be a list")
            object_ids = normalize_object_ids(requested_objects, state)
            if requested_objects is not None:
                requested_count = len({str(item) for item in requested_objects})
                if len(object_ids) != requested_count:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "unknown object in assignment")
            if default_scope is not None and not object_ids:
                object_ids = list(default_scope)
            if email:
                if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "invalid email")
                if len(password) < 8:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "temporary password must be at least 8 characters")
                with open_db(self.db_path) as conn:
                    exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
                    if exists:
                        raise ApiError(HTTPStatus.CONFLICT, "user email already exists")
                    salt, password_hash = hash_password(password)
                    conn.execute(
                        """
                        INSERT INTO users (email, name, role, password_salt, password_hash, active, created_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?)
                        """,
                        (email, name, role_id, salt, password_hash, utc_now()),
                    )
            next_id = f"USR-{len(state['team']) + 1}"
            item = {
                "id": next_id,
                "name": name,
                "role": role,
                "email": email,
                "access": "Назначен",
                "objects": object_label(state, None if default_scope is None and not object_ids else object_ids),
                "object_ids": object_ids,
                "last": "только что",
            }
            state["team"].append(item)
            self.add_audit(state, user["name"], f"Добавлен пользователь {name}", None)
            self.add_notification(state, "Система", "Пользователь добавлен", f"{name}: {role}")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.CREATED, {"ok": True, "data": item})
            return True

        if path == "/api/notifications/read-all":
            user = self.current_user()
            state = load_state(self.db_path)
            for item in state["notifications"]:
                item["read"] = True
            self.add_audit(state, user["name"], "Все уведомления отмечены прочитанными", None)
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": state["notifications"]})
            return True

        if path.startswith("/api/notifications/") and path.endswith("/read"):
            user = self.current_user()
            index = int(path.split("/")[3])
            state = load_state(self.db_path)
            try:
                item = state["notifications"][index]
            except IndexError as exc:
                raise ApiError(HTTPStatus.NOT_FOUND, "notification not found") from exc
            item["read"] = True
            self.add_audit(state, user["name"], f"Уведомление прочитано: {item['title']}", None)
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": item})
            return True

        if path.startswith("/api/money/") and path.endswith("/pay"):
            user = self.require("money:pay")
            pay_id = path.split("/")[3]
            payment_no = str(data.get("paymentNo", "")).strip()
            receipt = validate_upload_filename(str(data.get("receipt", "payment-confirmation.pdf")).strip() or "payment-confirmation.pdf")
            if not payment_no:
                raise ApiError(HTTPStatus.BAD_REQUEST, "paymentNo is required")
            state = load_state(self.db_path)
            item = find_item(state["money"], pay_id)
            if not item:
                raise ApiError(HTTPStatus.NOT_FOUND, "payment not found")
            require_object_access(state, user, item.get("object"))
            gateway_info = confirm_payment_with_gateway(item, user, payment_no, receipt)
            item["status"] = "Оплачено"
            item["due"] = "-"
            item["payment_no"] = payment_no
            item["receipt"] = receipt
            item["paid_at"] = utc_now()
            item["paid_by"] = user["name"]
            item.update(gateway_info)
            item.setdefault("history", []).append({"time": item["paid_at"], "actor": user["name"], "text": f"Оплата подтверждена, номер {payment_no}"})
            self.add_audit(state, user["name"], f"Отмечена оплата {pay_id}: {payment_no}", item.get("object"))
            self.add_notification(state, "Бухгалтерия", "Оплата подтверждена", f"{item['title']} · {payment_no}")
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": item})
            return True

        if path.startswith("/api/money/") and path.endswith("/appeal"):
            user = self.require("money:appeal")
            pay_id = path.split("/")[3]
            text = str(data.get("text", "")).strip()
            if not text:
                raise ApiError(HTTPStatus.BAD_REQUEST, "appeal text is required")
            state = load_state(self.db_path)
            item = find_item(state["money"], pay_id)
            if not item:
                raise ApiError(HTTPStatus.NOT_FOUND, "payment not found")
            require_object_access(state, user, item.get("object"))
            if item.get("status") == "Оплачено":
                raise ApiError(HTTPStatus.BAD_REQUEST, "paid item cannot be appealed")
            item["status"] = "Обжалуется"
            item["due"] = "На рассмотрении"
            item["appeal_text"] = text
            item["appealed_at"] = utc_now()
            item["appealed_by"] = user["name"]
            item.setdefault("history", []).append({"time": item["appealed_at"], "actor": user["name"], "text": f"Обжалование: {text}"})
            self.add_audit(state, user["name"], f"Подано обжалование {pay_id}", item.get("object"))
            self.add_notification(state, "Юрист", "Штраф обжалуется", item["title"])
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": item})
            return True

        if path.startswith("/api/inspections/") and path.endswith("/prepare"):
            user = self.require("inspections:prepare")
            index = int(path.split("/")[3])
            state = load_state(self.db_path)
            try:
                item = state["inspections"][index]
            except IndexError as exc:
                raise ApiError(HTTPStatus.NOT_FOUND, "inspection not found") from exc
            require_object_access(state, user, item.get("object"))
            item["status"] = "Материалы отправлены"
            self.add_audit(state, user["name"], "Подготовлены материалы к проверке", item.get("object"))
            self.add_notification(state, "Компания", "Материалы к проверке отправлены", item["title"])
            save_state(state, self.db_path)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": item})
            return True

        return False

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/") and self.route_get(path):
                return
            if path.startswith("/api/"):
                raise ApiError(HTTPStatus.NOT_FOUND, "api route not found")
            return super().do_GET()
        except ApiError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if self.route_post(path):
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "api route not found")
        except ApiError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.end_headers()

    @staticmethod
    def add_audit(state: dict[str, Any], actor: str, event: str, obj: Any = None) -> None:
        state["audit"].insert(0, {"time": utc_now(), "actor": actor, "event": event, "object": obj})

    @staticmethod
    def add_notification(state: dict[str, Any], from_: str, title: str, text: str) -> None:
        state["notifications"].insert(0, {"time": utc_now(), "from": from_, "title": title, "text": text, "urgent": False, "read": False})


def make_server(
    host: str,
    port: int,
    db_path: Path,
    upload_root: Path | None = None,
    backup_root: Path | None = None,
    tls_cert: Path | None = None,
    tls_key: Path | None = None,
    quiet: bool = False,
    require_production: bool = False,
) -> ThreadingHTTPServer:
    mimetypes.add_type("text/html; charset=utf-8", ".html")
    init_db(db_path)
    upload_root = upload_root or DEFAULT_UPLOAD_ROOT
    backup_root = backup_root or DEFAULT_BACKUP_ROOT
    upload_root.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    interval = backup_interval_seconds_from_env(strict=True)
    server = ThreadingHTTPServer((host, port), Handler)
    server.db_path = db_path  # type: ignore[attr-defined]
    server.upload_root = upload_root  # type: ignore[attr-defined]
    server.backup_root = backup_root  # type: ignore[attr-defined]
    server.quiet = quiet  # type: ignore[attr-defined]
    server.scheme = "http"  # type: ignore[attr-defined]
    if tls_cert or tls_key:
        if not tls_cert or not tls_key:
            server.server_close()
            raise ValueError("tls_cert and tls_key must be provided together")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(tls_cert), str(tls_key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        server.scheme = "https"  # type: ignore[attr-defined]
    if require_production or env_truthy("QH_REQUIRE_PRODUCTION"):
        report = readiness_report(db_path, upload_root, backup_root, getattr(server, "scheme", "http"))
        message = production_blocker_message(report)
        if message:
            server.server_close()
            raise RuntimeError(message)
    if interval:
        scheduler = BackupScheduler(db_path, backup_root, interval, quiet)
        original_server_close = server.server_close

        def close_with_scheduler() -> None:
            scheduler.stop()
            original_server_close()

        server.backup_scheduler = scheduler  # type: ignore[attr-defined]
        server.server_close = close_with_scheduler  # type: ignore[method-assign]
        scheduler.start()
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Qurulush Hub company platform backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--uploads", type=Path, default=DEFAULT_UPLOAD_ROOT)
    parser.add_argument("--backups", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--tls-cert", type=Path, default=None)
    parser.add_argument("--tls-key", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--require-production", action="store_true")
    parser.add_argument("--preflight", action="store_true", help="Print readiness checks and exit without binding an HTTP port")
    parser.add_argument("--preflight-json", action="store_true", help="Print preflight readiness checks as JSON")
    args = parser.parse_args(argv)
    if args.preflight or args.preflight_json:
        return run_preflight(args.db, args.uploads, args.backups, args.tls_cert, args.tls_key, args.require_production, args.preflight_json)
    server = make_server(args.host, args.port, args.db, args.uploads, args.backups, args.tls_cert, args.tls_key, args.quiet, args.require_production)
    print(f"Qurulush Hub company platform: {server.scheme}://{args.host}:{args.port}/")  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
