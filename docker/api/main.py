"""
EasyDict API Service
提供词典查询、列表获取和下载服务
"""

import os
import json
import logging
import sqlite3
import zipfile
import time
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager

import aiosqlite
import zstandard as zstd
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 配置日志
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@contextmanager
def performance_timer(operation_name: str, log_level: int = logging.INFO):
    """
    性能测量上下文管理器

    用法:
        with performance_timer("操作名称"):
            # 你的代码

    输出:
        [PERF] 操作名称: 123.45ms
    """
    start_time = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.log(log_level, f"[PERF] {operation_name}: {elapsed_ms:.2f}ms")

# 词典数据根目录
DICTIONARIES_PATH = Path(os.getenv("DICTIONARIES_PATH", "/data/dictionaries"))
# 辅助数据文件目录
AUXILIARY_PATH = Path(os.getenv("AUXILIARY_PATH", "/data/auxiliary"))
CACHE_PATH = Path(os.getenv("CACHE_PATH", "/tmp/easydict-cache"))

# 数据库连接缓存
_db_connections: Dict[str, aiosqlite.Connection] = {}
# Media 数据库连接缓存
_media_db_connections: Dict[str, aiosqlite.Connection] = {}
# Zstd 解压器缓存（每个词典一个，从 config 表的 zstd_dict 加载）
_zstd_decompressors: Dict[str, zstd.ZstdDecompressor] = {}

# ZIP 文件对象缓存
# 缓存打开的 ZipFile 对象，避免每次请求都重新打开 ZIP 文件
_zip_file_cache: Dict[str, zipfile.ZipFile] = {}
# ZIP 文件索引缓存
# 格式: {zip_path: {request_path: actual_path_in_zip}}
_zip_index_cache: Dict[str, Dict[str, str]] = {}
# ZIP 文件修改时间缓存（用于检测文件更新）
_zip_file_mtime_cache: Dict[str, float] = {}
# ZIP 文件数量缓存（直接存储文件数量，O(1) 查询）
_zip_file_count_cache: Dict[str, int] = {}

# 确保缓存目录存在
CACHE_PATH.mkdir(parents=True, exist_ok=True)



class DictionaryFileInfo(BaseModel):
    """词典文件信息"""
    name: str
    size: int
    modified: float


class DictionaryInfo(BaseModel):
    """词典信息模型"""
    id: str
    name: str
    version: int = 1
    entry_count: int = 0
    audio_count: int = 0
    image_count: int = 0
    dict_size: int = 0
    media_size: int = 0
    updated_at: Optional[str] = None


async def preload_zip_indexes():
    """
    预加载所有词典的 ZIP 文件索引

    在应用启动时扫描所有词典目录，为每个存在的 audios.zip 和 images.zip
    预构建索引并缓存。这样可以避免首次访问音频/图片文件时的延迟。

    性能影响:
    - 应用启动时间会增加（取决于 ZIP 文件大小和数量）
    - 但首次访问音频/图片文件时从 2000ms 降到 <1ms
    """
    if not DICTIONARIES_PATH.exists():
        logger.warning(f"Dictionaries path does not exist: {DICTIONARIES_PATH}")
        return

    logger.info("=" * 60)
    logger.info("开始预加载 ZIP 文件索引...")
    logger.info("=" * 60)

    preload_start = time.perf_counter()
    total_indexes = 0
    total_files = 0

    try:
        # 扫描所有词典目录
        for dict_path in DICTIONARIES_PATH.iterdir():
            if not dict_path.is_dir():
                continue

            dict_id = dict_path.name
            logger.info(f"处理词典: {dict_id}")

            # 检查并预加载 audios.zip
            audios_zip = dict_path / "audios.zip"
            if audios_zip.exists():
                try:
                    logger.info(f"  - 预加载音频索引: {audios_zip.name}")
                    index_start = time.perf_counter()
                    zip_index = await get_zip_index(audios_zip)
                    index_ms = (time.perf_counter() - index_start) * 1000
                    total_indexes += 1
                    total_files += len(zip_index)
                    logger.info(f"    ✓ 完成 | 索引条目: {len(zip_index):,} | 耗时: {index_ms:.2f}ms")
                except Exception as e:
                    logger.error(f"    ✗ 失败: {e}")

            # 检查并预加载 images.zip
            images_zip = dict_path / "images.zip"
            if images_zip.exists():
                try:
                    logger.info(f"  - 预加载图片索引: {images_zip.name}")
                    index_start = time.perf_counter()
                    zip_index = await get_zip_index(images_zip)
                    index_ms = (time.perf_counter() - index_start) * 1000
                    total_indexes += 1
                    total_files += len(zip_index)
                    logger.info(f"    ✓ 完成 | 索引条目: {len(zip_index):,} | 耗时: {index_ms:.2f}ms")
                except Exception as e:
                    logger.error(f"    ✗ 失败: {e}")

    except Exception as e:
        logger.error(f"预加载 ZIP 索引时出错: {e}")

    total_ms = (time.perf_counter() - preload_start) * 1000

    logger.info("=" * 60)
    logger.info(f"ZIP 索引预加载完成！")
    logger.info(f"  - 预加载索引数: {total_indexes}")
    logger.info(f"  - 总索引条目: {total_files:,}")
    logger.info(f"  - 总耗时: {total_ms:.2f}ms ({total_ms/1000:.2f}秒)")
    logger.info("=" * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"Starting EasyDict API Server")
    logger.info(f"Dictionaries path: {DICTIONARIES_PATH}")
    logger.info(f"Auxiliary path: {AUXILIARY_PATH}")
    logger.info(f"Cache path: {CACHE_PATH}")

    # 预加载所有 ZIP 文件索引
    await preload_zip_indexes()

    yield
    # 清理数据库连接
    for conn in _db_connections.values():
        await conn.close()
    # 清理 media 数据库连接
    for conn in _media_db_connections.values():
        await conn.close()
    # 关闭所有打开的 ZipFile 对象
    for zf in _zip_file_cache.values():
        try:
            zf.close()
        except:
            pass
    # 清理 ZIP 缓存
    _zip_file_cache.clear()
    _zip_index_cache.clear()
    _zip_file_count_cache.clear()
    _zip_file_mtime_cache.clear()
    # 清理 zstd 解压器缓存
    _zstd_decompressors.clear()
    logger.info("EasyDict API Server stopped")


