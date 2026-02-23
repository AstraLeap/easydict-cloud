# EasyDict API 完整接口文档

## 基础信息

- **服务名称**: EasyDict API
- **版本**: v2.0.0
- **基础URL**: `http://localhost:3070`
- **协议**: HTTP/HTTPS
- **格式**: JSON
- **编码**: UTF-8

---

## 接口列表（共 10 个）

### 1. 健康检查
### 2. 词典管理（1个）
### 3. 词典查询（1个）
### 4. 文件下载（4个）
### 5. 媒体文件（2个）
### 6. 辅助文件（1个）

---

## 详细接口说明

## 1. 健康检查

### 1.1 健康检查

**接口**: `GET /health`

**功能**: 检查 API 服务健康状态

**请求示例**:
```bash
curl http://localhost:3070/health
```

**响应示例**:
```json
{
  "status": "healthy",
  "service": "easydict-api"
}
```

**HTTP 状态码**: 200

**缓存**: 无

---

## 2. 词典管理

### 2.1 获取词典列表

**接口**: `GET /dictionaries`

**功能**: 获取所有可用词典的详细信息

**请求示例**:
```bash
curl http://localhost:3070/dictionaries
```

**响应示例**:
```json
{
  "dictionaries": [
    {
      "id": "ode_now",
      "name": "Oxford Dictionary of English",
      "description": "Oxford Dictionary of English - The foremost single-volume dictionary of current English",
      "version": "1.0.0",
      "author": "",
      "language": "",
      "entry_count": 2,
      "has_database": true,
      "has_audios": true,
      "has_images": true,
      "has_logo": true,
      "has_metadata": true,
      "audio_count": 226045,
      "image_count": 892,
      "dict_size": 90112,
      "media_size": 549814272,
      "created_at": "2026-02-04T12:52:36.784312",
      "updated_at": "2026-02-04T12:52:36.784312"
    }
  ]
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 词典唯一标识符 |
| `name` | string | 词典名称 |
| `description` | string | 词典描述 |
| `version` | string | 版本号 |
| `author` | string | 作者 |
| `language` | string | 语言 |
| `entry_count` | int | 词条数量 |
| `has_database` | bool | 是否有词典数据库 |
| `has_audios` | bool | 是否有音频文件 |
| `has_images` | bool | 是否有图片文件 |
| `has_logo` | bool | 是否有 Logo |
| `has_metadata` | bool | 是否有元数据 |
| `audio_count` | int | 音频文件数量 |
| `image_count` | int | 图片文件数量 |
| `dict_size` | int | dictionary.db 文件大小（字节） |
| `media_size` | int | media.db 文件大小（字节） |
| `created_at` | string | 创建时间（ISO 8601） |
| `updated_at` | string | 更新时间（ISO 8601） |

**HTTP 状态码**: 200

**缓存**: 5分钟

---

## 3. 词典查询

### 3.1 查询单词

**接口**: `GET /word/{dict_id}/{word}`

**功能**: 查询单词的释义、例句、发音等信息

**路径参数**:
- `dict_id` (string): 词典ID
- `word` (string): 要查询的单词

**请求示例**:
```bash
# 查询单词
curl http://localhost:3070/word/ode_now/apple

