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
import io
import unicodedata
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

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

DATA_DIR = Path(os.environ.get("USER_DATA_PATH", "/data/user"))
DB_PATH = DATA_DIR / "user.db"
SETTINGS_DIR = DATA_DIR / "settings"
DICTS_PATH = Path(os.environ.get("DICTIONARIES_PATH", "/data/dictionaries"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "168"))

REQUIRED_FILES = {"metadata.json", "dictionary.db", "logo.png"}
OPTIONAL_FILES = {"media.db"}
ALLOWED_FILES = REQUIRED_FILES | OPTIONAL_FILES
METADATA_REQUIRED_KEYS = {"id", "name", "source_language", "target_language"}


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
    expires_in: int
    user: dict


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
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


init_db()


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
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "username": username, "exp": expire}
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
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, username, email, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
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
    except:
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


def _get_zstd_dict(db_path: Path) -> bytes | None:
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT value FROM config WHERE key = 'zstd_dict'").fetchone()
        conn.close()
        return bytes(row[0]) if row and row[0] else None
    except:
        return None


def compress_entry(data: bytes, zdict_bytes: bytes | None) -> bytes:
    if zdict_bytes:
        zdict = zstd.ZstdCompressionDict(zdict_bytes)
        cctx = zstd.ZstdCompressor(level=7, dict_data=zdict)
    else:
        cctx = zstd.ZstdCompressor(level=7)
    return cctx.compress(data)


def upsert_entry_in_db(db_path: Path, entry_json: dict) -> str:
    entry_id = entry_json.get("entry_id")
    zdict_bytes = _get_zstd_dict(db_path)
    compressed = compress_entry(
        json.dumps(entry_json, ensure_ascii=False).encode("utf-8"), zdict_bytes
    )
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("PRAGMA table_info(entries)")
        columns = [row[1] for row in cur.fetchall()]
        existing = None
        if entry_id is not None:
            row = conn.execute(
                "SELECT entry_id FROM entries WHERE entry_id = ?", (str(entry_id),)
            ).fetchone()
            existing = row
        if existing:
            conn.execute("UPDATE entries SET json_data = ? WHERE entry_id = ?", (compressed, str(entry_id)))
            conn.commit()
            return "updated"
        else:
            headword = str(entry_json.get("headword", ""))
            headword_normalized = _normalize_headword(headword)
            col_map = {
                "entry_id": str(entry_id) if entry_id is not None else None,
                "headword": headword or None,
                "headword_normalized": headword_normalized or None,
                "entry_type": str(entry_json.get("entry_type", "")) or None,
                "page": str(entry_json.get("page", "")) or None,
                "section": str(entry_json.get("section", "")) or None,
                "version": str(entry_json.get("version", "")) or None,
                "json_data": compressed,
            }
            insert_cols = [c for c in columns if c in col_map]
            values = [col_map[c] for c in insert_cols]
            placeholders = ", ".join("?" * len(insert_cols))
            col_names = ", ".join(insert_cols)
            conn.execute(f"INSERT INTO entries ({col_names}) VALUES ({placeholders})", values)
            conn.commit()
            return "inserted"
    finally:
        conn.close()


def next_version(dict_id: str) -> int:
    with get_db() as conn:
        row = conn.execute(
            "SELECT MAX(version) FROM version_history WHERE dict_id = ?", (dict_id,)
        ).fetchone()
    return (row[0] or 0) + 1


def record_version(dict_id: str, version: int, message: str, change_type: str, file_name: str, entry_id: int | None = None):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO version_history
               (dict_id, version, message, change_type, file_name, entry_id, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (dict_id, version, message, change_type, file_name, entry_id, now)
        )


app = FastAPI(title="EasyDict User API", description="用户认证、设置同步和词典管理", version="1.0.0")


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
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, email, password, created_at) VALUES (?,?,?,?)",
                (data.username, data.email.lower(), hashed, now)
            )
            user_id = conn.execute("SELECT id FROM users WHERE username = ?", (data.username,)).fetchone()[0]
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
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user={"id": user_id, "username": data.username, "email": data.email.lower()}
    )