app = FastAPI(
    title="EasyDict API",
    description="词典查询和下载服务 API",
    version="2.0.0",
    lifespan=lifespan
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


async def get_db_connection(dict_id: str) -> Optional[aiosqlite.Connection]:
    """获取词典数据库连接（带缓存）"""
    cache_key = dict_id

    if cache_key in _db_connections:
        return _db_connections[cache_key]

    db_path = DICTIONARIES_PATH / dict_id / "dictionary.db"

    if not db_path.exists():
        return None

    try:
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        _db_connections[cache_key] = conn
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database {db_path}: {e}")
        return None


async def get_db_connection_raw(dict_id: str) -> Optional[aiosqlite.Connection]:
    """获取词典数据库连接（不带 row_factory，用于聚合查询）"""
    db_path = DICTIONARIES_PATH / dict_id / "dictionary.db"

    if not db_path.exists():
        return None

    try:
        conn = await aiosqlite.connect(str(db_path))
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database {db_path}: {e}")
        return None


async def get_media_db_connection(dict_id: str) -> Optional[aiosqlite.Connection]:
    """获取 media.db 数据库连接（带缓存）"""
    cache_key = f"media_{dict_id}"

    if cache_key in _media_db_connections:
        return _media_db_connections[cache_key]

    media_db_path = DICTIONARIES_PATH / dict_id / "media.db"

    if not media_db_path.exists():
        return None

    try:
        conn = await aiosqlite.connect(str(media_db_path))
        conn.row_factory = aiosqlite.Row
        _media_db_connections[cache_key] = conn
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to media database {media_db_path}: {e}")
        return None


async def create_media_db(dict_id: str) -> bool:
    """
    创建 media.db 数据库和表结构

    Args:
        dict_id: 词典ID

    Returns:
        是否成功创建
    """
    media_db_path = DICTIONARIES_PATH / dict_id / "media.db"

    try:
        async with aiosqlite.connect(str(media_db_path)) as conn:
            # 创建 audios 表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audios (
                    name TEXT PRIMARY KEY,
                    blob BLOB NOT NULL
                )
            """)

            # 创建 images 表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS images (
                    name TEXT PRIMARY KEY,
                    blob BLOB NOT NULL
                )
            """)

            # 创建索引以提高查询性能
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_audios_name ON audios(name)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_images_name ON images(name)")

            await conn.commit()

        logger.info(f"Created media.db for dictionary '{dict_id}'")
        return True

    except Exception as e:
        logger.error(f"Failed to create media.db for {dict_id}: {e}")
        return False


