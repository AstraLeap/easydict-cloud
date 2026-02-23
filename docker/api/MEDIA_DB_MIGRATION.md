# 媒体文件存储迁移说明

## 概述

本次修改将音频和图片文件的存储方式从 ZIP 压缩包改为 SQLite3 数据库。

## 主要变化

### 1. 文件存储方式

**之前：**
- `audios.zip` - 音频文件压缩包
- `images.zip` - 图片文件压缩包

**现在：**
- `media.db` - SQLite3 数据库，包含两个表：
  - `audios` 表：存储音频文件（name, blob）
  - `images` 表：存储图片文件（name, blob）

### 2. API 接口变化

#### 下载接口

**之前：**
- `GET /download/{dict_id}/audios` - 下载音频压缩包
- `GET /download/{dict_id}/images` - 下载图片压缩包

**现在：**
- `GET /download/{dict_id}/media` - 下载媒体数据库文件

#### 单个文件获取接口

接口路径保持不变，但内部实现从 ZIP 读取改为从数据库读取：

- `GET /audio/{dict_id}/{file_path}` - 获取单个音频文件
- `GET /image/{dict_id}/{file_path}` - 获取单个图片文件

### 3. 数据结构

#### media.db 数据库结构

```sql
-- 音频表
CREATE TABLE audios (
    name TEXT PRIMARY KEY,
    blob BLOB NOT NULL
);

-- 图片表
CREATE TABLE images (
    name TEXT PRIMARY KEY,
    blob BLOB NOT NULL
);

-- 索引
CREATE INDEX idx_audios_name ON audios(name);
CREATE INDEX idx_images_name ON images(name);
```

## 数据迁移

### 自动迁移

API 代码中包含 `migrate_zip_to_media_db()` 函数，可以自动将 ZIP 文件迁移到数据库。

### 手动迁移

使用提供的迁移脚本：

```bash
# 迁移所有词典
cd /home/karx/easydict/docker/api
python migrate_to_media_db.py

# 迁移指定词典
python migrate_to_media_db.py <dict_id>
```

### 迁移步骤

1. **停止 API 服务**
   ```bash
   docker-compose down
   ```

2. **运行迁移脚本**
   ```bash
   cd docker/api
   python migrate_to_media_db.py
   ```

3. **验证迁移结果**
   - 检查词典目录下是否生成了 `media.db` 文件
   - 验证音频和图片数量是否正确

4. **备份旧文件（可选）**
   ```bash
   # 重命名旧的 zip 文件作为备份
   mv audios.zip audios.zip.bak
   mv images.zip images.zip.bak
   ```

5. **启动 API 服务**
   ```bash
   docker-compose up -d
   ```

## 向后兼容

代码保持向后兼容性：
- 如果 `media.db` 存在，优先从数据库读取
- 如果 `media.db` 不存在，会尝试从旧的目录结构读取
- 旧的 ZIP 文件可以保留作为备份

## 性能优势

使用数据库存储相比 ZIP 文件的优势：

1. **查询速度更快**：数据库索引支持 O(log n) 查询
2. **并发访问更好**：SQLite 支持多读单写
3. **内存占用更小**：不需要将整个 ZIP 文件加载到内存
4. **维护更方便**：可以使用 SQL 工具直接查询和管理
5. **扩展性更好**：方便添加更多元数据字段

## 文件清单

修改的文件：
- `docker/api/main.py` - 主要 API 代码

新增的文件：
- `docker/api/migrate_to_media_db.py` - 数据迁移脚本
- `docker/api/MEDIA_DB_MIGRATION.md` - 本说明文档

## 测试验证

迁移后可以进行以下测试：

1. **获取词典列表**
   ```bash
   curl http://localhost:8080/dictionaries
   ```
   检查词典信息中的 `has_audios`、`has_images`、`audio_count`、`image_count` 是否正确

2. **下载媒体数据库**
   ```bash
   curl http://localhost:8080/download/{dict_id}/media -o media.db
   ```

3. **获取单个音频文件**
   ```bash
   curl http://localhost:8080/audio/{dict_id}/word.mp3 -o test.mp3
   ```

4. **获取单个图片文件**
   ```bash
   curl http://localhost:8080/image/{dict_id}/word.jpg -o test.jpg
   ```

## 故障排除

### 问题：迁移后文件无法访问

**解决方案：**
1. 检查 `media.db` 文件是否存在
2. 验证数据库文件是否损坏：
   ```bash
   sqlite3 media.db "SELECT COUNT(*) FROM audios;"
   sqlite3 media.db "SELECT COUNT(*) FROM images;"
   ```
3. 检查 API 日志中的错误信息

### 问题：迁移脚本执行失败

**解决方案：**
1. 检查是否有足够的磁盘空间
2. 确保 audios.zip 和 images.zip 文件完整且未损坏
3. 检查文件权限

### 问题：性能下降

**解决方案：**
1. 检查数据库索引是否正确创建
2. 考虑增加数据库缓存大小
3. 检查磁盘 I/O 性能

## 回滚方案

如果需要回滚到旧的 ZIP 方式：

1. 恢复备份的 ZIP 文件：
   ```bash
   mv audios.zip.bak audios.zip
   mv images.zip.bak images.zip
   ```

2. 删除 media.db 文件：
   ```bash
   rm media.db
   ```

3. 重启 API 服务

API 会自动检测并使用 ZIP 文件。