# 查询短语
curl http://localhost:3070/word/ode_now/apple%20pie
```

**响应示例**:
```json
{
  "dict_id": "ode_now",
  "word": "apple",
  "entries": [
    {
      "id": "1",
      "headword": "apple",
      "entry_type": "word",
      "page": null,
      "section": null,
      "tags": [],
      "certifications": [],
      "frequency": {},
      "etymology": null,
      "inflections": [],
      "pronunciations": [
        {
          "ipa": "/ˈapl/",
          "audio": "apple_gb_1.opus",
          "region": "GB"
        },
        {
          "ipa": "/ˈæpl/",
          "audio": "apple_us_1.opus",
          "region": "US"
        }
      ],
      "senses": [
        {
          "id": "1",
          "definition": "A round fruit with red or green skin and crisp flesh.",
          "examples": ["I ate an apple for lunch."],
          "labels": []
        }
      ],
      "boards": [],
      "collocations": null,
      "phrases": null,
      "theasaruses": null,
      "senseGroups": []
    }
  ],
  "total": 1
}
```

**查询特性**:
- ✅ 精确匹配优先
- ✅ 前缀匹配
- ✅ 模糊匹配（JSON内容搜索）
- ✅ 最多返回 50 条结果
- ✅ 按相关度排序

**HTTP 状态码**:
- 200: 成功
- 404: 词典或单词未找到
- 500: 服务器错误

**缓存**: 5分钟

---

## 4. 文件下载

### 4.1 下载词典 Logo

**接口**: `GET /download/{dict_id}/logo`

**功能**: 下载词典的 Logo 图片

**路径参数**:
- `dict_id` (string): 词典ID

**响应类型**: `image/png`

**请求示例**:
```bash
curl http://localhost:3070/download/ode_now/logo -o logo.png
```

**响应头**:
```
Content-Type: image/png
Content-Disposition: inline; filename="logo.png"
Cache-Control: public, max-age=2592000
```

**缓存**: 30天

---

### 4.2 下载词典元数据

**接口**: `GET /download/{dict_id}/metadata`

**功能**: 下载词典的元数据 JSON 文件

**路径参数**:
- `dict_id` (string): 词典ID

**响应类型**: `application/json`

**请求示例**:
```bash
curl http://localhost:3070/download/ode_now/metadata -o metadata.json
```

**响应内容示例**:
```json
{
  "name": "Oxford Dictionary of English",
  "description": "Oxford Dictionary of English",
  "version": "1.0.0",
  "author": "",
  "language": "en"
}
```

**缓存**: 1天

---

### 4.3 下载词典数据库

**接口**: `GET /download/{dict_id}/database`

**功能**: 下载词典的 SQLite3 数据库文件

**路径参数**:
- `dict_id` (string): 词典ID

**响应类型**: `application/vnd.sqlite3`

**请求示例**:
```bash
curl http://localhost:3070/download/ode_now/database -o dictionary.db
```

**响应头**:
```
Content-Type: application/vnd.sqlite3
Content-Disposition: inline; filename="ode_now.db"
Cache-Control: public, max-age=86400
```

**数据库结构**:
```sql
CREATE TABLE entries (
    entry_id INTEGER PRIMARY KEY,
    headword TEXT NOT NULL,
    entry_type TEXT,
    page TEXT,
    section TEXT,
    json_data TEXT
);

CREATE INDEX idx_headword ON entries(headword);
```

**缓存**: 1天

---

### 4.4 下载媒体数据库

**接口**: `GET /download/{dict_id}/media`

**功能**: 下载词典的媒体文件数据库（包含音频和图片）

**路径参数**:
- `dict_id` (string): 词典ID

**响应类型**: `application/vnd.sqlite3`

**请求示例**:
```bash
curl http://localhost:3070/download/ode_now/media -o media.db
```

**数据库结构**:
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

**查询示例**:
```sql
-- 查看音频数量
SELECT COUNT(*) FROM audios;

-- 查看图片数量
SELECT COUNT(*) FROM images;

-- 获取音频文件列表
SELECT name FROM audios LIMIT 10;

-- 获取图片文件列表
SELECT name FROM images LIMIT 10;
```

**缓存**: 30天

---

## 5. 媒体文件

### 5.1 获取音频文件

**接口**: `GET /audio/{dict_id}/{file_path:path}`

**功能**: 获取单个音频文件

**路径参数**:
- `dict_id` (string): 词典ID
- `file_path` (string): 音频文件路径（支持多级路径）

**查询优先级**:
1. 从 `media.db` 数据库读取（新方式）
2. 从 `audios/` 目录读取（向后兼容）

**支持的格式**:
- MP3 (`audio/mpeg`)
- WAV (`audio/wav`)
- OGG (`audio/ogg`)
- Opus (`audio/opus`)

**请求示例**:
```bash
# 获取音频文件
curl http://localhost:3070/audio/ode_now/apple_gb_1.opus -o apple.opus

# 支持多级路径
curl http://localhost:3070/audio/ode_now/subdir/file.mp3 -o file.mp3
```

**响应头**:
```
Content-Type: audio/opus
Content-Disposition: inline; filename="apple_gb_1.opus"
Cache-Control: public, max-age=2592000
```

**错误处理**:
```json
{
  "detail": "Audio file 'word.mp3' not found"
}
```

**缓存**: 30天

---

### 5.2 获取图片文件

**接口**: `GET /image/{dict_id}/{file_path:path}`

**功能**: 获取单个图片文件

**路径参数**:
- `dict_id` (string): 词典ID
- `file_path` (string): 图片文件路径（支持多级路径）

**查询优先级**:
1. 从 `media.db` 数据库读取（新方式）
2. 从 `images/` 目录读取（向后兼容）

**支持的格式**:
- PNG (`image/png`)
- JPEG (`image/jpeg`)
- GIF (`image/gif`)
- WebP (`image/webp`)
- SVG (`image/svg+xml`)

**请求示例**:
```bash
# 获取图片文件
curl http://localhost:3070/image/ode_now/A-frame.svg -o aframe.svg

