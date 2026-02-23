# EasyDict Docker 部署指南

本文档介绍如何在服务器上部署 EasyDict 词典服务。

## 目录结构

```
docker/
├── docker-compose.yml    # Docker Compose 配置文件
├── nginx.conf            # Nginx 反向代理配置
├── deploy.sh             # 一键部署脚本
├── .env.example          # 环境变量示例
├── README.md             # 本文件
├── logs/                 # 日志目录（自动生成）
└── api/                  # 后端 API 服务
    ├── Dockerfile
    ├── main.py
    └── requirements.txt
```

## 快速开始

### 1. 准备词典数据

在服务器上准备词典数据目录，结构如下：

```
/data/dictionaries/           # 词典数据根目录
├── 653/                     # 词典 ID 目录（可以是数字）
│   ├── dictionary.db        # 词典数据库（SQLite）
│   ├── audios/              # 音频文件目录
│   │   ├── example.mp3
│   │   └── hello.mp3
│   └── images/              # 图片文件目录
│       ├── example.png
│       └── diagram.png
├── dictid654/               # 词典 ID 目录（可以是任意字符串）
│   ├── dictionary.db
│   ├── audios/
│   └── images/
├── oxford/                  # 词典 ID 目录（可以是英文名称）
│   ├── dictionary.db
│   ├── audios/
│   └── images/
└── ...
```

### 2. 配置环境变量

```bash
# 复制环境变量示例文件
cp .env.example .env

# 编辑 .env 文件，设置词典数据路径
vim .env
```

`.env` 文件内容示例：

```env
DICTIONARIES_PATH=/data/dictionaries
```

### 3. 部署服务

#### 方式一：使用部署脚本（推荐）

```bash
chmod +x deploy.sh
./deploy.sh
```

#### 方式二：手动部署

```bash
# 创建日志目录
mkdir -p logs/nginx

# 构建并启动服务
docker-compose up -d --build

# 或使用新版 Docker Compose
docker compose up -d --build
```

### 4. 验证部署

```bash
# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 测试健康检查
curl http://localhost/health

# 测试词典查询
curl http://localhost/dictid653/word/example
```

## API 接口说明

### 1. 查询单词

```
GET /{词典ID}/word/{单词}
```

**示例：**

```bash
# 使用数字 ID
curl http://easydict.org/653/word/example

# 使用自定义 ID
curl http://easydict.org/dictid653/word/example
curl http://easydict.org/oxford/word/hello
```

**响应：**

```json
{
  "dict_id": "653",
  "word": "example",
  "entries": [
    {
      "id": "1",
      "headword": "example",
      "entry_type": "word",
      "pronunciations": [...],
      "senses": [...]
    }
  ],
  "total": 1
}
```

### 2. 获取音频文件

```
GET /{词典ID}/audio/{文件名}.mp3
```

**示例：**

```bash
curl http://easydict.org/653/audio/example.mp3
curl http://easydict.org/oxford/audio/hello.mp3
```

### 3. 获取图片文件

```
GET /{词典ID}/image/{文件名}.png
```

**示例：**

```bash
curl http://easydict.org/653/image/example.png
curl http://easydict.org/oxford/image/diagram.png
```

### 4. 健康检查

```
GET /health
```

### 5. 列出所有词典（词典商店）

```
GET /dictionaries
```

**响应：**

```json
{
  "dictionaries": [
    {
      "id": "653",
      "name": "牛津高阶词典",
      "description": "经典英语学习词典",
      "version": "1.0.0",
      "author": "Oxford",
      "language": "en",
      "entry_count": 185000,
      "has_database": true,
      "has_audios": true,
      "has_images": true,
      "has_logo": true,
      "has_metadata": true,
      "audio_count": 50000,
      "image_count": 2000,
      "database_size": 52428800
    }
  ]
}
```

### 6. 获取词典详情

```
GET /dictionaries/{词典ID}
```

**示例：**

```bash
curl http://easydict.org/dictionaries/653
```

### 7. 获取词典 Logo

```
GET /dictionaries/{词典ID}/logo
```

**示例：**

```bash
curl http://easydict.org/dictionaries/653/logo -o logo.png
```

### 8. 获取词典元数据

```
GET /dictionaries/{词典ID}/metadata
```

**示例：**

```bash
curl http://easydict.org/dictionaries/653/metadata
```

### 9. 下载词典（支持选择性下载）

```
GET /dictionaries/{词典ID}/download?db={0|1}&audios={0|1}&images={0|1}
```