async def migrate_zip_to_media_db(dict_id: str) -> bool:
    """
    将 audios.zip 和 images.zip 中的文件迁移到 media.db

    Args:
        dict_id: 词典ID

    Returns:
        是否成功迁移
    """
    dict_path = DICTIONARIES_PATH / dict_id
    audios_zip = dict_path / "audios.zip"
    images_zip = dict_path / "images.zip"

    # 检查是否有需要迁移的文件
    if not audios_zip.exists() and not images_zip.exists():
        logger.info(f"No zip files to migrate for dictionary '{dict_id}'")
        return True

    try:
        # 首先创建数据库
        if not await create_media_db(dict_id):
            logger.error(f"Failed to create media.db for {dict_id}")
            return False

        # 获取数据库连接
        conn = await get_media_db_connection(dict_id)
        if not conn:
            logger.error(f"Failed to connect to media.db for {dict_id}")
            return False

        # 迁移音频文件
        if audios_zip.exists():
            logger.info(f"Migrating audios.zip to media.db for '{dict_id}'")
            try:
                with zipfile.ZipFile(audios_zip, 'r') as zf:
                    for file_info in zf.filelist:
                        if file_info.is_dir():
                            continue

                        file_name = file_info.filename
                        # 只使用文件名，不包含路径
                        simple_name = file_name.split('/')[-1]

                        # 读取文件内容
                        file_data = zf.read(file_name)

                        # 插入数据库
                        await conn.execute(
                            "INSERT OR REPLACE INTO audios (name, blob) VALUES (?, ?)",
                            (simple_name, file_data)
                        )

                await conn.commit()
                logger.info(f"Successfully migrated audios from '{dict_id}'")
            except Exception as e:
                logger.error(f"Failed to migrate audios for {dict_id}: {e}")
                return False

        # 迁移图片文件
        if images_zip.exists():
            logger.info(f"Migrating images.zip to media.db for '{dict_id}'")
            try:
                with zipfile.ZipFile(images_zip, 'r') as zf:
                    for file_info in zf.filelist:
                        if file_info.is_dir():
                            continue

                        file_name = file_info.filename
                        # 只使用文件名，不包含路径
                        simple_name = file_name.split('/')[-1]

                        # 读取文件内容
                        file_data = zf.read(file_name)

                        # 插入数据库
                        await conn.execute(
                            "INSERT OR REPLACE INTO images (name, blob) VALUES (?, ?)",
                            (simple_name, file_data)
                        )

                await conn.commit()
                logger.info(f"Successfully migrated images from '{dict_id}'")
            except Exception as e:
                logger.error(f"Failed to migrate images for {dict_id}: {e}")
                return False

        logger.info(f"Successfully migrated media files for dictionary '{dict_id}'")
        return True

    except Exception as e:
        logger.error(f"Failed to migrate media files for {dict_id}: {e}")
        return False


async def count_files_in_media_db(dict_id: str, table_name: str) -> int:
    """
    统计 media.db 中的文件数量

    Args:
        dict_id: 词典ID
        table_name: 表名 ('audios' 或 'images')

    Returns:
        文件数量
    """
    conn = await get_media_db_connection(dict_id)
    if not conn:
        return 0

    try:
        cursor = await conn.execute(f"SELECT COUNT(*) as count FROM {table_name}")
        row = await cursor.fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"Failed to count files in {table_name}: {e}")
        return 0


