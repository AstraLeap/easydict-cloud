# EasyDict Docker 迁移指南

## 快速迁移步骤

### 1. 准备目标系统
确保目标系统已安装：
- Docker (>= 20.10)
- Docker Compose (>= 2.0)

```bash
docker --version
docker-compose --version
```

### 2. 打包项目文件

```bash
# 在源系统上，进入 docker 目录
cd /home/karx/easydict/docker

# 打包项目配置文件（不需要打包词典数据）
tar czf easydict-docker-config.tar.gz \
    docker-compose.yml \
    nginx.conf \
    .env \
    api/

# 查看 tar 包内容
tar tzf easydict-docker-config.tar.gz
```

### 3. 迁移词典数据

```bash
# 方式1: 直接复制目录（推荐用于小型词典）
rsync -avz /home/karx/easydict/dicts/ user@target-server:/path/to/dictionaries/

# 方式2: 打包后传输
cd /home/karx/easydict
tar czf dictionaries.tar.gz dicts/
scp dictionaries.tar.gz user@target-server:/tmp/
```

### 4. 在目标系统上部署

```bash
# 1. 解压项目配置
mkdir -p ~/easydict-docker
cd ~/easydict-docker
tar xzf /path/to/easydict-docker-config.tar.gz

# 2. 解压词典数据（如果使用了打包方式）
mkdir -p ~/dictionaries
cd ~/
tar xzf /tmp/dictionaries.tar.gz -C ~/dictionaries

# 3. 修改配置参数
vim .env
```

## 必须修改的配置参数

### `.env` 文件（重要！）

```bash
# 修改词典数据路径为目标系统的实际路径
DICTIONARIES_PATH=/home/youruser/dictionaries

# 可选：修改日志级别
LOG_LEVEL=info  # 可选: debug, info, warning, error
```

### 可选配置修改

#### 1. 修改端口（如果 3070 端口被占用）
编辑 `docker-compose.yml` 第 9 行：
```yaml
ports:
  - "8080:80"  # 将外部端口改为其他值，如 8080
```

#### 2. 调整资源限制（根据目标系统性能）
编辑 `docker-compose.yml` 第 18-25 行（nginx）和 57-64 行（api）：

**高性能服务器**：
```yaml
deploy:
  resources:
    limits:
      cpus: '4'      # 增加CPU限制
      memory: 2G     # 增加内存限制
    reservations:
      cpus: '1'
      memory: 512M
```

**低性能服务器**：
```yaml
deploy:
  resources:
    limits:
      cpus: '1'
      memory: 512M
    reservations:
      cpus: '0.25'
      memory: 128M
```

#### 3. 修改容器名称（避免多系统冲突）
编辑 `docker-compose.yml` 第 7 和 43 行：
```yaml
container_name: easydict-nginx   # 改为唯一名称，如 easydict-nginx-prod
container_name: easydict-api     # 改为唯一名称，如 easydict-api-prod
```

### 5. 启动服务

```bash
# 创建必要的目录
mkdir -p logs/nginx

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 检查服务状态
docker-compose ps
```

### 6. 验证部署

```bash
# 健康检查
curl http://localhost:3070/health

# 测试词典查询
curl http://localhost:3070/ode_now/word/blue

# 查看词典列表
curl http://localhost:3070/dictionaries
```

## 常见问题

### 问题1：端口被占用
```bash
# 查看端口占用
sudo lsof -i :3070

# 解决：修改 docker-compose.yml 中的端口映射
ports:
  - "3080:80"  # 使用其他端口
```

### 问题2：权限问题
```bash
# 确保词典数据目录可读
chmod -R 755 /path/to/dictionaries
```

### 问题3：容器无法启动
```bash
# 查看详细日志
docker-compose logs api
docker-compose logs nginx

# 重新构建镜像
docker-compose up -d --build
```

### 问题4：数据库文件损坏
```bash
# 检查数据库文件
file /path/to/dictionaries/ode_now/dictionary.db

# 验证数据库（需要 sqlite3）
sqlite3 /path/to/dictionaries/ode_now/dictionary.db "PRAGMA integrity_check;"
```

## 配置文件总览

```
easydict-docker/
├── docker-compose.yml    # 容器编排配置
├── nginx.conf           # Nginx 反向代理配置
├── .env                 # 环境变量配置
├── api/
│   ├── Dockerfile       # API 服务镜像定义
│   ├── main.py          # API 服务代码
│   └── requirements.txt # Python 依赖
└── logs/
    └── nginx/           # Nginx 日志目录
```

## 数据目录结构

```
dictionaries/
└── ode_now/             # 词典ID
    ├── dictionary.db    # SQLite 数据库
    ├── audios/          # 音频文件目录
    │   └── blue__gb_1.ogg
    ├── images/          # 图片文件目录
    │   └── logo.png
    ├── logo.png         # 词典 Logo（可选）
    └── metadata.json    # 词典元数据（可选）
```

## 迁移检查清单

- [ ] Docker 和 Docker Compose 已安装
- [ ] 已修改 `.env` 中的 `DICTIONARIES_PATH`
- [ ] 词典数据已完整迁移
- [ ] 目录权限正确（755）
- [ ] 端口未被占用（或已修改配置）
- [ ] 服务正常启动（`docker-compose ps`）
- [ ] 健康检查通过（`curl /health`）
- [ ] 词典查询测试成功

## 一键部署脚本（可选）

创建 `deploy.sh`：
```bash
#!/bin/bash
set -e

echo "EasyDict Docker 一键部署脚本"

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: Docker 未安装"
    exit 1
fi

# 读取配置
source .env

# 检查词典目录
if [ ! -d "$DICTIONARIES_PATH" ]; then
    echo "错误: 词典目录不存在: $DICTIONARIES_PATH"
    exit 1
fi

# 创建日志目录
mkdir -p logs/nginx

# 启动服务
echo "启动服务..."
docker-compose up -d

# 等待服务启动
sleep 5

# 健康检查
echo "执行健康检查..."
if curl -f http://localhost:3070/health &> /dev/null; then
    echo "✓ 服务启动成功！"
    echo "访问地址: http://localhost:3070"
else
    echo "✗ 服务启动失败，请查看日志"
    docker-compose logs
fi
```

使用方法：
```bash
chmod +x deploy.sh
./deploy.sh
```
