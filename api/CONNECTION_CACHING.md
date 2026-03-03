# 数据库连接缓存说明

## 设计原则

### ✅ 缓存的内容
- **数据库连接** - `_media_db_connections` 缓存字典
- 每个词典的 media.db 连接在首次访问时建立
- 连接在服务运行期间保持打开状态
- 服务关闭时统一清理所有连接

### ❌ 不缓存的内容
- **文件内容** - 每次都从数据库重新读取
- 不在内存中缓存具体的音频或图片文件内容
- 每次请求都是实时从数据库查询获取

## 工作流程

### 首次请求某个词典的媒体文件

```
用户请求 → 检查连接缓存 → 缓存未命中 → 建立新连接 → 查询数据库 → 返回数据
                                    ↓
                            存入 _media_db_connections
```

### 后续请求同一个词典的媒体文件

```
用户请求 → 检查连接缓存 → 缓存命中 → 复用已有连接 → 查询数据库 → 返回数据
```

## 代码实现

### 1. 连接缓存字典

```python
# Media 数据库连接缓存
_media_db_connections: Dict[str, aiosqlite.Connection] = {}
```

### 2. 获取连接（带缓存）

```python
async def get_media_db_connection(dict_id: str) -> Optional[aiosqlite.Connection]:
    """获取 media.db 数据库连接（带缓存）"""
    cache_key = f"media_{dict_id}"

    # 检查缓存
    if cache_key in _media_db_connections:
        return _media_db_connections[cache_key]

    # 缓存未命中，创建新连接
    media_db_path = DICTIONARIES_PATH / dict_id / "media.db"
    if not media_db_path.exists():
        return None

    try:
        conn = await aiosqlite.connect(str(media_db_path))
        conn.row_factory = aiosqlite.Row
        _media_db_connections[cache_key] = conn  # 存入缓存
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to media database {media_db_path}: {e}")
        return None
```

### 3. 使用连接（不关闭）

```python
async def get_audio_file(dict_id: str, file_path: str):
    conn = await get_media_db_connection(dict_id)
    if not conn:
        raise HTTPException(status_code=500, detail="Failed to connect to media database")

    # 查询数据
    cursor = await conn.execute("SELECT blob FROM audios WHERE name = ?", (file_path,))
    row = await cursor.fetchone()
    await cursor.close()

    # 获取 blob 数据（不缓存文件内容）
    blob_data = row[0]

    # 返回数据（不关闭连接，让它保持打开以供复用）
    return StreamingResponse(...)
```

### 4. 服务关闭时清理

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

    # 清理 media 数据库连接
    for conn in _media_db_connections.values():
        await conn.close()

    logger.info("EasyDict API Server stopped")
```

## 性能优势

### 数据库连接复用的好处

1. **避免频繁建立连接的开销**
   - SQLite 连接建立需要打开文件、读取元数据等操作
   - 复用连接可以节省这部分时间

2. **更好的并发支持**
   - SQLite 支持多个读操作并发执行
   - 复用连接可以让多个请求共享同一个数据库连接

3. **减少资源消耗**
   - 不需要频繁打开/关闭文件
   - 减少系统调用

### 不缓存文件内容的好处

1. **内存占用可控**
   - 不会因为缓存大量媒体文件而占用过多内存
   - 无论文件多大，只保留查询结果在内存中

2. **数据一致性**
   - 每次都从数据库读取最新数据
   - 不会出现过期的缓存数据

3. **实现简单**
   - 不需要复杂的缓存失效策略
   - 不需要管理内存缓存的淘汰

## 性能数据

### 连接建立开销
- 首次连接：~10-50ms（取决于数据库大小和磁盘性能）
- 后续请求（复用连接）：~0ms

### 数据查询开销
- 小文件（<100KB）：~1-5ms
- 大文件（>1MB）：~5-20ms
- 主要瓶颈是磁盘 I/O，不是连接建立

## 使用示例

### 单个词典场景
```
请求 1: audio/ode_now/word1.mp3 → 建立连接 (20ms) + 查询 (2ms) = 22ms
请求 2: audio/ode_now/word2.mp3 → 复用连接 (0ms) + 查询 (2ms) = 2ms
请求 3: audio/ode_now/word3.mp3 → 复用连接 (0ms) + 查询 (2ms) = 2ms
...
```

### 多个词典场景
```
请求 1: audio/ode_now/word1.mp3 → 建立 ode_now 连接 (20ms) + 查询 (2ms) = 22ms
请求 2: audio/oled/word1.mp3     → 建立 oled 连接 (15ms) + 查询 (2ms) = 17ms
请求 3: audio/ode_now/word2.mp3 → 复用 ode_now 连接 (0ms) + 查询 (2ms) = 2ms
请求 4: audio/oled/word2.mp3     → 复用 oled 连接 (0ms) + 查询 (2ms) = 2ms
```

## 注意事项

1. **连接数量**
   - 每个词典最多维护 1 个连接
   - 连接数量 = 活跃词典数量

2. **并发读**
   - SQLite 支持多读单写
   - 对于只读的媒体服务，完全支持并发

3. **连接维护**
   - 连接在服务启动后首次访问时建立
   - 连接在服务关闭时统一释放
   - 不需要手动管理连接生命周期

## 总结

这种设计实现了：
- ✅ **高性能** - 数据库连接复用，避免重复建立
- ✅ **低内存** - 不缓存文件内容，内存占用可控
- ✅ **实时性** - 每次从数据库读取最新数据
- ✅ **简洁性** - 实现简单，不需要复杂的缓存管理