async def get_zip_index(zip_path: Path) -> Dict[str, str]:
    """
    获取 ZIP 文件路径索引（带缓存）

    构建 {请求路径: ZIP内实际路径} 的映射字典
    例如: {'word.mp3': 'audios/word.mp3', 'word': 'audios/word.mp3'}

    性能优化:
    - 首次调用: 打开 ZIP 文件，解析 central directory，构建索引，并保持 ZipFile 对象打开
    - 后续调用: 直接使用已打开的 ZipFile 对象和缓存的索引，O(1) 查找
    - 自动更新: 检测文件修改时间，变化时重新打开 ZIP 并重建索引

    Args:
        zip_path: ZIP 文件路径

    Returns:
        路径映射字典 {request_path: actual_path_in_zip}
    """
    total_start = time.perf_counter()

    cache_key = str(zip_path)

    # 检查文件是否存在
    with performance_timer(f"检查 ZIP 文件存在: {zip_path.name}"):
        if not zip_path.exists():
            raise HTTPException(status_code=404, detail=f"Zip file not found: {zip_path}")

    # 获取当前文件修改时间
    try:
        with performance_timer(f"获取文件修改时间: {zip_path.name}"):
            current_mtime = zip_path.stat().st_mtime
    except Exception as e:
        logger.error(f"Failed to get mtime for {zip_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to access zip file")

    # 检查缓存是否有效
    cache_check_start = time.perf_counter()
    if cache_key in _zip_file_cache:
        if _zip_file_mtime_cache.get(cache_key) == current_mtime:
            # 缓存命中，直接返回
            cache_check_ms = (time.perf_counter() - cache_check_start) * 1000
            logger.info(f"[PERF] ZIP 文件对象缓存命中: {cache_check_ms:.2f}ms")
            logger.debug(f"ZIP file cache hit for {zip_path.name}")
            return _zip_index_cache[cache_key]
        else:
            logger.info(f"ZIP file {zip_path.name} has been modified, reopening...")
            # 关闭旧的 ZipFile
            try:
                _zip_file_cache[cache_key].close()
            except:
                pass
            del _zip_file_cache[cache_key]

    # 缓存未命中或文件已更新，重新打开 ZIP 并构建索引
    logger.info(f"Opening ZIP file and building index for {zip_path.name}...")

    index = {}  # {请求路径: 实际路径}
    file_count = 0  # 实际文件数量（排除目录）

    try:
        with performance_timer(f"打开并解析 ZIP 文件: {zip_path.name}"):
            # 打开 ZIP 文件并保持打开状态
            zf = zipfile.ZipFile(zip_path, 'r')

            with performance_timer(f"遍历 ZIP 文件列表"):
                namelist = zf.namelist()

            with performance_timer(f"构建索引映射 ({len(namelist)} 个文件)"):
                # 遍历 ZIP 中的所有文件
                for name in namelist:
                    if name.endswith('/'):  # 跳过目录项
                        continue

                    # 统计实际文件数量
                    file_count += 1

                    # 为每个文件创建多个访问路径的映射
                    # 这样无论客户端请求什么路径格式都能找到

                    # 1. 完整路径映射
                    index[name] = name

                    # 2. 只有文件名的映射（最常用）
                    filename = name.split('/')[-1]
                    if filename:  # 确保文件名不为空
                        index[filename] = name

                    # 3. 去除可能的目录前缀
                    parts = name.split('/')
                    if len(parts) > 1:
                        # 去除第一层目录前缀
                        short_path = '/'.join(parts[1:])
                        index[short_path] = name

                        # 去除两层目录前缀（双重前缀情况）
                        if len(parts) > 2:
                            short_path2 = '/'.join(parts[2:])
                            index[short_path2] = name

        # 缓存 ZipFile 对象、索引、文件数量和修改时间
        with performance_timer("缓存 ZipFile 对象和索引到内存"):
            _zip_file_cache[cache_key] = zf  # 保持 ZipFile 打开！
            _zip_index_cache[cache_key] = index
            _zip_file_count_cache[cache_key] = file_count  # 缓存文件数量
            _zip_file_mtime_cache[cache_key] = current_mtime

        total_ms = (time.perf_counter() - total_start) * 1000
        logger.info(f"[PERF] ZIP 文件打开和索引构建总耗时: {total_ms:.2f}ms | 文件: {zip_path.name} | 文件数: {file_count} | 索引条目: {len(index)}")
        return index

    except zipfile.BadZipFile as e:
        logger.error(f"Invalid ZIP file {zip_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Invalid ZIP file: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to open ZIP file {zip_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to open ZIP file: {str(e)}")


def parse_json_field(value: Optional[str]) -> Any:
    """解析 JSON 字段"""
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