**参数：**

- `db`: 是否包含数据库文件 (默认: 1)
- `audios`: 是否包含音频文件 (默认: 0)
- `images`: 是否包含图片文件 (默认: 0)

**注意：** `metadata.json` 和 `logo.png` 始终包含

**示例：**

```bash
# 仅下载数据库（最小安装）
curl http://easydict.org/dictionaries/653/download?db=1 -o 653_db.tar

# 下载数据库+音频
curl http://easydict.org/dictionaries/653/download?db=1&audios=1 -o 653_db_audios.tar

# 完整下载
curl http://easydict.org/dictionaries/653/download?db=1&audios=1&images=1 -o 653_full.tar
```

## Nginx 配置说明

`nginx.conf` 中配置了三个主要路由：

1. **单词查询** (`/{词典ID}/word/{单词}`)
   - 转发到后端 API 服务
   - 查询 SQLite 数据库返回 JSON

2. **音频文件** (`/{词典ID}/audio/{文件名}.mp3`)
   - Nginx 直接提供静态文件
   - 路径映射：`/data/dictionaries/{词典ID}/audios/`

3. **图片文件** (`/{词典ID}/image/{文件名}.png`)
   - Nginx 直接提供静态文件
   - 路径映射：`/data/dictionaries/{词典ID}/images/`

## 域名配置

如果你使用 `https://easydict.org`，需要在服务器上配置反向代理：

### 使用 Nginx（服务器层面）

```nginx
server {
    listen 443 ssl http2;
    server_name easydict.org;

    # SSL 配置
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:80;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name easydict.org;
    return 301 https://$server_name$request_uri;
}
```

### 使用 Cloudflare 等 CDN

如果使用 Cloudflare，只需：

1. 将域名 DNS 指向服务器 IP
2. 在 Cloudflare 开启 HTTPS
3. 服务器上保持 HTTP（80端口）即可

## 常用命令

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 查看日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f api
docker-compose logs -f nginx

# 重新构建并启动
docker-compose up -d --build

# 进入容器调试
docker-compose exec api /bin/sh
docker-compose exec nginx /bin/sh
```

## 故障排查

### 1. 词典数据库无法访问

检查词典目录权限：

```bash
# 检查目录是否存在
ls -la $DICTIONARIES_PATH

# 检查数据库文件
ls -la $DICTIONARIES_PATH/dictid653/dictionary.db

# 检查文件权限
chmod -R 755 $DICTIONARIES_PATH
```

### 2. 音频/图片文件 404

检查文件路径：

```bash
# 检查音频文件
ls -la $DICTIONARIES_PATH/dictid653/audios/

# 检查图片文件
ls -la $DICTIONARIES_PATH/dictid653/images/
```

### 3. 查看详细日志

```bash
# API 服务日志
docker-compose logs api

# Nginx 访问日志
docker-compose exec nginx cat /var/log/nginx/access.log

# Nginx 错误日志
docker-compose exec nginx cat /var/log/nginx/error.log
```

### 4. 数据库连接问题

进入 API 容器检查：

```bash
docker-compose exec api /bin/sh

# 检查词典目录
ls -la /data/dictionaries/

# 测试数据库连接
python -c "import sqlite3; conn = sqlite3.connect('/data/dictionaries/dictid653/dictionary.db'); print('OK')"
```

## 性能优化

### 1. 启用 Nginx 缓存

已在 `nginx.conf` 中配置静态文件缓存：

```nginx
# 音频/图片缓存 30 天
expires 30d;
add_header Cache-Control "public, immutable";
```

### 2. 数据库连接池

API 服务已内置数据库连接缓存，避免重复连接。

### 3. 使用 CDN

对于音频和图片文件，建议使用 CDN（如 Cloudflare、阿里云 CDN）加速。

## 安全建议

1. **使用 HTTPS**：生产环境务必启用 HTTPS
2. **限制访问**：使用防火墙限制端口访问
3. **定期备份**：定期备份词典数据
4. **日志监控**：配置日志监控和告警

## 更新维护

### 更新代码

```bash
# 拉取最新代码
git pull

# 重新构建并启动
docker-compose up -d --build
```

### 更新词典数据

直接替换服务器上的词典文件即可，无需重启服务：

```bash
# 替换数据库文件
cp new_dictionary.db /data/dictionaries/dictid653/dictionary.db

# 添加新的音频/图片文件
cp new_audio.mp3 /data/dictionaries/dictid653/audios/
```

## 许可证

MIT License