# 支持多级路径
curl http://localhost:3070/image/ode_now/subdir/image.png -o image.png
```

**响应头**:
```
Content-Type: image/svg+xml
Content-Disposition: inline; filename="A-frame.svg"
Cache-Control: public, max-age=2592000
```

**错误处理**:
```json
{
  "detail": "Image file 'word.png' not found"
}
```

**缓存**: 30天

---

## 6. 辅助文件

### 6.1 获取辅助文件

**接口**: `GET /auxi/{filename:path}`

**功能**: 获取辅助数据目录中的任意文件

**路径参数**:
- `filename` (string): 文件名（支持路径）

**安全限制**:
- ❌ 不允许路径遍历（`..`）
- ❌ 不允许绝对路径（`/`）
- ✅ 只能访问辅助目录下的文件

**请求示例**:
```bash
# 下载辅助数据库
curl http://localhost:3070/auxi/en.db -o en.db

# 下载配置文件
curl http://localhost:3070/auxi/data/config.json -o config.json

# 下载任意辅助文件
curl http://localhost:3070/auxi/dictionary.index -o index
```

**响应头**:
```
Content-Type: <根据文件扩展名自动识别>
Content-Disposition: inline; filename="<原文件名>"
Cache-Control: public, max-age=86400
```

**缓存**: 1天

---

## 性能优化

### 数据库连接缓存

| 连接类型 | 首次查询 | 后续查询 | 说明 |
|---------|---------|---------|------|
| dictionary.db | 20-50ms | 1-5ms | 词条查询 |
| media.db | 20-50ms | 1-5ms | 媒体文件 |

### HTTP 缓存策略

| 资源类型 | 缓存时间 | 说明 |
|---------|---------|------|
| Logo | 30天 | 静态资源 |
| 元数据 | 1天 | 可能更新 |
| 词典数据库 | 1天 | 可能更新 |
| 媒体数据库 | 30天 | 静态资源 |
| 音频/图片 | 30天 | 静态资源 |
| 辅助文件 | 1天 | 可能更新 |
| 词典列表 | 5分钟 | 可能变化 |
| 单词查询 | 5分钟 | 查询结果 |

### CORS 支持

所有接口均支持跨域访问：

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

---

## 错误处理

### HTTP 状态码

| 状态码 | 说明 |
|-------|------|
| 200 | 成功 |
| 404 | 资源未找到 |
| 405 | 方法不允许 |
| 500 | 服务器内部错误 |

### 错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

### 常见错误场景

**词典不存在**:
```json
{
  "detail": "Dictionary 'unknown_dict' not found"
}
```

**文件未找到**:
```json
{
  "detail": "Audio file 'word.mp3' not found"
}
```

**路径遍历攻击**:
```json
{
  "detail": "Invalid filename. Path traversal is not allowed."
}
```

---

## 使用示例

### 完整查词流程

```bash
# 1. 获取所有可用词典
curl http://localhost:3070/dictionaries

# 2. 查询单词
curl http://localhost:3070/word/ode_now/apple

# 3. 获取单词的发音音频
curl http://localhost:3070/audio/ode_now/apple_gb_1.opus -o apple.opus

# 4. 播放音频（使用你的播放器）
# play apple.opus
```

### 下载完整词典数据包

```bash
# 创建输出目录
mkdir -p ode_now
cd ode_now

# 1. 下载词典数据库
curl http://localhost:3070/download/ode_now/database -o dictionary.db

# 2. 下载媒体数据库
curl http://localhost:3070/download/ode_now/media -o media.db

# 3. 下载 Logo
curl http://localhost:3070/download/ode_now/logo -o logo.png

# 4. 下载元数据
curl http://localhost:3070/download/ode_now/metadata -o metadata.json
```

### 批量查询单词

```bash
# 从文件读取单词列表并批量查询
cat words.txt | while read word; do
  echo "Querying: $word"
  curl "http://localhost:3070/word/ode_now/$word"
  echo ""