async def get_zstd_decompressor(dict_id: str) -> Optional[zstd.ZstdDecompressor]:
    """获取词典的 zstd 解压器（带缓存），从 config 表读取压缩字典"""
    if dict_id in _zstd_decompressors:
        return _zstd_decompressors[dict_id]

    conn = await get_db_connection(dict_id)
    if conn is None:
        return None

    try:
        cursor = await conn.execute(
            "SELECT value FROM config WHERE key = 'zstd_dict'"
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row and row[0]:
            zdict = zstd.ZstdCompressionDict(bytes(row[0]))
            dctx = zstd.ZstdDecompressor(dict_data=zdict)
            _zstd_decompressors[dict_id] = dctx
            return dctx
    except Exception as e:
        logger.warning(f"No zstd dict for '{dict_id}', falling back to plain decompressor: {e}")

    # Fallback: no training dict
    dctx = zstd.ZstdDecompressor()
    _zstd_decompressors[dict_id] = dctx
    return dctx


def decompress_json_data(data: bytes, dctx: Optional[zstd.ZstdDecompressor]) -> Any:
    """解压 json_data BLOB 并解析为对象；若解压失败则直接 json.loads"""
    if data is None:
        return {}
    raw = bytes(data)
    # Try zstd decompression
    if dctx is not None:
        try:
            raw = dctx.decompress(raw)
        except Exception:
            pass  # Not compressed (or wrong dict) – use as-is
    try:
        return json.loads(raw)
    except Exception:
        return {}



def get_directory_size(path: Path) -> int:
    """获取目录总大小"""
    total = 0
    if path.exists():
        for item in path.rglob('*'):
            if item.is_file():
                total += item.stat().st_size
    return total


def count_files_in_directory(path: Path) -> int:
    """统计目录中的所有文件数量（不区分扩展名）"""
    if not path.exists():
        return 0
    count = 0
    for item in path.iterdir():
        if item.is_file():
            count += 1
    return count


async def count_files_in_zip_index(zip_path: Path) -> int:
    """
    从缓存中获取 ZIP 文件数量（O(1) 查询）

    性能优化：文件数量在预加载 ZIP 索引时已经统计并缓存，直接读取即可

    Args:
        zip_path: ZIP 文件路径

    Returns:
        文件数量
    """
    cache_key = str(zip_path)

    # 检查缓存中是否有该 ZIP 文件的文件数量
    if cache_key in _zip_file_count_cache:
        # O(1) 直接从缓存读取文件数量
        return _zip_file_count_cache[cache_key]

    # 缓存中没有，先加载索引（会自动统计并缓存文件数量）
    try:
        await get_zip_index(zip_path)
        # 加载完成后，文件数量已经缓存
        return _zip_file_count_cache.get(cache_key, 0)
    except Exception as e:
        # ZIP 文件不存在或加载失败
        logger.error(f"Failed to load ZIP index for {zip_path.name}: {e}")
        return 0


async def get_dictionary_info(dict_id: str) -> Optional[DictionaryInfo]:
    """获取词典详细信息"""
    dict_path = DICTIONARIES_PATH / dict_id
    
    if not dict_path.exists() or not dict_path.is_dir():
        return None
    
    metadata = {}
    metadata_path = dict_path / "metadata.json"
    if metadata_path.exists():
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read metadata for {dict_id}: {e}")
    
    db_path = dict_path / "dictionary.db"
    media_db_path = dict_path / "media.db"
    audios_path = dict_path / "audios"
    images_path = dict_path / "images"

    entry_count = 0
    if db_path.exists():
        try:
            conn = await get_db_connection_raw(dict_id)
            if conn:
                cursor = await conn.execute("SELECT COUNT(DISTINCT headword) as count FROM entries")
                row = await cursor.fetchone()
                entry_count = row[0] if row else 0
                await conn.close()
        except Exception as e:
            logger.warning(f"Failed to count entries for {dict_id}: {e}")

    dict_size = db_path.stat().st_size if db_path.exists() else 0
    media_size = media_db_path.stat().st_size if media_db_path.exists() else 0

    audio_count = 0
    if media_db_path.exists():
        audio_count = await count_files_in_media_db(dict_id, 'audios')
    elif audios_path.exists():
        audio_count = count_files_in_directory(audios_path)

    image_count = 0
    if media_db_path.exists():
        image_count = await count_files_in_media_db(dict_id, 'images')
    elif images_path.exists():
        image_count = count_files_in_directory(images_path)

    stat = dict_path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

    return DictionaryInfo(
        id=dict_id,
        name=metadata.get('name', dict_id),
        version=metadata.get('version', 1),
        entry_count=entry_count,
        audio_count=audio_count,
        image_count=image_count,
        dict_size=dict_size,
        media_size=media_size,
        updated_at=updated_at
    )


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy", "service": "easydict-api"}


ALLOWED_FILES = {
    "logo.png":      ("image/png",                 2592000),  # 缓存30天
    "metadata.json": ("application/json",           86400),   # 缓存1天
    "dictionary.db": ("application/vnd.sqlite3",    86400),   # 缓存1天
    "media.db":      ("application/vnd.sqlite3",    2592000), # 缓存30天
}


@app.get("/download/{dict_id}/file/{filename}")
async def download_file(dict_id: str, filename: str):
    """下载词典文件"""
    if filename not in ALLOWED_FILES:
        raise HTTPException(status_code=400, detail=f"File '{filename}' not allowed")

    file_path = DICTIONARIES_PATH / dict_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found for dictionary '{dict_id}'")

    media_type, max_age = ALLOWED_FILES[filename]
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename,
        headers={
            "Cache-Control": f"public, max-age={max_age}"
        }
    )


class EntryIdsRequest(BaseModel):
    entries: list[int]


