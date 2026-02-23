# EasyDict API 接口文档

## 基础信息

- **基础URL**: `http://localhost:3070` (或通过 nginx 代理)
- **API 版本**: 2.0.0
- **响应格式**: JSON
- **字符编码**: UTF-8

---

## 目录

1. [健康检查](#1-健康检查)
2. [词典管理](#2-词典管理)
3. [词典查询](#3-词典查询)
4. [文件下载](#4-文件下载)
5. [媒体文件](#5-媒体文件)
6. [辅助文件](#6-辅助文件)

---

## 1. 健康检查

### 1.1 健康检查

**接口**: `GET /health`

**描述**: 检查 API 服务是否正常运行

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

---

## 2. 词典管理

### 2.1 获取词典列表

**接口**: `GET /dictionaries`

**描述**: 获取所有可用词典的详细信息

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
      "database_size": 90112,
      "created_at": "2026-02-04T12:52:36.784312",
      "updated_at": "2026-02-04T12:52:36.784312"
    }
  ]
}
```

**字段说明**:
- `id`: 词典唯一标识符
- `name`: 词典名称
- `description`: 词典描述
- `version`: 版本号
- `author`: 作者
- `language`: 语言
- `entry_count`: 词条数量
- `has_database`: 是否有词典数据库
- `has_audios`: 是否有音频文件
- `has_images`: 是否有图片文件
- `has_logo`: 是否有 Logo
- `has_metadata`: 是否有元数据
- `audio_count`: 音频文件数量
- `image_count`: 图片文件数量
- `database_size`: 数据库文件大小（字节）
- `created_at`: 创建时间（ISO 8601）
- `updated_at`: 更新时间（ISO 8601）

---

## 3. 词典查询

### 3.1 查询单词

**接口**: `GET /word/{dict_id}/{word}`

**描述**: 查询单词的释义、例句、发音等信息

**路径参数**:
- `dict_id`: 词典ID
- `word`: 要查询的单词

**请求示例**:
```bash
curl http://localhost:3070/word/ode_now/apple
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

**查询说明**:
- 支持精确匹配：查询 `apple` 只返回 `apple`
- 支持前缀匹配：查询 `app` 返回 `app`, `apple`, `application` 等
- 返回结果按相关度排序
- 最多返回 50 条结果

---

## 4. 文件下载

### 4.1 下载词典 Logo

**接口**: `GET /download/{dict_id}/logo`

**描述**: 下载词典的 Logo 图片

**路径参数**:
- `dict_id`: 词典ID

**响应类型**: `image/png`

**缓存**: 30天

**请求示例**:
```bash
curl http://localhost:3070/download/ode_now/logo -o logo.png
```

---

### 4.2 下载词典元数据

**接口**: `GET /download/{dict_id}/metadata`

**描述**: 下载词典的元数据 JSON 文件

**路径参数**:
- `dict_id`: 词典ID

**响应类型**: `application/json`

**缓存**: 1天

**请求示例**:
```bash
curl http://localhost:3070/download/ode_now/metadata -o metadata.json
```

---

### 4.3 下载词典数据库

**接口**: `GET /download/{dict_id}/database`

**描述**: 下载词典的 SQLite3 数据库文件

**路径参数**:
- `dict_id`: 词典ID

**响应类型**: `application/vnd.sqlite3`

**缓存**: 1天

**请求示例**:
```bash
curl http://localhost:3070/download/ode_now/database -o dictionary.db
```

---

### 4.4 下载词典媒体数据库

**接口**: `GET /download/{dict_id}/media`

**描述**: 下载词典的媒体文件数据库（包含音频和图片的 SQLite3 数据库）

**路径参数**:
- `dict_id`: 词典ID

**响应类型**: `application/vnd.sqlite3`

**缓存**: 30天

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
```

**请求示例**:
```bash
curl http://localhost:3070/download/ode_now/media -o media.db
```

---

## 5. 媒体文件

### 5.1 获取音频文件

**接口**: `GET /audio/{dict_id}/{file_path}`

**描述**: 获取单个音频文件

**路径参数**:
- `dict_id`: 词典ID
- `file_path`: 音频文件路径（支持多级路径）

**查询优先级**:
1. 从 `media.db` 数据库读取
2. 从 `audios/` 目录读取（向后兼容）

**支持的音频格式**:
- MP3 (`audio/mpeg`)
- WAV (`audio/wav`)
- OGG (`audio/ogg`)
- Opus (`audio/opus`)

**缓存**: 30天

**请求示例**:
```bash
# 获取音频文件
curl http://localhost:3070/audio/ode_now/apple_gb_1.opus -o apple.opus

# 支持多级路径
curl http://localhost:3070/audio/ode_now/path/to/file.mp3 -o file.mp3
```

**响应头**:
```
Content-Type: audio/opus
Content-Disposition: inline; filename="apple_gb_1.opus"
Cache-Control: public, max-age=2592000
```

---

### 5.2 获取图片文件

**接口**: `GET /image/{dict_id}/{file_path}`

**描述**: 获取单个图片文件

**路径参数**:
- `dict_id`: 词典ID
- `file_path`: 图片文件路径（支持多级路径）

**查询优先级**:
1. 从 `media.db` 数据库读取
2. 从 `images/` 目录读取（向后兼容）

**支持的图片格式**:
- PNG (`image/png`)
- JPEG (`image/jpeg`)
- GIF (`image/gif`)
- WebP (`image/webp`)
- SVG (`image/svg+xml`)

**缓存**: 30天

**请求示例**:
```bash
# 获取图片文件
curl http://localhost:3070/image/ode_now/A-frame.svg -o aframe.svg

# 支持多级路径
curl http://localhost:3070/image/ode_now/path/to/image.png -o image.png
```

**响应头**:
```
Content-Type: image/svg+xml
Content-Disposition: inline; filename="A-frame.svg"
Cache-Control: public, max-age=2592000
```

---

## 6. 辅助文件

### 6.1 获取辅助文件

**接口**: `GET /auxi/{filename}`

**描述**: 获取辅助数据目录中的任意文件

**路径参数**:
- `filename`: 文件名（支持路径，如 `en.db`, `data/config.json`）

**安全限制**:
- 不允许路径遍历攻击（`..`）
- 不允许绝对路径（`/`）

**缓存**: 1天

**请求示例**:
```bash
# 下载辅助数据库
curl http://localhost:3070/auxi/en.db -o en.db

# 下载配置文件
curl http://localhost:3070/auxi/data/config.json -o config.json
```

---

## 性能优化

### 连接缓存

- **词典数据库连接**: 每个词典的连接在首次访问时建立并缓存
- **媒体数据库连接**: 每个词典的 media.db 连接在首次访问时建立并缓存
- **连接复用**: 后续请求复用已有连接，避免重复建立开销

### HTTP 缓存

不同资源使用不同的缓存策略：

| 资源类型 | 缓存时间 | 说明 |
|---------|---------|------|
| Logo | 30天 | 静态资源，很少变化 |
| 元数据 | 1天 | 可能偶尔更新 |
| 数据库 | 1天 | 可能偶尔更新 |
| 媒体数据库 | 30天 | 静态资源，很少变化 |
| 音频/图片 | 30天 | 静态资源，很少变化 |
| 辅助文件 | 1天 | 可能偶尔更新 |
| 词典列表 | 5分钟 | 可能频繁变化 |

### CORS 支持

所有接口都支持 CORS（跨域资源共享）：

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
| 500 | 服务器内部错误 |

### 错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

### 常见错误示例

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

**数据库连接失败**:
```json
{
  "detail": "Failed to connect to media database"
}
```

---

## 使用示例

### 完整的查词流程

```bash
# 1. 获取词典列表
curl http://localhost:3070/dictionaries

# 2. 查询单词
curl http://localhost:3070/word/ode_now/apple

# 3. 获取单词的发音音频
curl http://localhost:3070/audio/ode_now/apple_gb_1.opus -o apple.opus

# 4. 播放音频
# 使用你的音频播放器播放 apple.opus
```

### 下载完整的词典数据包

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

---

## 技术架构

### 后端技术栈

- **框架**: FastAPI
- **异步**: asyncio + aiosqlite
- **数据库**: SQLite3
- **Web服务器**: Uvicorn

### 前端代理

- **反向代理**: Nginx
- **负载均衡**: 支持
- **静态文件缓存**: 支持
- **Gzip 压缩**: 支持

---

## 附录

### MIME 类型映射

| 文件扩展名 | MIME 类型 |
|-----------|----------|
| .mp3 | audio/mpeg |
| .wav | audio/wav |
| .ogg | audio/ogg |
| .opus | audio/opus |
| .png | image/png |
| .jpg/.jpeg | image/jpeg |
| .gif | image/gif |
| .webp | image/webp |
| .svg | image/svg+xml |
| .db | application/vnd.sqlite3 |
| .json | application/json |

### 环境变量

| 变量名 | 默认值 | 说明 |
|-------|-------|------|
| DICTIONARIES_PATH | /data/dictionaries | 词典数据根目录 |
| AUXILIARY_PATH | /data/auxiliary | 辅助文件目录 |
| CACHE_PATH | /tmp/easydict-cache | 缓存目录 |
| PORT | 8080 | API 服务端口 |
| LOG_LEVEL | info | 日志级别 |

---

## 更新日志

### v2.0.0 (2026-02-04)

**重大变更**:
- ✨ 新增媒体数据库（media.db）支持
- 🔧 优化文件存储方式（从 ZIP 改为 SQLite3）
- ⚡ 性能优化：数据库连接缓存
- 📝 统一媒体文件下载接口为 `/download/{dict_id}/media`
- 🐛 修复：改进错误处理机制

**向后兼容**:
- ✅ 支持旧的目录结构（audios/, images/）
- ✅ 保留所有原有 API 接口

---

## 联系方式

如有问题或建议，请联系开发团队。
