# 修改总结

## 修改概述

本次修改将音频和图片文件的存储方式从 ZIP 压缩包改为 SQLite3 数据库（media.db），并相应修改了 API 接口。

## 修改的文件

### 1. docker/api/main.py

**新增功能：**
- 添加了 `_media_db_connections` 缓存字典
- 新增 `get_media_db_connection()` - 获取媒体数据库连接
- 新增 `create_media_db()` - 创建 media.db 数据库和表结构
- 新增 `migrate_zip_to_media_db()` - 将 ZIP 文件迁移到数据库
- 新增 `count_files_in_media_db()` - 统计数据库中的文件数量

**修改功能：**
- `lifespan()` - 添加 media 数据库连接的清理
- `get_dictionary_info()` - 修改检查逻辑，优先检查 media.db
- 删除了 `get_dictionary_audios()` 和 `get_dictionary_images()` 接口
- 新增 `get_dictionary_media()` - 统一的媒体数据库下载接口
- `get_audio_file()` - 修改为从数据库读取音频文件
- `get_image_file()` - 修改为从数据库读取图片文件

### 2. docker/nginx.conf

**修改：**
- 删除了旧的 `/download/{dict_id}/audios` 配置
- 删除了旧的 `/download/{dict_id}/images` 配置
- 新增 `/download/{dict_id}/media` 配置

### 3. 新增文件

#### docker/api/migrate_to_media_db.py
独立的数据迁移脚本，用于将现有的 ZIP 文件迁移到 media.db 数据库。

**使用方法：**
```bash
# 迁移所有词典
python migrate_to_media_db.py

# 迁移指定词典
python migrate_to_media_db.py <dict_id>
```

#### docker/api/MEDIA_DB_MIGRATION.md
完整的迁移说明文档，包含：
- 修改概述
- API 变化
- 数据结构
- 迁移步骤
- 性能优势
- 测试验证
- 故障排除
- 回滚方案

## 数据库结构

### media.db

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

## API 变化

### 下载接口

**删除：**
- ❌ `GET /download/{dict_id}/audios`
- ❌ `GET /download/{dict_id}/images`

**新增：**
- ✅ `GET /download/{dict_id}/media` - 下载媒体数据库文件

### 单文件获取接口

接口路径保持不变，但内部实现改变：
- ✅ `GET /audio/{dict_id}/{file_path}` - 从数据库读取音频
- ✅ `GET /image/{dict_id}/{file_path}` - 从数据库读取图片

## 向后兼容性

代码保持向后兼容：
- 如果 `media.db` 存在，优先从数据库读取
- 如果 `media.db` 不存在，尝试从旧的目录结构读取
- 旧的 ZIP 文件可以保留作为备份

## 测试清单

在使用前请进行以下测试：

### 1. 服务启动测试
```bash
docker-compose up -d
docker-compose logs -f api
```

### 2. API 测试

#### 获取词典列表
```bash
curl http://localhost:3070/dictionaries
```
检查 `has_audios`、`has_images`、`audio_count`、`image_count` 字段

#### 下载媒体数据库
```bash
curl http://localhost:3070/download/{dict_id}/media -o media.db
```

#### 获取单个音频文件
```bash
curl http://localhost:3070/audio/{dict_id}/word.mp3 -o test.mp3
```

#### 获取单个图片文件
```bash
curl http://localhost:3070/image/{dict_id}/word.jpg -o test.jpg
```

### 3. 数据库验证

```bash
# 打开数据库
sqlite3 media.db

# 查看表
.tables

# 统计音频数量
SELECT COUNT(*) FROM audios;

# 统计图片数量
SELECT COUNT(*) FROM images;

# 查看音频文件列表
SELECT name FROM audios LIMIT 10;

# 退出
.quit
```

## 迁移步骤（如有旧数据）

### 自动迁移（推荐）
在 API 代码中调用 `migrate_zip_to_media_db()` 函数

### 手动迁移
```bash
# 1. 停止服务
docker-compose down

# 2. 运行迁移脚本
cd docker/api
python migrate_to_media_db.py

# 3. 验证迁移结果
ls -lh /data/dictionaries/*/media.db

# 4. 备份旧文件（可选）
mv /data/dictionaries/{dict_id}/audios.zip /data/dictionaries/{dict_id}/audios.zip.bak
mv /data/dictionaries/{dict_id}/images.zip /data/dictionaries/{dict_id}/images.zip.bak

# 5. 启动服务
docker-compose up -d
```

## 性能优势

使用数据库存储相比 ZIP 文件的优势：

1. **查询速度**：数据库索引支持 O(log n) 查询
2. **并发访问**：SQLite 支持多读单写
3. **内存占用**：不需要加载整个 ZIP 文件
4. **维护方便**：可以使用 SQL 工具直接管理
5. **扩展性**：方便添加更多元数据字段

## 注意事项

1. **磁盘空间**：迁移后需要额外的磁盘空间存储数据库
2. **迁移时间**：大型词典可能需要较长时间迁移
3. **备份**：迁移前建议备份原始 ZIP 文件
4. **测试**：建议在测试环境中先验证迁移效果

## 回滚方案

如需回滚到旧的 ZIP 方式：

1. 恢复备份的 ZIP 文件
2. 删除 media.db 文件
3. 重启服务

API 会自动检测并使用 ZIP 文件。

## 代码质量

- ✅ 所有文件通过 Python 语法检查
- ✅ nginx 配置语法正确
- ✅ 保持了原有的错误处理机制
- ✅ 添加了详细的日志记录
- ✅ 保持了向后兼容性

## 文件清单

| 文件 | 状态 | 说明 |
|------|------|------|
| docker/api/main.py | 修改 | 主要 API 代码 |
| docker/nginx.conf | 修改 | Nginx 配置 |
| docker/api/migrate_to_media_db.py | 新增 | 迁移脚本 |
| docker/api/MEDIA_DB_MIGRATION.md | 新增 | 迁移说明文档 |
| docker/api/CHANGES_SUMMARY.md | 新增 | 本文档 |

## 下一步建议

1. 在测试环境中验证所有功能
2. 运行迁移脚本转换现有数据
3. 验证迁移后的数据完整性
4. 测试 API 性能
5. 部署到生产环境
6. 监控服务运行状态

## 技术支持

如有问题，请查看：
- `docker/api/MEDIA_DB_MIGRATION.md` - 详细迁移文档
- Docker 日志：`docker-compose logs -f api`
- Nginx 日志：`docker/logs/nginx/`
