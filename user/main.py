"""
EasyDict User API Service
合并用户认证、设置同步和词典管理功能
API: /user/*, /settings, /dict/*
Web: /contributor/*
"""

import os
import re
import json
import shutil
import sqlite3
import hashlib
import secrets
import zipfile
import zlib
import io
import asyncio
import unicodedata
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from contextlib import asynccontextmanager

import aiosqlite
import zstandard as zstd

from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, EmailStr
import jwt
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("easydict")

# 根数据目录（自动构建子目录路径）
DATA_PATH = Path(os.environ.get("DATA_PATH", "./easydict-data"))
DATA_DIR = DATA_PATH / "user"
DB_PATH = DATA_DIR / "user.db"
SETTINGS_DIR = DATA_DIR / "settings"
DICTS_PATH = DATA_PATH / "dictionaries"

DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

# JWT_SECRET must be set in environment for security
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "ERROR: JWT_SECRET environment variable is required for security.\n"
        "Please set JWT_SECRET to a long random string before starting the service.\n"
        "Example: JWT_SECRET=$(python -c 'import secrets; print(secrets.token_hex(32))')"
    )
JWT_ALGORITHM = "HS256"

# api 服务地址（同一 docker network 内）
API_INTERNAL_URL = os.environ.get("API_INTERNAL_URL", "http://api:8080")

# File size limits (configurable via environment variables)
MAX_SETTINGS_FILE_SIZE = int(os.environ.get("MAX_SETTINGS_FILE_SIZE", 10 * 1024 * 1024))  # 10MB
MAX_METADATA_FILE_SIZE = int(os.environ.get("MAX_METADATA_FILE_SIZE", 5 * 1024 * 1024))  # 5MB
MAX_DICTIONARY_FILE_SIZE = int(os.environ.get("MAX_DICTIONARY_FILE_SIZE", 2 * 1024 * 1024 * 1024))  # 2GB
MAX_MEDIA_FILE_SIZE = int(os.environ.get("MAX_MEDIA_FILE_SIZE", 4 * 1024 * 1024 * 1024))  # 4GB
MAX_ENTRIES_FILE_SIZE = int(os.environ.get("MAX_ENTRIES_FILE_SIZE", 500 * 1024 * 1024))  # 500MB (compressed)

REQUIRED_FILES = {"metadata.json", "dictionary.db", "logo.png"}


def clear_wal_shm_files(db_path: Path) -> None:
    """清除数据库的 WAL 和 SHM 文件，确保使用新的数据库文件"""
    wal_path = db_path.with_suffix(db_path.suffix + "-wal")
    shm_path = db_path.with_suffix(db_path.suffix + "-shm")
    try:
        if wal_path.exists():
            wal_path.unlink()
            logger.info(f"[wal_shm] removed {wal_path}")
        if shm_path.exists():
            shm_path.unlink()
            logger.info(f"[wal_shm] removed {shm_path}")
    except Exception as e:
        logger.warning(f"[wal_shm] failed to clear wal/shm files for {db_path}: {e}")


async def invalidate_api_dict_cache(dict_id: str) -> None:
    """通知 api 服务清除指定词典的连接缓存，在替换 dictionary.db 后调用"""
    import urllib.request
    url = f"{API_INTERNAL_URL}/internal/cache/{dict_id}"
    try:
        req = urllib.request.Request(url, method="DELETE")
        await asyncio.to_thread(urllib.request.urlopen, req, None, 5)
        logger.info(f"[cache] api cache invalidated for '{dict_id}'")
    except Exception as e:
        logger.warning(f"[cache] failed to invalidate api cache for '{dict_id}': {e}")


async def update_api_checksums(dict_id: str) -> None:
    """通知 api 服务更新指定词典的 CRC32 校验值"""
    import urllib.request
    url = f"{API_INTERNAL_URL}/internal/checksums/{dict_id}"
    try:
        req = urllib.request.Request(url, method="POST")
        await asyncio.to_thread(urllib.request.urlopen, req, None, 10)
        logger.info(f"[checksums] api checksums updated for '{dict_id}'")
    except Exception as e:
        logger.warning(f"[checksums] failed to update api checksums for '{dict_id}': {e}")


def calculate_crc32(data: bytes) -> str:
    """计算数据的 CRC32 校验值，返回 8 位十六进制字符串"""
    return format(zlib.crc32(data) & 0xFFFFFFFF, '08x')


async def stream_write_file(
    upload_file: UploadFile,
    target_path: Path,
    max_size: int,
    expected_crc32: Optional[str] = None,
    filename: str = "",
) -> int:
    """
    流式写入上传文件到目标路径
    
    Args:
        upload_file: 上传的文件对象
        target_path: 目标文件路径
        max_size: 最大允许文件大小
        expected_crc32: 期望的 CRC32 校验值（可选）
        filename: 文件名（用于错误信息）
    
    Returns:
        写入的总字节数
    
    Raises:
        HTTPException: 文件过大或 CRC32 校验失败
    """
    total_size = 0
    crc32_value = 0
    
    with open(target_path, "wb") as f:
        while chunk := await upload_file.read(1024 * 1024):
            total_size += len(chunk)
            if total_size > max_size:
                raise HTTPException(status_code=413, detail=f"{filename} too large (max {max_size / 1024 / 1024:.0f}MB)")
            f.write(chunk)
            if expected_crc32:
                crc32_value = zlib.crc32(chunk, crc32_value)
    
    if expected_crc32:
        server_crc32 = format(crc32_value & 0xFFFFFFFF, '08x')
        if server_crc32 != expected_crc32.lower():
            raise HTTPException(status_code=400, detail=f"{filename} CRC32 mismatch: expected {expected_crc32.lower()}, got {server_crc32}")
    
    return total_size


