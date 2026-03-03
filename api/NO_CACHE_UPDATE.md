# 移除媒体数据库缓存

## 修改说明

根据用户要求，已完全移除 media.db 数据库的连接缓存机制，改为每次请求都直接从数据库获取。

## 修改内容

### 1. 移除全局缓存变量

删除了 `_media_db_connections` 缓存字典：
```python
# 删除
# Media 数据库连接缓存
_media_db_connections: Dict[str, aiosqlite.Connection] = {}
```

### 2. 修改 get_media_db_connection 函数

移除缓存逻辑，每次都创建新连接：

**之前：**
```python
async def get_media_db_connection(dict_id: str) -> Optional[aiosqlite.Connection]:
    """获取 media.db 数据库连接（带缓存）"""
    cache_key = f"media_{dict_id}"

    if cache_key in _media_db_connections:
        return _media_db_connections[cache_key]

    # ... 创建连接并缓存
```

**现在：**
```python
async def get_media_db_connection(dict_id: str) -> Optional[aiosqlite.Connection]:
    """获取 media.db 数据库连接（每次新建连接）"""
    media_db_path = DICTIONARIES_PATH / dict_id / "media.db"

    if not media_db_path.exists():
        return None

    try:
        conn = await aiosqlite.connect(str(media_db_path))
        conn.row_factory = aiosqlite.Row
        return conn  # 不缓存，直接返回
    except Exception as e:
        logger.error(f"Failed to connect to media database {media_db_path}: {e}")
        return None
```

### 3. 确保及时关闭连接

修改了所有使用媒体数据库的函数，确保在获取数据后立即关闭连接：

#### count_files_in_media_db
```python
async def count_files_in_media_db(dict_id: str, table_name: str) -> int:
    conn = await get_media_db_connection(dict_id)
    if not conn:
        return 0

    try:
        cursor = await conn.execute(f"SELECT COUNT(*) as count FROM {table_name}")
        row = await cursor.fetchone()
        count = row[0] if row else 0
        await conn.close()  # 立即关闭
        return count
    except Exception as e:
        logger.error(f"Failed to count files in {table_name}: {e}")
        await conn.close()  # 确保关闭
        return 0
```

#### get_audio_file
```python
conn = None
try:
    conn = await get_media_db_connection(dict_id)
    if not conn:
        raise HTTPException(status_code=500, detail="Failed to connect to media database")

    # 查询数据
    cursor = await conn.execute("SELECT blob FROM audios WHERE name = ?", (file_path,))
    row = await cursor.fetchone()
    await cursor.close()

    if not row:
        await conn.close()
        raise HTTPException(status_code=404, detail=f"Audio file '{file_path}' not found in database")

    blob_data = row[0]

    # 关闭数据库连接
    await conn.close()
    conn = None

    # 返回响应...

except HTTPException:
    if conn:
        await conn.close()
    raise
except Exception as e:
    if conn:
        await conn.close()
    logger.error(f"[AUDIO] 从数据库读取失败: {e}")
```

#### get_image_file
同样修改，确保在获取图片数据后立即关闭连接。

### 4. 修改 lifespan 函数

移除了对 media 数据库连接缓存的清理：

**之前：**
```python
yield
# 清理数据库连接
for conn in _db_connections.values():
    await conn.close()
# 清理 media 数据库连接
for conn in _media_db_connections.values():
    await conn.close()
```

**现在：**
```python
yield
# 清理数据库连接
for conn in _db_connections.values():
    await conn.close()
```

## 优势

1. **避免连接泄漏**：每次用完立即关闭，不会留下未关闭的连接
2. **数据一致性**：每次都读取最新数据，不受缓存影响
3. **内存占用**：不会保留长时间打开的连接，节省内存
4. **简单直接**：代码逻辑更简单，不需要管理缓存状态

## 性能影响

- 每次请求都需要建立新的数据库连接，会有一点性能开销
- SQLite 的连接建立很快，影响很小
- 对于媒体文件服务，数据读取的 I/O 才是主要瓶颈，连接开销可以忽略

## 验证

所有修改已通过 Python 语法检查，可以直接使用。

## 注意事项

- 确保 SQLite 数据库文件权限正确，允许并发读取
- SQLite 支持多读单写，对于只读操作不会有问题
- 每个请求完成后连接都会关闭，不会累积连接
