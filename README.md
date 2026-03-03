# EasyDict Cloud

EasyDict 词典服务的 Docker 部署方案，提供词典查询、词典分发、用户认证和设置同步功能。

## 服务架构

```
                     ┌─────────────────────────────────────┐
                     │           Nginx (端口 3070)          │
                     │         反向代理 + 路由分发           │
                     └──────────────┬──────────────────────┘
                                    │
               ┌────────────────────┴────────────────────┐
               │                                         │
        ┌──────▼──────┐                          ┌───────▼──────┐
        │  API 服务    │                          │  User 服务   │
        │  (port 8080) │                          │  (port 8000) │
        │             │                          │              │
        │ 词典查询     │                          │ 用户注册登录  │
        │ 词典下载     │                          │ 设置同步      │
        │ 音频/图片    │                          │ 词典上传管理  │
        │ 辅助数据     │                          │              │
        └──────┬──────┘                          └───────┬──────┘
               │                                         │
               └────────────────┬────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │      数据目录          │
                    │  /data/dictionaries/  │  ← 词典数据
                    │  /data/auxiliary/     │  ← 辅助数据（en.db 等）
                    │  /data/user/          │  ← 用户数据（自动生成）
                    └───────────────────────┘
```

## 快速开始

### 前置要求

- Docker >= 20.10
- Docker Compose >= 2.0（或 docker-compose >= 1.29）

### 欢迎页面

访问根路径 `/` 可以看到一个友好的 HTML 欢迎页面，包含一个可爱的 SVG 小猫和 API 使用提示。这个页面提醒用户这是一个 API 服务，而非网页应用。

### 1. 克隆仓库

```bash
git clone git@github.com:AstraLeap/easydict-cloud.git
cd easydict-cloud/docker
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，**至少需要配置以下内容**：

```env
# 数据目录根路径（包含词典、用户数据等所有文件）
# 系统会自动在此目录下创建 dictionaries/、user/、auxiliary/ 等子目录
# 默认值：./easydict-data（相对于 docker-compose.yml）
DATA_PATH=./easydict-data

# JWT 密钥（建议设置，否则服务重启后所有用户 Token 失效）
JWT_SECRET=your_random_secret_here
```

或在启动 docker-compose 时指定：

```bash
DATA_PATH=/path/to/data docker-compose up -d
```

> 💡 **重要**：`DATA_PATH` 下的 `dictionaries/` 目录必须包含词典文件。如果目录为空，`/dictionaries` API 端点会返回空列表。

### 3. 准备词典数据

在 `DATA_PATH/dictionaries/` 目录下按以下结构放置词典数据：

```
./easydict-data/
├── dictionaries/            # 词典数据
│   ├── oxford/              # 词典 ID（可以是任意字符串）
│   │   ├── dictionary.db    # 词典数据库（SQLite，必须）
│   │   ├── metadata.json    # 词典元数据（必须）
│   │   ├── logo.png         # 词典图标（必须）
│   │   └── media.db         # 媒体数据库（可选）
│   └── collins/
│       ├── dictionary.db
│       ├── metadata.json
│       └── logo.png
├── user/                    # 用户数据（自动创建）
└── auxiliary/               # 辅助文件如 en.db（可选）
```

`metadata.json` 必须包含以下字段：

```json
{
  "id": "oxford",
  "name": "牛津高阶英汉双解词典",
  "source_language": "en",
  "target_language": "zh"
}
```

### 4. 启动服务

```bash
# 方式一：一键部署脚本（推荐）
chmod +x deploy.sh
./deploy.sh

# 方式二：手动启动
mkdir -p logs/nginx
docker compose up -d --build
```

### 5. 验证部署

```bash
# 健康检查
curl http://localhost:3070/health

# 查询词典列表
curl http://localhost:3070/dictionaries