OPTIONAL_FILES = {"media.db"}
ALLOWED_FILES = REQUIRED_FILES | OPTIONAL_FILES
METADATA_REQUIRED_KEYS = {"id", "name", "source_language", "target_language"}

# 全局 user.db 连接（在 lifespan 中初始化和关闭）
_user_db_conn: Optional[aiosqlite.Connection] = None


class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    email: EmailStr
    password: str = Field(..., min_length=8)


class UserLogin(BaseModel):
    identifier: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def get_db() -> aiosqlite.Connection:
    """返回全局 user.db 连接（在 lifespan 中初始化）"""
    if _user_db_conn is None:
        raise RuntimeError("Database connection not initialized")
    return _user_db_conn


async def init_db():
    conn = get_db()
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    NOT NULL UNIQUE,
            email       TEXT    NOT NULL UNIQUE,
            password    TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dicts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            dict_id     TEXT    NOT NULL UNIQUE,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            name        TEXT    NOT NULL,
            has_media   INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS version_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            dict_id     TEXT    NOT NULL REFERENCES dicts(dict_id),
            version     INTEGER NOT NULL,
            message     TEXT    NOT NULL,
            change_type TEXT    NOT NULL,
            file_name   TEXT    NOT NULL,
            entry_id    TEXT,
            created_at  TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_vh_dict_version
            ON version_history(dict_id, version);
    """)
    await conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _user_db_conn
    _user_db_conn = await aiosqlite.connect(str(DB_PATH))
    _user_db_conn.row_factory = aiosqlite.Row
    await init_db()
    yield
    await _user_db_conn.close()
    _user_db_conn = None


def hash_password(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{digest}"


def verify_password(stored: str, password: str) -> bool:
    parts = stored.split(":", 1)
    if len(parts) != 2:
        return False
    salt, _ = parts
    return secrets.compare_digest(stored, hash_password(password, salt))


def create_token(user_id: int, username: str) -> str:
    payload = {"sub": str(user_id), "username": username}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header[7:]
    payload = verify_token(token)
    user_id = int(payload["sub"])
    conn = get_db()
    cursor = await conn.execute(
        "SELECT id, username, email, created_at FROM users WHERE id = ?",
        (user_id,)
    )
    user = await cursor.fetchone()
    await cursor.close()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(user)


def get_settings_zip_path(user_id: int) -> Path:
    return SETTINGS_DIR / f"{user_id}.zip"


def dict_dir(dict_id: str) -> Path:
    return DICTS_PATH / dict_id


def validate_dict_id(dict_id: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9_\-]{1,64}$", dict_id))


def dict_id_exists(dict_id: str) -> bool:
    return dict_dir(dict_id).exists()


def parse_metadata(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to parse metadata.json: {e}")
        return {}


def validate_metadata_keys(meta: dict) -> list:
    return sorted(METADATA_REQUIRED_KEYS - meta.keys())


def validate_metadata_version(meta: dict) -> Optional[str]:
    if "version" in meta and not isinstance(meta["version"], int):
        return "version must be an integer"
    return None


def _normalize_headword(headword: str) -> str:
    nfd = unicodedata.normalize("NFD", headword.lower())
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def normalize_japanese(text: str) -> str:
    text = text.lower()
    text = text.replace("tch", "っch")
    text = re.sub(r"m(?=[bpm])", "ん", text)
    text = re.sub(r"([bcdfghjklmpqrstvwxyz])\1", r"っ\1", text)
    text = re.sub(r"n(?=[^aeiouy]|$)", "ん", text)
    romaji_map = {
        "kya": "きゃ", "kyu": "きゅ", "kyo": "きょ",
        "sha": "しゃ", "shi": "し", "shu": "しゅ", "she": "しぇ", "sho": "しょ",
        "cha": "ちゃ", "chi": "ち", "chu": "ちゅ", "che": "ちぇ", "cho": "ちょ",
        "nya": "にゃ", "nyu": "にゅ", "nyo": "にょ",
        "hya": "ひゃ", "hyu": "ひゅ", "hyo": "ひょ",
        "mya": "みゃ", "myu": "みゅ", "myo": "みょ",
        "rya": "りゃ", "ryu": "りゅ", "ryo": "りょ",
        "gya": "ぎゃ", "gyu": "ぎゅ", "gyo": "ぎょ",
        "ja": "じゃ", "ji": "じ", "ju": "じゅ", "je": "じぇ", "jo": "じょ",
        "bya": "びゃ", "byu": "びゅ", "byo": "びょ",
        "pya": "ぴゃ", "pyu": "ぴゅ", "pyo": "ぴょ",
        "ka": "か", "ki": "き", "ku": "く", "ke": "け", "ko": "こ",
        "sa": "さ", "su": "す", "se": "せ", "so": "そ",
        "ta": "た", "te": "て", "to": "と", "tsu": "つ",
        "na": "な", "ni": "に", "nu": "ぬ", "ne": "ね", "no": "の",
        "ha": "は", "hi": "ひ", "fu": "ふ", "hu": "ふ", "he": "へ", "ho": "ほ",
        "ma": "ま", "mi": "み", "mu": "む", "me": "め", "mo": "も",
        "ya": "や", "yu": "ゆ", "yo": "よ",
        "ra": "ら", "ri": "り", "ru": "る", "re": "れ", "ro": "ろ",
        "wa": "わ", "wi": "ゐ", "we": "ゑ", "wo": "を",
        "ga": "が", "gi": "ぎ", "gu": "ぐ", "ge": "げ", "go": "ご",
        "za": "ざ", "zu": "ず", "ze": "ぜ", "zo": "ぞ",
        "da": "だ", "di": "ぢ", "du": "づ", "de": "で", "do": "ど",
        "ba": "ば", "bi": "び", "bu": "ぶ", "be": "べ", "bo": "ぼ",
        "pa": "ぱ", "pi": "ぴ", "pu": "ぷ", "pe": "ぺ", "po": "ぽ",
        "a": "あ", "i": "い", "u": "う", "e": "え", "o": "お",
        "ā": "ああ", "ī": "いい", "ū": "うう", "ē": "ええ", "ō": "おお",
    }
    for romaji in sorted(romaji_map.keys(), key=len, reverse=True):
        text = text.replace(romaji, romaji_map[romaji])
    text = re.sub(r"[\s　]+", "", text)
    text = re.sub(r"[’・－\-]", "", text)
    text = "".join([chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in text])
    text = unicodedata.normalize("NFD", text)
    text = text.replace("\u3099", "").replace("\u309a", "")
    text = unicodedata.normalize("NFC", text)
    vowel_map = {
        "あ": "あ", "か": "あ", "さ": "あ", "た": "あ", "な": "あ", "は": "あ", "ま": "あ", "や": "あ", "ら": "あ", "わ": "あ", "ぁ": "あ", "ゃ": "あ", "ゎ": "あ",
        "い": "い", "き": "い", "し": "い", "ち": "い", "に": "い", "ひ": "い", "み": "い", "り": "い", "ゐ": "い", "ぃ": "い",
        "う": "う", "く": "う", "す": "う", "つ": "う", "ぬ": "う", "ふ": "う", "む": "う", "ゆ": "う", "る": "う", "ぅ": "う", "ゅ": "う",
        "え": "え", "け": "え", "せ": "え", "て": "え", "ね": "え", "へ": "え", "め": "え", "れ": "え", "ゑ": "え", "ぇ": "え",
        "お": "お", "こ": "お", "そ": "お", "と": "お", "の": "お", "ほ": "お", "も": "お", "よ": "お", "ろ": "お", "を": "お", "ぉ": "お", "ょ": "お",
    }
    res_choonpu = []
    current_vowel = None
    for c in text:
        if c == "ー":
            if current_vowel:
                res_choonpu.append(current_vowel)
            else:
                res_choonpu.append(c)
        else:
            res_choonpu.append(c)
            if c in vowel_map:
                current_vowel = vowel_map[c]
            else:
                current_vowel = None
    text = "".join(res_choonpu)
    small_to_large = str.maketrans("ぁぃぅぇぉゃゅょゎっ", "あいうえおやゆよわつ")
    text = text.translate(small_to_large)
    return text


def normalize_text(text: str, lang_code: str, is_phonetic: bool) -> str:
    if not text:
        return ""
    if is_phonetic:
        text = text.replace(" ", "")
    if lang_code in {"zh-tw", "zh-hk", "zh-mo", "zh-hant"} and not is_phonetic:
        import opencc
        converter = opencc.OpenCC("t2s.json")
        text = converter.convert(text)
    if lang_code in {"ja", "jp"} and is_phonetic:
        text = normalize_japanese(text)
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").strip().lower()
    return text


def extract_links(links) -> list[str]:
    if not links:
        return []
    if isinstance(links, str):
        return [links] if links.strip() else []
    if isinstance(links, list):
        return [item for item in links if isinstance(item, str) and item.strip()]
    return []


def extract_anchors_from_json(data, current_path: str = "") -> dict:
    result = {}
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{current_path}.{key}" if current_path else key
            result.update(extract_anchors_from_json(value, new_path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_path = f"{current_path}.{i}" if current_path else str(i)
            result.update(extract_anchors_from_json(item, new_path))
    elif isinstance(data, str):
        pattern = r"\[([^\]]+)\]\(anchor\)"
        matches = re.findall(pattern, data)
        for text in matches:
            result[text] = current_path
    return result


def _get_zstd_dict(db_path: Path) -> bytes | None:
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT value FROM config WHERE key = 'zstd_dict'").fetchone()
        conn.close()
        return bytes(row[0]) if row and row[0] else None
    except Exception as e:
        logger.error(f"Failed to get zstd dictionary from {db_path}: {e}")
        return None


def compress_entry(data: bytes, zdict_bytes: bytes | None) -> bytes:
    if zdict_bytes:
        zdict = zstd.ZstdCompressionDict(zdict_bytes)
        cctx = zstd.ZstdCompressor(level=7, dict_data=zdict)
    else:
        cctx = zstd.ZstdCompressor(level=7)
    return cctx.compress(data)


def upsert_entry_in_db(db_path: Path, entry_json: dict, zdict_bytes: bytes | None = None, lang_code: str = "en") -> str:
    """将单个词条 upsert 进 dictionary.db。zdict_bytes 可由调用方预先获取并传入，避免重复查询 config 表。"""
    entry_id = entry_json.get("entry_id")
    if entry_id is not None:
        entry_id = int(entry_id)
    compressed = compress_entry(
        json.dumps(entry_json, ensure_ascii=False).encode("utf-8"), zdict_bytes
    )
    conn = sqlite3.connect(str(db_path))
    try:
        if entry_id is not None:
            conn.execute("DELETE FROM entries WHERE entry_id = ?", (entry_id,))
        conn.execute("INSERT INTO entries (entry_id, json_data) VALUES (?, ?)", (entry_id, compressed))
        phonetic_raw = entry_json.get("phonetic", "")
        phonetic_norm = normalize_text(phonetic_raw, lang_code, True)
        headword_anchor_map = {}
        if "headword" in entry_json:
            headword_anchor_map[entry_json["headword"]] = ""
        links = entry_json.get("links", [])
        for link in extract_links(links):
            headword_anchor_map[link] = ""
        headword_anchor_map.update(extract_anchors_from_json(entry_json))
        etype = entry_json.get("entry_type", "")
        for hw, anchor in headword_anchor_map.items():
            hw_norm = normalize_text(hw, lang_code, False)
            conn.execute(
                "INSERT INTO indices (headword, headword_normalized, phonetic, entry_type, entry_id, anchor) VALUES (?, ?, ?, ?, ?, ?)",
                (hw, hw_norm, phonetic_norm or None, etype or None, entry_id, anchor or None)
            )
        conn.commit()
        return "upserted"
    finally:
        conn.close()


async def next_version(dict_id: str) -> int:
    conn = get_db()
    cursor = await conn.execute(
        "SELECT MAX(version) FROM version_history WHERE dict_id = ?", (dict_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    return (row[0] or 0) + 1


async def record_version(dict_id: str, version: int, message: str, change_type: str, file_name: str, entry_id: int | None = None):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    await conn.execute(
        """INSERT INTO version_history
           (dict_id, version, message, change_type, file_name, entry_id, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (dict_id, version, message, change_type, file_name, entry_id, now)
    )
    await conn.commit()


