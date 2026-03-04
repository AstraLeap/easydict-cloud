#!/usr/bin/env python3
"""
数据库迁移脚本：将旧的 'entry' change_type 转换为 'insert' 或 'update'

这个脚本需要手动配置，因为我们无法自动判断一个旧的 'entry' 记录是插入还是更新。
使用方式：
    1. 编辑此脚本，添加你知道的插入 entry 的版本号
    2. 运行此脚本以更新数据库
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "easydict-data" / "user" / "user.db"

# 配置：这里列出所有已知是"插入"的 entry（版本号和entry_id组合）
# 格式：(dict_id, version, entry_id)
KNOWN_INSERTS = [
    # 第一个版本的初始化 entries（词典刚创建时都是插入）
    ("ode_now", 1, 306517),
    ("testdict1", 4, 1),
    ("testdict1", 4, 2),
    
    # 新增的 entry（v33 新增）
    ("ode_now", 33, 999999),
]

def migrate():
    """执行迁移"""
    if not DB_PATH.exists():
        print(f"错误：找不到数据库文件 {DB_PATH}")
        return False
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    try:
        # 查询所有旧的 'entry' 类型记录
        cursor.execute("""
            SELECT id, dict_id, version, entry_id 
            FROM version_history 
            WHERE change_type = 'entry'
            ORDER BY version ASC
        """)
        old_entries = cursor.fetchall()
        
        if not old_entries:
            print("没有找到需要迁移的 'entry' 记录")
            return True
        
        print(f"找到 {len(old_entries)} 条 'entry' 记录需要迁移")
        print("\n现有的 'entry' 记录：")
        for id, dict_id, version, entry_id in old_entries:
            print(f"  - {dict_id} v{version} entry_id={entry_id}")
        
        print("\n要将这些记录转换为 'insert' 或 'update'，请编辑脚本顶部的 KNOWN_INSERTS 配置")
        print("并指定哪些是插入，其余的将被转换为更新。")
        
        # 更新已知的插入
        for dict_id, version, entry_id in KNOWN_INSERTS:
            cursor.execute("""
                UPDATE version_history 
                SET change_type = 'insert'
                WHERE dict_id = ? AND version = ? AND entry_id = ? AND change_type = 'entry'
            """, (dict_id, version, entry_id))
            print(f"✓ 标记为 insert: {dict_id} v{version} entry_id={entry_id}")
        
        # 将剩余的 'entry' 转换为 'update'
        cursor.execute("""
            UPDATE version_history 
            SET change_type = 'update'
            WHERE change_type = 'entry'
        """)
        print(f"✓ 将其他 {len(old_entries) - len(KNOWN_INSERTS)} 条记录标记为 update")
        
        conn.commit()
        print("\n迁移完成！")
        return True
        
    except Exception as e:
        print(f"错误：{e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    if not migrate():
        sys.exit(1)