# 查询单词
curl http://localhost:3070/word/oxford/hello
```

## API 接口

### 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 服务健康检查，返回 `{"status": "healthy"}` |

### 词典查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/dictionaries` | 获取所有词典列表及统计信息 |
| GET | `/word/{词典ID}/{单词}` | 查询单词，支持前缀匹配，最多返回 50 条 |
| GET | `/entry/{词典ID}/{词条ID}` | 按词条 ID 精确查询单条词条 |
| GET | `/audio/{词典ID}/{文件路径}` | 获取音频文件（mp3/wav/ogg） |
| GET | `/image/{词典ID}/{文件路径}` | 获取图片文件（png/jpg/gif/webp） |
| GET | `/auxi/{文件路径}` | 获取辅助数据文件（如 en.db） |

**查询单词示例响应（`entries` 为数据库原始 JSON，字段因词典而异）：**

```json
{
  "dict_id": "oxford",
  "word": "hello",
  "entries": [
    {
      "dict_id": "oxford",
      "entry_id": "1",
      "headword": "hello",
      "entry_type": "word",
      "pronunciation": [...],
      "sense_group": [...]
    }
  ],
  "total": 1
}
```

### 词典文件下载

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/download/{词典ID}/file/logo.png` | 下载词典图标 |
| GET | `/download/{词典ID}/file/metadata.json` | 下载词典元数据 |
| GET | `/download/{词典ID}/file/dictionary.db` | 下载词典数据库 |
| GET | `/download/{词典ID}/file/media.db` | 下载媒体数据库（音频/图片） |
| POST | `/download/{词典ID}/entries` | 批量下载条目，请求体为 `{"entries": [id1, id2, ...]}` ，返回 `.zst` 压缩的 JSONL 文件 |

### 用户认证

需要认证的接口须在请求头携带 Token：`Authorization: Bearer <token>`

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/user/register` | 否 | 注册，请求体：`{"username": "...", "email": "...", "password": "..."}` |
| POST | `/user/login` | 否 | 登录，请求体：`{"identifier": "用户名或邮箱", "password": "..."}` |
| GET | `/user/me` | 是 | 获取当前用户信息 |

**注册/登录响应：**

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {"id": 1, "username": "foo", "email": "foo@example.com"}
}
```

### 设置同步

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/user/settings` | 下载用户设置（返回 .zip 文件） |
| POST | `/user/settings` | 上传用户设置（multipart，字段名 `file`，必须是 .zip） |
| DELETE | `/user/settings` | 删除用户设置 |

### 词典管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/user/dicts` | 获取当前用户上传的词典列表 |
| POST | `/user/dicts` | 上传新词典（multipart，见下方说明） |
| POST | `/user/dicts/{词典ID}` | 更新已有词典（multipart，各文件字段均为可选） |
| DELETE | `/user/dicts/{词典ID}` | 删除词典 |
| POST | `/user/dicts/{词典ID}/entries` | 增量更新词条，上传 `.zst` 压缩的 JSONL 文件，支持 upsert 和删除（见下方说明） |

**上传新词典（multipart 字段）：**

| 字段名 | 必填 | 说明 |
|--------|------|------|
| `metadata_file` | 是 | `metadata.json`，必须包含 `id`、`name`、`source_language`、`target_language` |
| `dictionary_file` | 是 | `dictionary.db` SQLite 数据库 |
| `logo_file` | 是 | `logo.png` 词典图标 |
| `media_file` | 否 | `media.db` 媒体数据库（音频/图片） |
| `message` | 否 | 版本说明（默认"初始上传"） |

**增量更新词条（`POST /user/dicts/{词典ID}/entries`）：**

请求为 multipart/form-data，字段：

| 字段名 | 必填 | 说明 |
|--------|------|------|
| `file` | 是 | `.zst` 压缩文件，解压后为 JSONL，每行一条操作 |
| `message` | 否 | 版本说明（默认"更新条目"） |

JSONL 每行可以是 **upsert** 或 **删除** 操作，两种操作可混在同一文件中：

```jsonl
{"entry_id": 999, "headword": "apple", "entry_type": "word", ...}
{"entry_id": 23413, "_delete": true}
{"entry_id": 1423, "_delete": true}
```