done
```

---

## 数据存储架构

### 词典目录结构

```
/data/dictionaries/
├── ode_now/
│   ├── dictionary.db      # 词典数据库
│   ├── media.db           # 媒体数据库
│   ├── logo.png           # Logo图片
│   └── metadata.json      # 元数据
└── another_dict/
    ├── dictionary.db
    ├── media.db
    ├── logo.png
    └── metadata.json
```

### media.db 结构

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

### 向后兼容

旧的数据存储方式仍然支持：

```
/data/dictionaries/
├── old_dict/
│   ├── dictionary.db
│   ├── audios/            # 旧方式：音频目录
│   │   ├── word1.mp3
│   │   └── word2.mp3
│   ├── images/            # 旧方式：图片目录
│   │   ├── image1.png
│   │   └── image2.png
│   └── metadata.json
```

**优先级**:
1. ✅ media.db（优先）
2. ✅ audios/ 和 images/ 目录（向后兼容）

---

## 环境变量

| 变量名 | 默认值 | 说明 |
|-------|-------|------|
| `DICTIONARIES_PATH` | `/data/dictionaries` | 词典数据根目录 |
| `AUXILIARY_PATH` | `/data/auxiliary` | 辅助文件目录 |
| `CACHE_PATH` | `/tmp/easydict-cache` | 缓存目录 |
| `PORT` | `8080` | API 服务端口 |
| `LOG_LEVEL` | `info` | 日志级别 |

---

## MIME 类型映射

### 音频文件

| 扩展名 | MIME 类型 |
|-------|----------|
| .mp3 | audio/mpeg |
| .wav | audio/wav |
| .ogg | audio/ogg |
| .opus | audio/opus |

### 图片文件

| 扩展名 | MIME 类型 |
|-------|----------|
| .png | image/png |
| .jpg/.jpeg | image/jpeg |
| .gif | image/gif |
| .webp | image/webp |
| .svg | image/svg+xml |

### 数据文件

| 扩展名 | MIME 类型 |
|-------|----------|
| .db | application/vnd.sqlite3 |
| .json | application/json |

---

## 性能指标

### 响应时间

| 操作 | 平均响应时间 |
|------|------------|
| 健康检查 | < 5ms |
| 词典列表 | 50-200ms |
| 单词查询 | 10-50ms |
| 音频文件获取 | 5-20ms |
| 图片文件获取 | 5-20ms |
| 数据库下载 | 取决于文件大小 |

### 并发支持

- ✅ 支持高并发读取
- ✅ SQLite 多读单写
- ✅ 数据库连接池
- ✅ 异步 I/O

---

## 更新日志

### v2.0.0 (2026-02-04)

**重大变更**:
- ✨ 新增媒体数据库（media.db）支持
- 🔧 存储方式从 ZIP 改为 SQLite3
- ⚡ 性能优化：数据库连接缓存
- 📝 字段重命名：`database_size` → `dict_size`，`media_db_size` → `media_size`
- 🐛 改进错误处理

**新增接口**:
- `GET /download/{dict_id}/media` - 下载媒体数据库

**删除接口**:
- ❌ `GET /download/{dict_id}/audios` - 不再支持
- ❌ `GET /download/{dict_id}/images` - 不再支持

**向后兼容**:
- ✅ 支持旧的目录结构（audios/, images/）
- ✅ 所有原有接口保持可用

---

## 技术栈

### 后端
- **框架**: FastAPI 0.100+
- **异步**: asyncio
- **数据库**: SQLite3 + aiosqlite
- **服务器**: Uvicorn

### 前端代理
- **反向代理**: Nginx
- **负载均衡**: 支持
- **静态文件**: 支持
- **Gzip 压缩**: 启用

---

## 附录

### 字段变更历史

| 版本 | 字段 | 变更 |
|------|------|------|
| v2.0.0 | `database_size` | → `dict_size` |
| v2.0.0 | `media_db_size` | → `media_size` |
| v2.0.0 | `media_size` | ✨ 新增 |

### 相关文档

- `API_REFERENCE.md` - API 接口详细文档
- `MEDIA_DB_MIGRATION.md` - 数据迁移指南
- `CONNECTION_CACHING.md` - 连接缓存说明
- `DCTIONARIES_API_UPDATE.md` - 词典列表接口更新
- `CHANGES_SUMMARY.md` - 修改总结

---

## 联系方式

如有问题或建议，请提交 Issue 或 Pull Request。
