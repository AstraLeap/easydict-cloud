#!/usr/bin/env python3
"""
将词典的 audios.zip 和 images.zip 迁移到 media.db 数据库

使用方法:
    python migrate_to_media_db.py [dict_id]

    如果不指定 dict_id，则迁移所有词典
    如果指定 dict_id，则只迁移指定的词典
"""

import os
import sys
import logging
import zipfile
from pathlib import Path
from typing import Optional

import sqlite3

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 词典数据根目录
DICTIONARIES_PATH = Path(os.getenv("DICTIONARIES_PATH", "/data/dictionaries"))


def create_media_db(dict_path: Path) -> bool:
    """
    创建 media.db 数据库和表结构

    Args:
        dict_path: 词典目录路径

    Returns:
        是否成功创建
    """
    media_db_path = dict_path / "media.db"

    try:
        conn = sqlite3.connect(str(media_db_path))

        # 创建 audios 表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audios (
                name TEXT PRIMARY KEY,
                blob BLOB NOT NULL
            )
        """)

        # 创建 images 表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS images (
                name TEXT PRIMARY KEY,
                blob BLOB NOT NULL
            )
        """)

        # 创建索引以提高查询性能
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audios_name ON audios(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_name ON images(name)")

        conn.commit()
        conn.close()

        logger.info(f"✓ 创建 media.db 成功: {media_db_path}")
        return True

    except Exception as e:
        logger.error(f"✗ 创建 media.db 失败 {media_db_path}: {e}")
        return False


def migrate_zip_to_media_db(dict_path: Path, dict_id: str) -> bool:
    """
    将 audios.zip 和 images.zip 中的文件迁移到 media.db

    Args:
        dict_path: 词典目录路径
        dict_id: 词典ID

    Returns:
        是否成功迁移
    """
    audios_zip = dict_path / "audios.zip"
    images_zip = dict_path / "images.zip"
    media_db_path = dict_path / "media.db"

    # 检查是否有需要迁移的文件
    if not audios_zip.exists() and not images_zip.exists():
        logger.info(f"  没有 zip 文件需要迁移: {dict_id}")
        return True

    try:
        # 首先创建数据库
        if not create_media_db(dict_path):
            logger.error(f"  ✗ 创建 media.db 失败: {dict_id}")
            return False

        # 获取数据库连接
        conn = sqlite3.connect(str(media_db_path))

        # 迁移音频文件
        if audios_zip.exists():
            logger.info(f"  → 迁移音频文件: {audios_zip.name}")
            try:
                with zipfile.ZipFile(audios_zip, 'r') as zf:
                    audio_count = 0
                    for file_info in zf.filelist:
                        if file_info.is_dir():
                            continue

                        file_name = file_info.filename
                        # 只使用文件名，不包含路径
                        simple_name = file_name.split('/')[-1]

                        # 读取文件内容
                        file_data = zf.read(file_name)

                        # 插入数据库
                        conn.execute(
                            "INSERT OR REPLACE INTO audios (name, blob) VALUES (?, ?)",
                            (simple_name, file_data)
                        )
                        audio_count += 1

                conn.commit()
                logger.info(f"  ✓ 音频迁移完成: {audio_count} 个文件")
            except Exception as e:
                logger.error(f"  ✗ 音频迁移失败: {e}")
                conn.close()
                return False

        # 迁移图片文件
        if images_zip.exists():
            logger.info(f"  → 迁移图片文件: {images_zip.name}")
            try:
                with zipfile.ZipFile(images_zip, 'r') as zf:
                    image_count = 0
                    for file_info in zf.filelist:
                        if file_info.is_dir():
                            continue

                        file_name = file_info.filename
                        # 只使用文件名，不包含路径
                        simple_name = file_name.split('/')[-1]

                        # 读取文件内容
                        file_data = zf.read(file_name)

                        # 插入数据库
                        conn.execute(
                            "INSERT OR REPLACE INTO images (name, blob) VALUES (?, ?)",
                            (simple_name, file_data)
                        )
                        image_count += 1

                conn.commit()
                logger.info(f"  ✓ 图片迁移完成: {image_count} 个文件")
            except Exception as e:
                logger.error(f"  ✗ 图片迁移失败: {e}")
                conn.close()
                return False

        conn.close()

        # 统计迁移结果
        if media_db_path.exists():
            size_mb = media_db_path.stat().st_size / (1024 * 1024)
            logger.info(f"  ✓ media.db 大小: {size_mb:.2f} MB")

        logger.info(f"  ✓ 迁移完成: {dict_id}")
        return True

    except Exception as e:
        logger.error(f"  ✗ 迁移失败 {dict_id}: {e}")
        return False


def migrate_all_dictionaries():
    """迁移所有词典"""
    if not DICTIONARIES_PATH.exists():
        logger.error(f"词典目录不存在: {DICTIONARIES_PATH}")
        return

    logger.info("=" * 60)
    logger.info("开始迁移所有词典的媒体文件...")
    logger.info(f"词典目录: {DICTIONARIES_PATH}")
    logger.info("=" * 60)

    success_count = 0
    fail_count = 0
    total_count = 0

    # 扫描所有词典目录
    for dict_path in DICTIONARIES_PATH.iterdir():
        if not dict_path.is_dir():
            continue

        dict_id = dict_path.name
        total_count += 1

        logger.info(f"\n处理词典: {dict_id}")

        if migrate_zip_to_media_db(dict_path, dict_id):
            success_count += 1
        else:
            fail_count += 1

    logger.info("\n" + "=" * 60)
    logger.info(f"迁移完成！")
    logger.info(f"  总计: {total_count} 个词典")
    logger.info(f"  成功: {success_count} 个")
    logger.info(f"  失败: {fail_count} 个")
    logger.info("=" * 60)


def migrate_single_dictionary(dict_id: str):
    """迁移单个词典"""
    dict_path = DICTIONARIES_PATH / dict_id

    if not dict_path.exists() or not dict_path.is_dir():
        logger.error(f"词典不存在: {dict_id}")
        return

    logger.info("=" * 60)
    logger.info(f"开始迁移词典: {dict_id}")
    logger.info(f"词典路径: {dict_path}")
    logger.info("=" * 60)

    if migrate_zip_to_media_db(dict_path, dict_id):
        logger.info(f"\n✓ 词典 '{dict_id}' 迁移成功！")
    else:
        logger.error(f"\n✗ 词典 '{dict_id}' 迁移失败！")


def main():
    """主函数"""
    if len(sys.argv) > 1:
        # 迁移指定的词典
        dict_id = sys.argv[1]
        migrate_single_dictionary(dict_id)
    else:
        # 迁移所有词典
        migrate_all_dictionaries()


if __name__ == "__main__":
    main()