- **upsert**：完整词条 JSON，有 `entry_id` 则更新，无则插入
- **删除**：仅需 `{"entry_id": <id>, "_delete": true}`

返回：`{"success": true, "version": 42}`

### 词典上传（大文件，upload 子域名专用）

通过 `upload.*` 子域名访问，绕过 Cloudflare 等 CDN 的文件大小限制，支持 10GB 以内的文件：

| 方法 | 路径（upload 子域名） | 说明 |
|------|------|------|
| POST | `/` | 上传新词典（同 `/user/dicts`） |
| POST | `/{词典ID}` | 更新已有词典（同 `/user/dicts/{词典ID}`） |

### 更新检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/update` | 批量查询多本词典的更新信息 |

查询参数格式：`{词典ID}={from_ver}` 或 `{词典ID}={from_ver}:{to_ver}`，每本词典一个参数，不指定 `to_ver` 则默认查询到最新版本。

```
/update?oxford=5&collins=0:10
```

**响应示例：**

```json
[
  {
    "dict_id": "oxford",
    "from": 5,
    "to": 8,
    "history": [
      {"v": 6, "m": "更新发音"},
      {"v": 8, "m": "新增词条"}
    ],
    "required": {
      "files": ["dictionary.db", "metadata.json"],
      "entries": [1024, 2048],
      "deleted_entries": [512]
    }
  },
  {
    "dict_id": "collins",
    "from": 0,
    "to": 10,
    "history": [...],
    "required": {...}
  }
]
```

词典不存在时该项返回 `{"dict_id": "...", "error": "not found"}`，不影响其他词典的查询结果。

`required.files` 表示需要整体重新下载的文件，`required.entries` 表示可增量 upsert 的词条 ID 列表，`required.deleted_entries` 表示需要从本地删除的词条 ID 列表（配合 `/download/{词典ID}/entries` 接口使用）。

## 环境变量说明

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `DATA_PATH` | 否 | `./easydict-data` | 数据目录根路径，系统会自动创建 dictionaries/、user/、auxiliary/ 子目录 |
| `JWT_SECRET` | 否 | 随机生成 | JWT 签名密钥，建议固定设置，否则重启后 Token 全部失效 |
| `LOG_LEVEL` | 否 | `info` | 日志级别 |
| `NGINX_PORT` | 否 | `3070` | Nginx 反向代理监听端口 |
| `API_PORT` | 否 | `8080` | API 服务监听端口 |
| `USER_PORT` | 否 | `8000` | 用户服务监听端口 |
| `API_INTERNAL_URL` | 否 | `http://api:8080` | API 内部地址（用户服务访问） |
| `CACHE_PATH` | 否 | `/tmp/easydict-cache` | 缓存目录路径 |
| `MAX_SETTINGS_FILE_SIZE` | 否 | `10485760` (10MB) | 用户设置 ZIP 文件上限 |
| `MAX_METADATA_FILE_SIZE` | 否 | `5242880` (5MB) | 元数据 JSON 文件上限 |
| `MAX_DICTIONARY_FILE_SIZE` | 否 | `2147483648` (2GB) | 词典数据库文件上限 |
| `MAX_MEDIA_FILE_SIZE` | 否 | `4294967296` (4GB) | 媒体数据库文件上限 |
| `MAX_ENTRIES_FILE_SIZE` | 否 | `524288000` (500MB) | 压缩条目文件上限 |

## 配置 HTTPS（可选）

服务默认监听 `3070` 端口（HTTP）。如需 HTTPS，在服务器层用 Nginx 做反向代理：

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:3070;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

也可以使用 Cloudflare 等 CDN，将 DNS 指向服务器 IP，开启 HTTPS 代理即可。

## 常用命令

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f

# 重新构建并启动
docker compose up -d --build

# 停止服务
docker compose down

# 进入容器调试
docker compose exec api /bin/sh
docker compose exec user /bin/sh
```

## 许可证

MIT License
