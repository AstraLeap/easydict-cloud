# EasyDict 配置升级指南 (v2.0)

## 概述

EasyDict v2.0 简化了环境变量配置，从多个路径配置合并为单个 `DATA_PATH` 配置。系统会自动在 `DATA_PATH` 下创建子目录。

### 变更总结

| 项目 | 旧配置 | 新配置 |
|------|--------|--------|
| 配置方式 | 三个独立路径变量 | 一个根路径变量 |
| 词典数据 | `DICTIONARIES_PATH=/data/dictionaries` | `DATA_PATH=./easydict-data` (自动在 `./easydict-data/dictionaries/`) |
| 用户数据 | `USER_DATA_PATH=/data/user` | 自动在 `./easydict-data/user/` |
| 辅助文件 | `AUXILIARY_PATH=/data/auxiliary` | 自动在 `./easydict-data/auxiliary/` |

## 升级步骤

### 第 1 步：备份现有数据

```bash
# 备份所有重要数据
cp -r /data/dictionaries ~/easydict-dictionaries-backup
cp -r /data/user ~/easydict-user-backup
cp -r /data/auxiliary ~/easydict-auxiliary-backup
```

### 第 2 步：更新 `.env` 配置

**旧配置示例：**
```env
DICTIONARIES_PATH=/data/dictionaries
USER_DATA_PATH=/data/user
AUXILIARY_PATH=/data/auxiliary
JWT_SECRET=your_secret_key
```

**新配置示例：**
```env
# 简单得多！只需配置一个根目录
DATA_PATH=./easydict-data
JWT_SECRET=your_secret_key
```

### 第 3 步：组织数据目录结构

新的目录结构应该是这样的：

```
easydict-data/
├── dictionaries/           # 所有词典放在这里
│   ├── ode_now/
│   │   ├── dictionary.db
│   │   ├── metadata.json
│   │   ├── logo.png
│   │   └── media.db (可选)
│   └── collins/
│       ├── dictionary.db
│       ├── metadata.json
│       └── logo.png
├── user/                   # 用户数据（自动创建）
│   └── user.db
└── auxiliary/              # 辅助文件（如 en.db）
    └── en.db (可选)
```

### 第 4 步：迁移数据

#### 选项 A：快速迁移（推荐用于本地开发）

```bash
# 假设你的项目目录是 /home/karx/easydict

# 1. 创建新的数据目录结构
mkdir -p easydict-data/{dictionaries,user,auxiliary}

# 2. 复制词典数据
cp -r /data/dictionaries/* easydict-data/dictionaries/

# 3. 复制用户数据（如果有的话）
if [ -d /data/user ]; then
    cp -r /data/user/* easydict-data/user/
fi

# 4. 复制辅助文件（如果有的话）
if [ -d /data/auxiliary ]; then
    cp -r /data/auxiliary/* easydict-data/auxiliary/
fi

# 5. 验证目录结构
tree easydict-data/
```

#### 选项 B：从现有位置创建符号链接（保持原有存储位置）

```bash
# 如果你想保持原有的数据位置不变，可以使用符号链接
mkdir -p easydict-data

# 创建符号链接
ln -s /data/dictionaries easydict-data/dictionaries
ln -s /data/user easydict-data/user
ln -s /data/auxiliary easydict-data/auxiliary
```

#### 选项 C：远程服务器迁移（带 rsync）

```bash
# 从远程服务器拉取数据
rsync -avz --progress remote-user@remote-server:/data/dictionaries ./easydict-data/
rsync -avz --progress remote-user@remote-server:/data/user ./easydict-data/
rsync -avz --progress remote-user@remote-server:/data/auxiliary ./easydict-data/
```

### 第 5 步：验证数据

```bash
# 检查词典文件是否完整
ls -la easydict-data/dictionaries/ode_now/

# 验证数据库文件
file easydict-data/dictionaries/ode_now/dictionary.db

# （可选）检查数据库完整性
sqlite3 easydict-data/dictionaries/ode_now/dictionary.db "PRAGMA integrity_check;"
```

### 第 6 步：更新 Docker Compose 配置

如果使用 Docker，新的 `docker-compose.yml` 已经自动更新。只需确保：

```yaml
volumes:
  - ${DATA_PATH:-./easydict-data}:/data/easydict
```

### 第 7 步：重启服务

```bash
# 停止现有服务
docker-compose down

# 重新启动（会自动应用新配置）
docker-compose up -d

# 检查服务状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

### 第 8 步：验证服务

```bash
# 健康检查
curl http://localhost:3070/health

# 测试词典查询
curl http://localhost:3070/ode_now/word/blue

# 查看词典列表
curl http://localhost:3070/dictionaries
```

## 常见问题

### Q: 为什么要进行这个改变？

A: 新配置更简洁直观，用户只需配置一个根目录，系统会自动组织子目录。这样：
- 配置更简单
- 数据更集中
- Docker 挂载更清晰
- 易于备份和迁移

### Q: 我可以保留旧的 `/data` 目录结构吗？

A: 可以！使用符号链接方案（选项 B），这样就不用移动数据。

### Q: 如果我已经有 `easydict-data` 目录怎么办？

A: 直接覆盖或合并即可。新的配置完全兼容。

### Q: Docker 容器内的路径是什么？

A: 
- 容器内数据根目录: `/data/easydict`
- 容器内词典目录: `/data/easydict/dictionaries`
- 容器内用户目录: `/data/easydict/user`
- 容器内辅助目录: `/data/easydict/auxiliary`

### Q: 如何在 Docker 中使用不同的数据路径？

A: 在启动时指定 `DATA_PATH` 环境变量：

```bash
# 方法 1：使用 .env 文件
echo "DATA_PATH=/mnt/data" >> .env
docker-compose up -d

# 方法 2：命令行
DATA_PATH=/mnt/data docker-compose up -d

# 方法 3：修改 docker-compose.yml
# 将 ${DATA_PATH:-./easydict-data} 替换为实际路径
```

### Q: 升级过程中数据会丢失吗？

A: 不会！我们在第 1 步做了完整备份。只要按步骤操作，数据是完全安全的。

### Q: 如何回滚到旧配置？

A: 
```bash
# 恢复旧配置文件
git checkout .env docker-compose.yml

# 或从备份恢复
cp ~/easydict-dictionaries-backup/* /data/dictionaries/
```

## 升级检查清单

- [ ] 已备份现有数据
- [ ] 已更新 `.env` 文件为新的 `DATA_PATH` 格式
- [ ] 已创建 `easydict-data/` 目录结构
- [ ] 已迁移或链接所有数据文件
- [ ] 已验证数据完整性（特别是 `.db` 文件）
- [ ] 已更新 `docker-compose.yml`（如使用 Docker）
- [ ] 已重启服务
- [ ] 已验证服务正常运行和数据可访问
- [ ] 已删除或存档旧的数据目录（可选）

## 获取帮助

如果在升级过程中遇到问题：

1. 检查日志：
   ```bash
   docker-compose logs -f
   ```

2. 验证目录权限：
   ```bash
   ls -la easydict-data/
   chmod -R 755 easydict-data/
   ```

3. 测试数据库：
   ```bash
   sqlite3 easydict-data/dictionaries/ode_now/dictionary.db ".tables"
   ```

4. 查看源代码中的路径配置：
   - API: `api/main.py` 第 52-56 行
   - User: `user/main.py` 第 39-42 行