@app.post("/download/{dict_id}/entries")
async def download_entries_batch(dict_id: str, data: EntryIdsRequest):
    """按 entry_id 列表批量下载条目，返回 .zst 压缩的 JSONL 文件"""
    dict_path = DICTIONARIES_PATH / dict_id
    if not dict_path.exists():
        raise HTTPException(status_code=404, detail=f"Dictionary '{dict_id}' not found")

    db_path = dict_path / "dictionary.db"
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="dictionary.db not found")

    if not data.entries:
        raise HTTPException(status_code=400, detail="No entries provided")

    entry_ids_str = [str(eid) for eid in data.entries]

    dctx = await get_zstd_decompressor(dict_id)

    conn = sqlite3.connect(str(db_path))
    placeholders = ",".join("?" * len(entry_ids_str))
    rows = conn.execute(
        f"SELECT entry_id, json_data FROM entries WHERE entry_id IN ({placeholders})",
        entry_ids_str
    ).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="No entries found")

    jsonl_lines = []
    for row in rows:
        entry_json = decompress_json_data(row[1], dctx)
        jsonl_lines.append(json.dumps(entry_json, ensure_ascii=False))

    jsonl_bytes = "\n".join(jsonl_lines).encode("utf-8")
    cctx = zstd.ZstdCompressor(level=3)
    compressed = cctx.compress(jsonl_bytes)

    return StreamingResponse(
        iter([compressed]),
        media_type="application/zstd",
        headers={
            "Content-Disposition": f'attachment; filename="entries.zst"',
            "Cache-Control": "no-cache",
        }
    )



@app.get("/word/{dict_id}/{word}")
async def query_word(dict_id: str, word: str, request: Request):
    """查询单词接口"""
    logger.info(f"Querying word '{word}' in dictionary '{dict_id}'")

    conn = await get_db_connection(dict_id)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"Dictionary '{dict_id}' not found")

    try:
        cursor = await conn.execute(
            """
            SELECT * FROM entries
            WHERE headword = ?
               OR headword LIKE ?
            ORDER BY
                CASE WHEN headword = ? THEN 0 ELSE 1 END,
                headword
            LIMIT 50
            """,
            (word, f"{word}%", word)
        )

        rows = await cursor.fetchall()
        await cursor.close()

        dctx = await get_zstd_decompressor(dict_id)
        entries = [decompress_json_data(row['json_data'], dctx) for row in rows]

        return JSONResponse({
            "dict_id": dict_id,
            "word": word,
            "entries": entries,
            "total": len(entries)
        })
    except Exception as e:
        logger.error(f"Error querying word '{word}': {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/entry/{dict_id}/{entry_id}")