app = FastAPI(title="EasyDict User API", description="用户认证、设置同步和词典管理", version="1.0.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    logger.warning(f"[validation] {request.method} {request.url.path} errors={errors}")
    if errors:
        first_error = errors[0]
        field = ".".join(str(loc) for loc in first_error.get("loc", []))
        msg = first_error.get("msg", "Validation error")
        detail = f"{field}: {msg}" if field else msg
    else:
        detail = "Validation error"
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "easydict-user"}


# ============ User API ============

@app.post("/user/register", response_model=TokenResponse)
async def register(data: UserRegister):
    if not re.match(r"^[a-zA-Z0-9_]{3,32}$", data.username):
        raise HTTPException(status_code=400, detail="Username must be 3-32 letters, numbers or underscores")
    now = datetime.now(timezone.utc).isoformat()
    hashed = hash_password(data.password)
    conn = get_db()
    try:
        await conn.execute(
            "INSERT INTO users (username, email, password, created_at) VALUES (?,?,?,?)",
            (data.username, data.email.lower(), hashed, now)
        )
        await conn.commit()
        user_cursor = await conn.execute("SELECT id FROM users WHERE username = ?", (data.username,))
        user_row = await user_cursor.fetchone()
        await user_cursor.close()
        user_id = user_row[0]
    except sqlite3.IntegrityError as e:
        if "username" in str(e):
            raise HTTPException(status_code=400, detail="Username already exists")
        elif "email" in str(e):
            raise HTTPException(status_code=400, detail="Email already registered")
        raise HTTPException(status_code=400, detail="Registration failed")
    token = create_token(user_id, data.username)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user={"id": user_id, "username": data.username, "email": data.email.lower()}
    )