@app.post("/user/login", response_model=TokenResponse)
async def login(data: UserLogin):
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (data.identifier, data.identifier.lower())
        ).fetchone()
    if not user or not verify_password(user["password"], data.password):
        raise HTTPException(status_code=401, detail="Invalid username/email or password")
    token = create_token(user["id"], user["username"])
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user={"id": user["id"], "username": user["username"], "email": user["email"]}
    )


@app.get("/user/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user


# ============ Settings API ============

@app.get("/settings")
async def download_settings(user: dict = Depends(get_current_user)):
    zip_path = get_settings_zip_path(user["id"])
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Settings not found")
    return StreamingResponse(
        iter([zip_path.read_bytes()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{user["id"]}.zip"', "Cache-Control": "no-cache"}
    )


@app.post("/settings")
async def upload_settings(user: dict = Depends(get_current_user), file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="File must be a .zip file")
    zip_path = get_settings_zip_path(user["id"])
    content = await file.read()
    try:
        with zipfile.ZipFile(io.BytesIO(content), 'r') as zf:
            zf.testzip()
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")
    zip_path.write_bytes(content)
    return {"success": True, "size": len(content), "updated_at": datetime.now(timezone.utc).isoformat()}


@app.delete("/settings")
async def delete_settings(user: dict = Depends(get_current_user)):
    zip_path = get_settings_zip_path(user["id"])
    if zip_path.exists():
        zip_path.unlink()
    return {"success": True}


# ============ Dict API ============

@app.get("/user/dicts")
async def list_dicts(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        dicts = conn.execute(
            "SELECT dict_id, name, has_media, created_at, updated_at FROM dicts WHERE user_id = ? ORDER BY updated_at DESC",
            (user["id"],)
        ).fetchall()
    return [{"dict_id": d["dict_id"], "name": d["name"], "has_media": bool(d["has_media"]), "created_at": d["created_at"], "updated_at": d["updated_at"]} for d in dicts]


@app.post("/user/dicts")
async def create_dict(
    user: dict = Depends(get_current_user),
    metadata_file: UploadFile = File(...),
    dictionary_file: UploadFile = File(...),
    logo_file: UploadFile = File(...),
    media_file: Optional[UploadFile] = File(None),
    message: str = Form("初始上传")
):
    errors = []
    for f in [metadata_file, dictionary_file, logo_file]:
        if not f.filename:
            errors.append(f"缺少必需文件")
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    try:
        meta_content = await metadata_file.read()
        meta = json.loads(meta_content.decode("utf-8"))
    except:
        raise HTTPException(status_code=400, detail="Invalid metadata.json")

    missing = validate_metadata_keys(meta)
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required keys: {missing}")

    version_error = validate_metadata_version(meta)
    if version_error:
        raise HTTPException(status_code=400, detail=version_error)

    dict_id = str(meta.get("id", "")).strip()
    if not validate_dict_id(dict_id):
        raise HTTPException(status_code=400, detail="Invalid dict_id")

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM dicts WHERE dict_id = ?", (dict_id,)).fetchone()
    disk_exists = dict_id_exists(dict_id)
    if existing or disk_exists:
        raise HTTPException(status_code=400, detail="Dict ID already exists")

    target_dir = dict_dir(dict_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    has_media = False

    try:
        (target_dir / "metadata.json").write_bytes(meta_content)
        (target_dir / "dictionary.db").write_bytes(await dictionary_file.read())
        (target_dir / "logo.png").write_bytes(await logo_file.read())
        if media_file and media_file.filename:
            (target_dir / "media.db").write_bytes(await media_file.read())
            has_media = True

        display_name = (meta.get("name") or "").strip() or dict_id
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO dicts (dict_id, user_id, name, has_media, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (dict_id, user["id"], display_name, int(has_media), now, now)
            )
        ver = next_version(dict_id)
        for fname in ["metadata.json", "dictionary.db", "logo.png"]:
            record_version(dict_id, ver, message, "file", fname)
        if has_media:
            record_version(dict_id, ver, message, "file", "media.db")

        return {"success": True, "dict_id": dict_id, "name": display_name}
    except Exception as e:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


# upload.dict.dxde.de 专用路由（绕过 Cloudflare，用于大文件上传）


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

    missing = [n for n, f in [("metadata_file", metadata_file), ("dictionary_file", dictionary_file), ("logo_file", logo_file)] if f is None]
    if missing:
        logger.warning(f"[upload_create_dict] missing fields: {missing}, all fields: {field_names}")
        raise HTTPException(status_code=422, detail=f"Missing required fields: {missing}. Received: {field_names}")

    return await create_dict(
        user=user,
        metadata_file=metadata_file,
        dictionary_file=dictionary_file,
        logo_file=logo_file,
        media_file=media_file,
        message=message,
    )


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

    return await update_dict(
        dict_id=dict_id,
        user=user,
        message=message,
        metadata_file=_get_file("metadata_file"),
        dictionary_file=_get_file("dictionary_file"),
        logo_file=_get_file("logo_file"),
        media_file=_get_file("media_file"),
    )


@app.delete("/user/dicts/{dict_id}")
async def delete_dict(dict_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        d = conn.execute(
            "SELECT * FROM dicts WHERE dict_id = ? AND user_id = ?", (dict_id, user["id"])
        ).fetchone()
    if not d:
        raise HTTPException(status_code=404, detail="Dict not found")
    shutil.rmtree(dict_dir(dict_id), ignore_errors=True)
    with get_db() as conn:
        conn.execute("DELETE FROM dicts WHERE dict_id = ?", (dict_id,))
    return {"success": True}


@app.post("/user/dicts/{dict_id}")
async def update_dict(
    dict_id: str,
    user: dict = Depends(get_current_user),
    message: str = Form(...),
    metadata_file: Optional[UploadFile] = File(None),
    dictionary_file: Optional[UploadFile] = File(None),
    logo_file: Optional[UploadFile] = File(None),
    media_file: Optional[UploadFile] = File(None),
):
    t0 = time.time()
    logger.info(f"[update_dict] START dict_id={dict_id} user={user.get('id')}")
    with get_db() as conn:
        d = conn.execute(
            "SELECT * FROM dicts WHERE dict_id = ? AND user_id = ?", (dict_id, user["id"])
        ).fetchone()
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
            logger.info(f"[update_dict] reading metadata_file elapsed={time.time()-t0:.1f}s")
            meta_content = await metadata_file.read()
            logger.info(f"[update_dict] metadata_file read done size={len(meta_content)} elapsed={time.time()-t0:.1f}s")
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
            logger.info(f"[update_dict] reading dictionary_file elapsed={time.time()-t0:.1f}s")
            data = await dictionary_file.read()
            logger.info(f"[update_dict] dictionary_file read done size={len(data)} elapsed={time.time()-t0:.1f}s")
            (target_dir / "dictionary.db").write_bytes(data)
            logger.info(f"[update_dict] dictionary_file write done elapsed={time.time()-t0:.1f}s")
            updated_files.append("dictionary.db")

        if logo_file and logo_file.filename:
            logger.info(f"[update_dict] reading logo_file elapsed={time.time()-t0:.1f}s")
            data = await logo_file.read()
            logger.info(f"[update_dict] logo_file read done size={len(data)} elapsed={time.time()-t0:.1f}s")
            (target_dir / "logo.png").write_bytes(data)
            updated_files.append("logo.png")

        if media_file and media_file.filename:
            logger.info(f"[update_dict] reading media_file elapsed={time.time()-t0:.1f}s")
            data = await media_file.read()
            logger.info(f"[update_dict] media_file read done size={len(data)} elapsed={time.time()-t0:.1f}s")
            (target_dir / "media.db").write_bytes(data)
            logger.info(f"[update_dict] media_file write done elapsed={time.time()-t0:.1f}s")
            has_media = True
            updated_files.append("media.db")

        if not updated_files:
            raise HTTPException(status_code=400, detail="No files provided for update")

        now = datetime.now(timezone.utc).isoformat()
        display_name = display_name if "display_name" in dir() else d["name"]
        with get_db() as conn:
            conn.execute(
                "UPDATE dicts SET name=?, has_media=?, updated_at=? WHERE dict_id=?",
                (display_name, int(has_media), now, dict_id)
            )

        ver = next_version(dict_id)
        for fname in updated_files:
            record_version(dict_id, ver, message, "file", fname)

        logger.info(f"[update_dict] DONE dict_id={dict_id} updated_files={updated_files} total={time.time()-t0:.1f}s")
        return {"success": True, "dict_id": dict_id, "version": ver, "updated_files": updated_files}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/user/dicts/{dict_id}/entries")
async def upsert_dict_entries(
    dict_id: str,
    user: dict = Depends(get_current_user),
    file: UploadFile = File(...),
    message: str = Form("更新条目"),
):
    with get_db() as conn:
        d = conn.execute(
            "SELECT * FROM dicts WHERE dict_id = ? AND user_id = ?", (dict_id, user["id"])
        ).fetchone()
    if not d:
        raise HTTPException(status_code=404, detail="Dict not found")

    db_path = dict_dir(dict_id) / "dictionary.db"
    if not db_path.exists():
        raise HTTPException(status_code=400, detail="dictionary.db not found")

    if not file.filename or not file.filename.endswith(".zst"):
        raise HTTPException(status_code=400, detail="File must be a .zst file")

    content = await file.read()

    dctx = zstd.ZstdDecompressor()
    try:
        decompressed = dctx.decompress(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decompress file: {e}")

    try:
        ver = next_version(dict_id)
        for i, line in enumerate(decompressed.decode("utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid JSON at line {i + 1}")
            upsert_entry_in_db(db_path, entry)
            eid = entry.get("entry_id")
            if eid is not None:
                record_version(dict_id, ver, message, "entry", "dictionary.db", int(eid))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Update metadata.json version and updatedAt
    metadata_path = dict_dir(dict_id) / "metadata.json"
    if metadata_path.exists():
        try:
            meta = parse_metadata(metadata_path)
            meta["version"] = ver
            meta["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            metadata_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update metadata.json: {e}")

    return {"success": True, "version": ver}


# ============ Update API ============

def _get_history_between(dict_id: str, from_ver: int, to_ver: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT DISTINCT version, message
               FROM version_history
               WHERE dict_id = ? AND version > ? AND version <= ?
               ORDER BY version ASC""",
            (dict_id, from_ver, to_ver)
        ).fetchall()

    return [{"v": r["version"], "m": r["message"]} for r in rows]


def _compute_required_files(dict_id: str, from_ver: int, to_ver: int) -> dict[str, list]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT version, change_type, file_name, entry_id
               FROM version_history
               WHERE dict_id = ? AND version > ? AND version <= ?
               ORDER BY version ASC""",
            (dict_id, from_ver, to_ver)
        ).fetchall()

    files_needed: set[str] = set()
    entries_needed: dict[int, None] = {}

    for r in rows:
        if r["change_type"] == "file":
            files_needed.add(r["file_name"])
            if r["file_name"] == "dictionary.db":
                entries_needed.clear()
        elif r["change_type"] == "entry":
            entries_needed[int(r["entry_id"])] = None

    return {
        "files": sorted(files_needed),
        "entries": list(entries_needed.keys()),
    }


@app.get("/update/{dict_id}")
async def get_updates(dict_id: str, from_ver: int = 0, to_ver: Optional[int] = None):
    dict_path = dict_dir(dict_id)
    if not dict_path.exists():
        raise HTTPException(status_code=404, detail=f"Dictionary '{dict_id}' not found")

    if to_ver is None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT MAX(version) FROM version_history WHERE dict_id = ?",
                (dict_id,)
            ).fetchone()
        to_ver = row[0] if row and row[0] is not None else 0

    history = _get_history_between(dict_id, from_ver, to_ver or 0)
    required = _compute_required_files(dict_id, from_ver, to_ver or 0)

    return {
        "dict_id": dict_id,
        "from": from_ver,
        "to": to_ver or 0,
        "history": history,
        "required": required,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