async def query_entry(dict_id: str, entry_id: int):
    """查询单个词条接口"""
    conn = await get_db_connection(dict_id)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"Dictionary '{dict_id}' not found")

    try:
        cursor = await conn.execute(
            "SELECT json_data FROM entries WHERE entry_id = ?",
            (entry_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            raise HTTPException(status_code=404, detail=f"Entry '{entry_id}' not found")

        dctx = await get_zstd_decompressor(dict_id)
        return JSONResponse(decompress_json_data(row['json_data'], dctx))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying entry '{entry_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/dictionaries")
async def list_dictionaries():
    """
    获取词典商店列表
    返回所有可用词典的详细信息
    """
    dictionaries = []
    
    if not DICTIONARIES_PATH.exists():
        return {"dictionaries": dictionaries}
    
    for item in DICTIONARIES_PATH.iterdir():
        if item.is_dir():
            dict_info = await get_dictionary_info(item.name)
            if dict_info:
                dictionaries.append(dict_info.dict())
    
    # 按名称排序
    dictionaries.sort(key=lambda x: x['name'])

    return {"dictionaries": dictionaries}


async def get_file_from_zip(zip_path: Path, file_path: str, media_type: str, filename: str):
    """
    从 zip 文件中提取单个文件并返回（使用缓存的 ZipFile 对象）

    性能保证：
    - 使用已打开并缓存的 ZipFile 对象，不需要每次重新打开
    - 使用缓存的 ZIP 索引，O(1) 路径查找
    - 不会读取整个 zip 文件
    - 不会将整个目标文件读入内存
    - 使用生成器逐块流式返回
    - 内存占用恒定 O(64KB)，与文件大小无关

    性能提升：
    - 服务启动后: ZIP 文件已打开，索引已构建
    - 首次访问: <1ms (直接使用缓存的 ZipFile 对象) ⚡⚡⚡
    """
    request_start = time.perf_counter()
    logger.info(f"[REQUEST] 开始处理 ZIP 文件请求: {zip_path.name}/{file_path}")

    try:
        # 🚀 使用缓存的索引，O(1) 查找！
        get_index_start = time.perf_counter()
        zip_index = await get_zip_index(zip_path)
        get_index_ms = (time.perf_counter() - get_index_start) * 1000
        logger.info(f"[PERF] 获取 ZIP 索引耗时: {get_index_ms:.2f}ms")

        # 在字典中查找，O(1) 复杂度
        lookup_start = time.perf_counter()
        if file_path not in zip_index:
            raise HTTPException(
                status_code=404,
                detail=f"File '{file_path}' not found in zip archive '{zip_path.name}'"
            )
        target_path = zip_index[file_path]
        lookup_ms = (time.perf_counter() - lookup_start) * 1000
        logger.info(f"[PERF] 路径查找耗时: {lookup_ms:.2f}ms | 目标路径: {target_path}")

        # 获取缓存的 ZipFile 对象
        cache_key = str(zip_path)
        zf = _zip_file_cache.get(cache_key)
        if not zf:
            # 这不应该发生，因为 get_zip_index 应该已经打开并缓存了
            raise HTTPException(
                status_code=500,
                detail=f"ZipFile object not found in cache for {zip_path.name}"
            )

        # 创建流式生成器，使用缓存的 ZipFile 对象
        async def file_iterator():
            """异步生成器，逐块读取文件内容"""
            iter_start = time.perf_counter()
            chunk_count = 0
            total_bytes = 0

            # 🚀 直接使用已打开的 ZipFile 对象，不需要重新打开！
            open_start = time.perf_counter()
            with zf.open(target_path) as f:
                open_ms = (time.perf_counter() - open_start) * 1000
                logger.info(f"[PERF] 打开 ZIP 内文件耗时: {open_ms:.2f}ms")

                while True:
                    chunk = f.read(65536)  # 每次只读 64KB
                    if not chunk:
                        break
                    chunk_count += 1
                    total_bytes += len(chunk)
                    yield chunk

            iter_ms = (time.perf_counter() - iter_start) * 1000
            logger.info(f"[PERF] 文件流式读取完成 | 块数: {chunk_count} | 字节: {total_bytes} | 耗时: {iter_ms:.2f}ms")

        total_prepare_ms = (time.perf_counter() - request_start) * 1000
        logger.info(f"[PERF] 响应准备完成，开始流式传输 | 总准备耗时: {total_prepare_ms:.2f}ms")

        return StreamingResponse(
            file_iterator(),
            media_type=media_type,
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "public, max-age=2592000"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading from zip file {zip_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read file from zip: {str(e)}")


def get_media_type(filename: str) -> str:
    """根据文件扩展名获取 MIME 类型"""
    ext = filename.split('.')[-1].lower()
    media_types = {
        'mp3': 'audio/mpeg',
        'wav': 'audio/wav',
        'ogg': 'audio/ogg',
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'webp': 'image/webp'
    }
    return media_types.get(ext, 'application/octet-stream')


@app.get("/audio/{dict_id}/{file_path:path}")
async def get_audio_file(dict_id: str, file_path: str):
    """
    获取单个音频文件
    如果 media.db 存在，则从数据库中读取
    否则兼容旧的目录结构
    """
    request_start = time.perf_counter()
    logger.info(f"===== [AUDIO REQUEST] 开始处理音频请求 | 词典: {dict_id} | 文件: {file_path} =====")

    dict_path = DICTIONARIES_PATH / dict_id
    if not dict_path.exists():
        raise HTTPException(status_code=404, detail=f"Dictionary '{dict_id}' not found")

    media_type = get_media_type(file_path)

    # 优先从 media.db 数据库中读取
    media_db_path = dict_path / "media.db"
    if media_db_path.exists():
        logger.info(f"[AUDIO] 从 media.db 数据库读取: {file_path}")
        try:
            conn = await get_media_db_connection(dict_id)
            if not conn:
                raise HTTPException(status_code=500, detail="Failed to connect to media database")

            # 查询音频文件
            cursor = await conn.execute(
                "SELECT blob FROM audios WHERE name = ?",
                (file_path,)
            )
            row = await cursor.fetchone()
            await cursor.close()

            if not row:
                raise HTTPException(status_code=404, detail=f"Audio file '{file_path}' not found in database")

            # 获取 blob 数据
            blob_data = row[0]

            # 创建流式生成器（不缓存文件内容，每次都从数据库读取）
            async def audio_iterator():
                chunk_size = 65536  # 64KB
                for i in range(0, len(blob_data), chunk_size):
                    yield blob_data[i:i + chunk_size]

            total_ms = (time.perf_counter() - request_start) * 1000
            logger.info(f"===== [AUDIO REQUEST] 从数据库返回 | 总耗时: {total_ms:.2f}ms =====")

            return StreamingResponse(
                audio_iterator(),
                media_type=media_type,
                headers={
                    "Content-Disposition": f'inline; filename="{file_path}"',
                    "Cache-Control": "public, max-age=2592000"  # 缓存30天
                }
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[AUDIO] 从数据库读取失败: {e}")
            # 继续尝试从目录读取

    # 兼容旧的目录结构
    logger.info(f"[AUDIO] 从目录读取: {file_path}")
    audios_path = dict_path / "audios"
    audio_file = audios_path / file_path
    if audio_file.exists() and audio_file.is_file():
        response = FileResponse(
            path=str(audio_file),
            media_type=media_type,
            headers={
                "Cache-Control": "public, max-age=2592000"  # 缓存30天
            }
        )
        total_ms = (time.perf_counter() - request_start) * 1000
        logger.info(f"===== [AUDIO REQUEST] 从目录返回 | 总耗时: {total_ms:.2f}ms =====")
        return response

    raise HTTPException(status_code=404, detail=f"Audio file '{file_path}' not found")


@app.get("/image/{dict_id}/{file_path:path}")
async def get_image_file(dict_id: str, file_path: str):
    """
    获取单个图片文件
    如果 media.db 存在，则从数据库中读取
    否则兼容旧的目录结构
    """
    dict_path = DICTIONARIES_PATH / dict_id
    if not dict_path.exists():
        raise HTTPException(status_code=404, detail=f"Dictionary '{dict_id}' not found")

    media_type = get_media_type(file_path)

    # 优先从 media.db 数据库中读取
    media_db_path = dict_path / "media.db"
    if media_db_path.exists():
        try:
            conn = await get_media_db_connection(dict_id)
            if not conn:
                raise HTTPException(status_code=500, detail="Failed to connect to media database")

            # 查询图片文件
            cursor = await conn.execute(
                "SELECT blob FROM images WHERE name = ?",
                (file_path,)
            )
            row = await cursor.fetchone()
            await cursor.close()

            if not row:
                raise HTTPException(status_code=404, detail=f"Image file '{file_path}' not found in database")

            # 获取 blob 数据
            blob_data = row[0]

            # 创建流式生成器（不缓存文件内容，每次都从数据库读取）
            async def image_iterator():
                chunk_size = 65536  # 64KB
                for i in range(0, len(blob_data), chunk_size):
                    yield blob_data[i:i + chunk_size]

            return StreamingResponse(
                image_iterator(),
                media_type=media_type,
                headers={
                    "Content-Disposition": f'inline; filename="{file_path}"',
                    "Cache-Control": "public, max-age=2592000"  # 缓存30天
                }
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[IMAGE] 从数据库读取失败: {e}")
            # 继续尝试从目录读取

    # 兼容旧的目录结构
    images_path = dict_path / "images"
    image_file = images_path / file_path
    if image_file.exists() and image_file.is_file():
        return FileResponse(
            path=str(image_file),
            media_type=media_type,
            headers={
                "Cache-Control": "public, max-age=2592000"  # 缓存30天
            }
        )

    raise HTTPException(status_code=404, detail=f"Image file '{file_path}' not found")


@app.get("/auxi/{filename:path}")
async def get_auxiliary_file(filename: str):
    """
    获取辅助数据文件
    支持批量下载辅助目录中的任何文件

    Examples:
        GET /auxi/en.db - 下载 en.db 文件
        GET /auxi/cn.db - 下载 cn.db 文件
        GET /auxi/data/config.json - 下载 data/config.json
    """
    logger.info(f"[AUXI] Requesting auxiliary file: {filename}")

    # 安全检查：确保文件名不包含路径遍历攻击
    if '..' in filename or filename.startswith('/'):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename. Path traversal is not allowed."
        )

    # 构建文件路径
    file_path = AUXILIARY_PATH / filename

    # 检查文件是否存在且是文件（不是目录）
    if not file_path.exists() or not file_path.is_file():
        logger.warning(f"[AUXI] File not found: {file_path}")
        raise HTTPException(
            status_code=404,
            detail=f"Auxiliary file '{filename}' not found"
        )

    # 获取 MIME 类型
    media_type = get_media_type(filename)

    logger.info(f"[AUXI] Serving file: {file_path} ({media_type})")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename,
        headers={
            "Cache-Control": "public, max-age=86400"  # 缓存1天
        }
    )


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