@app.post("/user/login", response_model=TokenResponse)
async def login(data: UserLogin):
    conn = get_db()
    login_cursor = await conn.execute(
        "SELECT * FROM users WHERE username = ? OR email = ?",
        (data.identifier, data.identifier.lower())
    )
    user = await login_cursor.fetchone()
    await login_cursor.close()
    if not user or not verify_password(user["password"], data.password):
        raise HTTPException(status_code=401, detail="Invalid username/email or password")
    token = create_token(user["id"], user["username"])
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user={"id": user["id"], "username": user["username"], "email": user["email"]}
    )


@app.get("/user/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user


# ============ Settings API ============

@app.get("/user/settings")
async def download_settings(user: dict = Depends(get_current_user)):
    zip_path = get_settings_zip_path(user["id"])
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Settings not found")
    return StreamingResponse(
        iter([zip_path.read_bytes()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{user["id"]}.zip"', "Cache-Control": "no-cache"}
    )


@app.post("/user/settings")
async def upload_settings(user: dict = Depends(get_current_user), file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="File must be a .zip file")
    
    # Validate file size
    if file.size is not None and file.size > MAX_SETTINGS_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"Settings file too large (max {MAX_SETTINGS_FILE_SIZE / 1024 / 1024:.0f}MB)")
    
    zip_path = get_settings_zip_path(user["id"])
    content = await file.read()
    
    # Additional size check on actual content
    if len(content) > MAX_SETTINGS_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"Settings file too large (max {MAX_SETTINGS_FILE_SIZE / 1024 / 1024:.0f}MB)")
    
    try:
        with zipfile.ZipFile(io.BytesIO(content), 'r') as zf:
            zf.testzip()
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")
    zip_path.write_bytes(content)
    return {"success": True, "size": len(content), "updated_at": datetime.now(timezone.utc).isoformat()}


@app.delete("/user/settings")
async def delete_settings(user: dict = Depends(get_current_user)):
    zip_path = get_settings_zip_path(user["id"])
    if zip_path.exists():
        zip_path.unlink()
    return {"success": True}


# ============ Dict API ============

@app.get("/user/dicts")
async def list_dicts(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = await conn.execute(
        "SELECT dict_id, name, has_media, created_at, updated_at FROM dicts WHERE user_id = ? ORDER BY updated_at DESC",
        (user["id"],)
    )
    dicts = await cursor.fetchall()
    await cursor.close()
    return [{"dict_id": d["dict_id"], "name": d["name"], "has_media": bool(d["has_media"]), "created_at": d["created_at"], "updated_at": d["updated_at"]} for d in dicts]


@app.delete("/user/dicts/{dict_id}")
async def delete_dict(dict_id: str, user: dict = Depends(get_current_user)):
    conn = get_db()
    d_cursor = await conn.execute(
        "SELECT * FROM dicts WHERE dict_id = ? AND user_id = ?", (dict_id, user["id"])
    )
    d = await d_cursor.fetchone()
    await d_cursor.close()
    if not d:
        raise HTTPException(status_code=404, detail="Dict not found")
    shutil.rmtree(dict_dir(dict_id), ignore_errors=True)
    await conn.execute("DELETE FROM dicts WHERE dict_id = ?", (dict_id,))
    await conn.commit()
    return {"success": True}


# upload.dict.dxde.de 专用路由（绕过 Cloudflare，用于大文件上传）


@app.get("/update")
async def get_updates_batch(request: Request):
    """
    批量查询多本词典的更新信息。

    查询参数格式：{dict_id}={from_ver} 或 {dict_id}={from_ver}:{to_ver}，例如：
      /update?ode_now=5&another_dict=0:10
    不指定 to_ver 则默认查询到最新版本。
    """
    results = []
    for dict_id, ver_str in request.query_params.items():
        # 解析 from_ver 和可选的 to_ver
        if ":" in ver_str:
            parts = ver_str.split(":", 1)
            try:
                from_ver = int(parts[0])
                to_ver: Optional[int] = int(parts[1])
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid version range for '{dict_id}': '{ver_str}'")
        else:
            try:
                from_ver = int(ver_str)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid version for '{dict_id}': '{ver_str}'")
            to_ver = None

        dict_path = dict_dir(dict_id)
        if not dict_path.exists():
            results.append({"dict_id": dict_id, "error": "not found"})
            continue

        if to_ver is None:
            conn = get_db()
            ver_cursor = await conn.execute(
                "SELECT MAX(version) FROM version_history WHERE dict_id = ?",
                (dict_id,)
            )
            row = await ver_cursor.fetchone()
            await ver_cursor.close()
            to_ver = row[0] if row and row[0] is not None else 0

        history = await _get_history_between(dict_id, from_ver, to_ver or 0)
        required = await _compute_required_files(dict_id, from_ver, to_ver or 0)

        results.append({
            "dict_id": dict_id,
            "from": from_ver,
            "to": to_ver,
            "history": history,
            "required": required,
        })

    return results


# upload.dict.dxde.de 专用路由（绕过 Cloudflare，用于大文件上传）


async def create_dict_impl(
    user: dict,
    metadata_file: UploadFile,
    dictionary_file: UploadFile,
    logo_file: UploadFile,
    media_file: Optional[UploadFile] = None,
    message: str = "初始上传",
    dictionary_crc32: Optional[str] = None,
    media_crc32: Optional[str] = None,
):
    """Internal implementation of dictionary creation logic"""
    errors = []
    for f in [metadata_file, dictionary_file, logo_file]:
        if not f.filename:
            errors.append(f"缺少必需文件")
    if errors:
        raise HTTPException(status_code=400, detail=errors)
    
    # Validate file sizes
    if metadata_file.size is not None and metadata_file.size > MAX_METADATA_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"Metadata file too large (max {MAX_METADATA_FILE_SIZE / 1024 / 1024:.0f}MB)")
    if dictionary_file.size is not None and dictionary_file.size > MAX_DICTIONARY_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"Dictionary file too large (max {MAX_DICTIONARY_FILE_SIZE / 1024 / 1024:.0f}MB)")
    if logo_file.size is not None and logo_file.size > MAX_METADATA_FILE_SIZE:  # Logo should be small
        raise HTTPException(status_code=413, detail="Logo file too large")
    if media_file and media_file.filename and media_file.size is not None and media_file.size > MAX_MEDIA_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"Media file too large (max {MAX_MEDIA_FILE_SIZE / 1024 / 1024 / 1024:.0f}GB)")

    try:
        meta_content = await metadata_file.read()
        # Additional size check on actual content
        if len(meta_content) > MAX_METADATA_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"Metadata file too large (max {MAX_METADATA_FILE_SIZE / 1024 / 1024:.0f}MB)")
        meta = json.loads(meta_content.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to parse metadata.json: {e}")
        raise HTTPException(status_code=400, detail="Invalid metadata.json")

    missing = validate_metadata_keys(meta)
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required keys: {missing}")

    version_error = validate_metadata_version(meta)
    if version_error:
        raise HTTPException(status_code=400, detail=version_error)

    dict_id = str(meta.get("id", "")).strip()
    if not validate_dict_id(dict_id):
        raise HTTPException(status_code=400, detail="Invalid dict_id format. dict_id must match pattern: ^[a-zA-Z0-9_\\-]{1,64}$")

    conn = get_db()
    existing_cursor = await conn.execute("SELECT id FROM dicts WHERE dict_id = ?", (dict_id,))
    existing = await existing_cursor.fetchone()
    await existing_cursor.close()
    disk_exists = dict_id_exists(dict_id)
    if existing or disk_exists:
        raise HTTPException(status_code=400, detail="Dict ID already exists")

    target_dir = dict_dir(dict_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    has_media = False

    try:
        (target_dir / "metadata.json").write_bytes(meta_content)
        
        await stream_write_file(
            dictionary_file,
            target_dir / "dictionary.db",
            MAX_DICTIONARY_FILE_SIZE,
            dictionary_crc32,
            "dictionary.db"
        )
        clear_wal_shm_files(target_dir / "dictionary.db")
        
        await stream_write_file(
            logo_file,
            target_dir / "logo.png",
            MAX_METADATA_FILE_SIZE,
            None,
            "logo.png"
        )
        
        if media_file and media_file.filename:
            await stream_write_file(
                media_file,
                target_dir / "media.db",
                MAX_MEDIA_FILE_SIZE,
                media_crc32,
                "media.db"
            )
            clear_wal_shm_files(target_dir / "media.db")
            has_media = True

        await invalidate_api_dict_cache(dict_id)
        await update_api_checksums(dict_id)

        display_name = (meta.get("name") or "").strip() or dict_id
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            "INSERT INTO dicts (dict_id, user_id, name, has_media, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (dict_id, user["id"], display_name, int(has_media), now, now)
        )
        await conn.commit()
        ver = await next_version(dict_id)
        for fname in ["metadata.json", "dictionary.db", "logo.png"]:
            await record_version(dict_id, ver, message, "file", fname)
        if has_media:
            await record_version(dict_id, ver, message, "file", "media.db")

        # Update metadata.json version and updated_at
        metadata_path = target_dir / "metadata.json"
        try:
            meta = parse_metadata(metadata_path)
            meta["version"] = ver
            meta["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+00:00")
            metadata_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to update metadata.json version: {e}")

        return {"success": True, "version": ver}
    except Exception as e:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/")
async def upload_create_dict(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    field_names = list(form.keys())
    logger.info(f"[upload_create_dict] received fields: {field_names}")

    def _get_file(name):
        val = form.get(name)
        return val if (val and hasattr(val, 'filename')) else None

    def _get_str(name, default=None):
        val = form.get(name)
        return str(val) if val and not hasattr(val, 'filename') else default

    metadata_file = _get_file("metadata_file")
    dictionary_file = _get_file("dictionary_file")
    logo_file = _get_file("logo_file")
    media_file = _get_file("media_file")
    message = _get_str("message", "初始上传")
    dictionary_crc32 = _get_str("dictionary_crc32")
    media_crc32 = _get_str("media_crc32")

    missing = [n for n, f in [("metadata_file", metadata_file), ("dictionary_file", dictionary_file), ("logo_file", logo_file)] if f is None]
    if missing:
        logger.warning(f"[upload_create_dict] missing fields: {missing}, all fields: {field_names}")
        raise HTTPException(status_code=422, detail=f"Missing required fields: {missing}. Received: {field_names}")

    return await create_dict_impl(
        user=user,
        metadata_file=metadata_file,
        dictionary_file=dictionary_file,
        logo_file=logo_file,
        media_file=media_file,
        message=message,
        dictionary_crc32=dictionary_crc32,
        media_crc32=media_crc32,
    )


async def update_dict_impl(
    dict_id: str,
    user: dict,
    message: str = "更新词典",
    metadata_file: Optional[UploadFile] = None,
    dictionary_file: Optional[UploadFile] = None,
    logo_file: Optional[UploadFile] = None,
    media_file: Optional[UploadFile] = None,
    dictionary_crc32: Optional[str] = None,
    media_crc32: Optional[str] = None,
):
    """Internal implementation of dictionary update logic"""
    # Validate dict_id format
    if not validate_dict_id(dict_id):
        raise HTTPException(status_code=400, detail="Invalid dict_id format. dict_id must match pattern: ^[a-zA-Z0-9_\\-]{1,64}$")
    
    t0 = time.time()
    logger.info(f"[update_dict_impl] START dict_id={dict_id} user={user.get('id')}")
    conn = get_db()
    d_cursor = await conn.execute(
        "SELECT * FROM dicts WHERE dict_id = ? AND user_id = ?", (dict_id, user["id"])
    )
    d = await d_cursor.fetchone()
    await d_cursor.close()
    if not d:
        raise HTTPException(status_code=404, detail="Dict not found")

    target_dir = dict_dir(dict_id)
    if not target_dir.exists():
        raise HTTPException(status_code=400, detail="Dict directory not found")

    updated_files = []
    has_media = bool(d["has_media"])
    display_name = d["name"]

    try:
        if metadata_file and metadata_file.filename:
            logger.info(f"[update_dict_impl] reading metadata_file elapsed={time.time()-t0:.1f}s")
            meta_content = await metadata_file.read()
            # Validate file size
            if len(meta_content) > MAX_METADATA_FILE_SIZE:
                raise HTTPException(status_code=413, detail=f"Metadata file too large (max {MAX_METADATA_FILE_SIZE / 1024 / 1024:.0f}MB)")
            logger.info(f"[update_dict_impl] metadata_file read done size={len(meta_content)} elapsed={time.time()-t0:.1f}s")
            meta = json.loads(meta_content.decode("utf-8"))
            missing = validate_metadata_keys(meta)
            if missing:
                raise HTTPException(status_code=400, detail=f"Missing required keys: {missing}")
            version_error = validate_metadata_version(meta)
            if version_error:
                raise HTTPException(status_code=400, detail=version_error)
            new_dict_id = str(meta.get("id", "")).strip()
            if new_dict_id != dict_id:
                raise HTTPException(status_code=400, detail=f"metadata.id ({new_dict_id}) must match dict_id ({dict_id})")
            (target_dir / "metadata.json").write_bytes(meta_content)
            display_name = (meta.get("name") or "").strip() or dict_id
            updated_files.append("metadata.json")

        if dictionary_file and dictionary_file.filename:
            logger.info(f"[update_dict_impl] streaming dictionary_file elapsed={time.time()-t0:.1f}s")
            await stream_write_file(
                dictionary_file,
                target_dir / "dictionary.db",
                MAX_DICTIONARY_FILE_SIZE,
                dictionary_crc32,
                "dictionary.db"
            )
            clear_wal_shm_files(target_dir / "dictionary.db")
            logger.info(f"[update_dict_impl] dictionary_file write done elapsed={time.time()-t0:.1f}s")
            updated_files.append("dictionary.db")

        if logo_file and logo_file.filename:
            logger.info(f"[update_dict_impl] streaming logo_file elapsed={time.time()-t0:.1f}s")
            await stream_write_file(
                logo_file,
                target_dir / "logo.png",
                MAX_METADATA_FILE_SIZE,
                None,
                "logo.png"
            )
            logger.info(f"[update_dict_impl] logo_file write done elapsed={time.time()-t0:.1f}s")
            updated_files.append("logo.png")

        if media_file and media_file.filename:
            logger.info(f"[update_dict_impl] streaming media_file elapsed={time.time()-t0:.1f}s")
            await stream_write_file(
                media_file,
                target_dir / "media.db",
                MAX_MEDIA_FILE_SIZE,
                media_crc32,
                "media.db"
            )
            clear_wal_shm_files(target_dir / "media.db")
            logger.info(f"[update_dict_impl] media_file write done elapsed={time.time()-t0:.1f}s")
            has_media = True
            updated_files.append("media.db")

        if not updated_files:
            raise HTTPException(status_code=400, detail="No files provided for update")

        # dictionary.db 或 media.db 有更新时，统一刷新 api 服务的连接缓存
        if "dictionary.db" in updated_files or "media.db" in updated_files:
            await invalidate_api_dict_cache(dict_id)
            await update_api_checksums(dict_id)

        now = datetime.now(timezone.utc).isoformat()
        display_name = display_name if "display_name" in dir() else d["name"]
        await conn.execute(
            "UPDATE dicts SET name=?, has_media=?, updated_at=? WHERE dict_id=?",
            (display_name, int(has_media), now, dict_id)
        )
        await conn.commit()

        ver = await next_version(dict_id)
        for fname in updated_files:
            await record_version(dict_id, ver, message, "file", fname)

        # Update metadata.json version and updated_at
        metadata_path = target_dir / "metadata.json"
        if metadata_path.exists():
            try:
                meta = parse_metadata(metadata_path)
                meta["version"] = ver
                meta["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+00:00")
                metadata_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to update metadata.json version: {e}")

        logger.info(f"[update_dict_impl] DONE dict_id={dict_id} updated_files={updated_files} total={time.time()-t0:.1f}s")
        return {"success": True, "version": ver}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/{dict_id}")
async def upload_update_dict(dict_id: str, request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    field_names = list(form.keys())
    logger.info(f"[upload_update_dict] dict_id={dict_id} received fields: {field_names}")

    def _get_file(name):
        val = form.get(name)
        return val if (val and hasattr(val, 'filename')) else None

    def _get_str(name, default=None):
        val = form.get(name)
        return str(val) if val and not hasattr(val, 'filename') else default

    message = _get_str("message", "更新词典")

    return await update_dict_impl(
        dict_id=dict_id,
        user=user,
        message=message,
        metadata_file=_get_file("metadata_file"),
        dictionary_file=_get_file("dictionary_file"),
        logo_file=_get_file("logo_file"),
        media_file=_get_file("media_file"),
        dictionary_crc32=_get_str("dictionary_crc32"),
        media_crc32=_get_str("media_crc32"),
    )





@app.post("/user/dicts/{dict_id}/entries")
async def upsert_dict_entries(
    dict_id: str,
    user: dict = Depends(get_current_user),
    file: UploadFile = File(...),
    message: str = Form("更新条目"),
):
    conn = get_db()
    d_cursor2 = await conn.execute(
        "SELECT * FROM dicts WHERE dict_id = ? AND user_id = ?", (dict_id, user["id"])
    )
    d = await d_cursor2.fetchone()
    await d_cursor2.close()
    if not d:
        raise HTTPException(status_code=404, detail="Dict not found")

    db_path = dict_dir(dict_id) / "dictionary.db"
    if not db_path.exists():
        raise HTTPException(status_code=400, detail="dictionary.db not found")

    if not file.filename or not file.filename.endswith(".zst"):
        raise HTTPException(status_code=400, detail="File must be a .zst file")

    content = await file.read()
    
    # Validate compressed file size
    if len(content) > MAX_ENTRIES_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"Entries file too large (max {MAX_ENTRIES_FILE_SIZE / 1024 / 1024:.0f}MB)")

    dctx = zstd.ZstdDecompressor()
    try:
        decompressed = dctx.decompress(content)
        # Validate decompressed size (limit to prevent zip bomb attacks)
        if len(decompressed) > MAX_DICTIONARY_FILE_SIZE:
            raise HTTPException(status_code=413, detail="Decompressed entries data too large")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decompress file: {e}")

    try:
        ver = await next_version(dict_id)
        upsert_entries = []
        delete_entry_ids = []
        for i, line in enumerate(decompressed.decode("utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid JSON at line {i + 1}")
            if entry.get("_delete"):
                eid = entry.get("entry_id")
                if eid is None:
                    raise HTTPException(status_code=400, detail=f"Missing entry_id for _delete entry at line {i + 1}")
                delete_entry_ids.append(int(eid))
            else:
                upsert_entries.append(entry)

        metadata_path = dict_dir(dict_id) / "metadata.json"
        lang_code = "en"
        if metadata_path.exists():
            meta = parse_metadata(metadata_path)
            lang_code = meta.get("source_language", "en") or "en"

        def _do_writes(lang_code: str):
            existing_eids = set()
            if upsert_entries or delete_entry_ids:
                db_conn = sqlite3.connect(str(db_path))
                try:
                    cursor = db_conn.execute("SELECT DISTINCT entry_id FROM entries")
                    existing_eids = {row[0] for row in cursor.fetchall()}
                finally:
                    db_conn.close()
            
            if delete_entry_ids:
                db_conn = sqlite3.connect(str(db_path))
                try:
                    placeholders = ",".join("?" * len(delete_entry_ids))
                    db_conn.execute(
                        f"DELETE FROM entries WHERE entry_id IN ({placeholders})",
                        delete_entry_ids,
                    )
                    db_conn.commit()
                finally:
                    db_conn.close()
            if upsert_entries:
                zdict_bytes = _get_zstd_dict(db_path)
                for entry in upsert_entries:
                    upsert_entry_in_db(db_path, entry, zdict_bytes, lang_code)
            
            return existing_eids

        existing_eids = await asyncio.to_thread(_do_writes, lang_code)
        await invalidate_api_dict_cache(dict_id)
        await update_api_checksums(dict_id)

        for eid in delete_entry_ids:
            await record_version(dict_id, ver, message, "delete", "dictionary.db", eid)
        for entry in upsert_entries:
            eid = entry.get("entry_id")
            if eid is not None:
                eid_int = int(eid)
                # 区分 insert 和 update：如果在执行前不存在，则是 insert；否则是 update
                change_type = "insert" if eid_int not in existing_eids else "update"
                await record_version(dict_id, ver, message, change_type, "dictionary.db", eid_int)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Update metadata.json version and updated_at
    metadata_path = dict_dir(dict_id) / "metadata.json"
    if metadata_path.exists():
        try:
            meta = parse_metadata(metadata_path)
            meta["version"] = ver
            meta["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+00:00")
            metadata_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update metadata.json: {e}")

    return {"success": True, "version": ver}


# ============ Update API ============

async def _get_history_between(dict_id: str, from_ver: int, to_ver: int) -> list[dict]:
    conn = get_db()
    cursor = await conn.execute(
        """SELECT DISTINCT version, message
           FROM version_history
           WHERE dict_id = ? AND version > ? AND version <= ?
           ORDER BY version ASC""",
        (dict_id, from_ver, to_ver)
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [{"v": r["version"], "m": r["message"]} for r in rows]


async def _compute_required_files(dict_id: str, from_ver: int, to_ver: int) -> dict[str, list]:
    conn = get_db()
    cursor = await conn.execute(
        """SELECT version, change_type, file_name, entry_id
           FROM version_history
           WHERE dict_id = ? AND version > ? AND version <= ?
           ORDER BY version ASC""",
        (dict_id, from_ver, to_ver)
    )
    rows = await cursor.fetchall()
    await cursor.close()

    files_needed: set[str] = set()
    entries_needed: dict[int, None] = {}
    entries_deleted: dict[int, None] = {}
    entries_state: dict[int, str] = {}  # 追踪每个entry从from_ver到to_ver的状态变化
    db_file_updated = False

    for r in rows:
        if r["change_type"] == "file":
            files_needed.add(r["file_name"])
            if r["file_name"] == "dictionary.db":
                db_file_updated = True
                entries_needed.clear()
                entries_deleted.clear()
                entries_state.clear()
        elif r["change_type"] in ("insert", "update", "entry") and not db_file_updated:
            eid = int(r["entry_id"])
            # 标记此entry的最终状态：insert 或 update 都视为"存在且被修改"
            entries_state[eid] = r["change_type"]
            entries_needed[eid] = None
            # 如果之前记录为删除，现在又被 insert/update，则从删除列表移除
            entries_deleted.pop(eid, None)
        elif r["change_type"] == "delete" and not db_file_updated:
            eid = int(r["entry_id"])
            # 只有在该entry被删除且之前是 update（不是 insert）时，才算真正的删除
            # 如果是 insert 然后 delete，说明这个 entry 在整个版本范围内不存在，不需要删除
            if entries_state.get(eid) == "update":
                entries_deleted[eid] = None
                # 从更新列表移除
                entries_needed.pop(eid, None)
            elif eid in entries_state and entries_state[eid] == "insert":
                # 新增的 entry 又被删除了，从需要的列表和状态中移除
                entries_needed.pop(eid, None)
                entries_state.pop(eid, None)

    return {
        "files": sorted(files_needed),
        "entries": list(entries_needed.keys()),
        "deleted_entries": list(entries_deleted.keys()),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
