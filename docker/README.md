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
# 词典数据目录（必填）
DICTIONARIES_PATH=/data/dictionaries

# 辅助数据目录，存放 en.db 等文件（可选）
AUXILIARY_PATH=/data/auxiliary

# JWT 密钥（建议设置，否则服务重启后所有用户 Token 失效）
JWT_SECRET=your_random_secret_here
```

### 3. 准备词典数据

在 `DICTIONARIES_PATH` 目录下按以下结构放置词典数据：

```
/data/dictionaries/
├── oxford/                  # 词典 ID（可以是任意字符串）
│   ├── dictionary.db        # 词典数据库（SQLite，必须）
│   ├── metadata.json        # 词典元数据（必须）
│   ├── logo.png             # 词典图标（必须）
│   ├── media.db             # 媒体数据库（可选）
│   └── audios/              # 音频文件目录（可选）
│       └── hello.mp3
└── collins/
    ├── dictionary.db
    ├── metadata.json
    └── logo.png
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

### 词典查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/dictionaries` | 获取所有词典列表 |
| GET | `/word/{词典ID}/{单词}` | 查询单词 |
| GET | `/audio/{词典ID}/{文件名}` | 获取音频文件 |
| GET | `/image/{词典ID}/{文件名}` | 获取图片文件 |
| GET | `/auxi/{文件名}` | 获取辅助数据文件（如 en.db） |

### 词典下载

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/download/{词典ID}/logo` | 获取词典图标 |
| GET | `/download/{词典ID}/metadata` | 获取词典元数据 |
| GET | `/download/{词典ID}/database` | 下载词典数据库 |
| GET | `/download/{词典ID}/media` | 下载媒体数据库 |

### 用户服务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/user/register` | 用户注册 |
| POST | `/user/login` | 用户登录 |
| GET | `/settings` | 获取用户设置 |
| POST | `/settings` | 上传用户设置 |
| GET | `/user/dicts` | 获取用户词典列表 |

### 词典上传（贡献者）

词典上传通过 `upload.` 子域名进行，需在 Nginx/反向代理层配置域名路由：

| 方法 | 路径（upload 子域名） | 说明 |
|------|------|------|
| POST | `/` | 上传新词典 |
| POST | `/{词典ID}` | 更新已有词典 |

### 更新检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/update/{词典ID}` | 检查词典更新 |

## 环境变量说明

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `DICTIONARIES_PATH` | 是 | `/data/dictionaries` | 词典数据目录 |
| `AUXILIARY_PATH` | 否 | `/data/auxiliary` | 辅助数据目录 |
| `JWT_SECRET` | 否 | 随机生成 | JWT 签名密钥，建议固定设置，否则重启后 Token 全部失效 |
| `JWT_EXPIRE_HOURS` | 否 | `168` | Token 有效期（小时） |
| `LOG_LEVEL` | 否 | `info` | 日志级别 |

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

## 故障排查

### 词典无法查询

```bash
# 检查词典目录是否挂载正确
docker compose exec api ls /data/dictionaries/

# 检查数据库文件权限
chmod -R 755 $DICTIONARIES_PATH
```

### 用户服务异常

```bash
# 检查用户数据目录是否可写
docker compose exec user ls /data/user/

# 查看详细日志
docker compose logs user
```

### 查看 Nginx 访问日志

```bash
docker compose exec nginx cat /var/log/nginx/access.log
docker compose exec nginx cat /var/log/nginx/error.log
```

## 许可证

MIT License
