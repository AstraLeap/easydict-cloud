# EasyDict Docker 优化指南

## 📋 已完成的优化

### 1. 性能优化
- ✅ **Uvicorn Workers 动态调整**: 根据 CPU 核心数自动设置 worker 数量
- ✅ **使用 uvloop**: 更高性能的事件循环
- ✅ **Nginx Gzip 压缩**: 减少传输数据量
- ✅ **连接保活**: 优化 TCP 连接

### 2. 资源管理
- ✅ **CPU 限制**: API 最多 2 核，Nginx 最多 1 核
- ✅ **内存限制**: API 最多 1GB，Nginx 最多 512MB
- ✅ **资源预留**: 保证最小资源分配

### 3. 健康检查
- ✅ **API 健康检查**: 每 30 秒检查一次
- ✅ **Nginx 健康检查**: 每 30 秒检查一次
- ✅ **自动重启**: 失败后自动重启

### 4. 安全性
- ✅ **安全响应头**: X-Frame-Options, X-Content-Type-Options, X-XSS-Protection
- ✅ **只读挂载**: 词典数据以只读方式挂载

### 5. 日志管理
- ✅ **日志轮转配置**: 保留 14 天，自动压缩
- ✅ **错误日志级别**: warn 级别减少日志量

## 🔧 应用优化

### 重新构建并启动
```bash
cd /home/karx/easydict/docker
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## 📊 监控命令

### 实时资源使用
```bash
docker stats
```

### 查看日志
```bash
# 所有日志
docker-compose logs -f

# API 日志
docker logs -f easydict-api

# Nginx 日志
tail -f logs/nginx/access.log
tail -f logs/nginx/error.log
```

### 容器状态
```bash
docker ps
docker-compose ps
```

## 🧹 定期维护

### 运行优化脚本
```bash
./optimize.sh
```

这个脚本会：
1. 清理未使用的 Docker 资源
2. 配置日志轮转
3. 清理 API 缓存
4. 显示磁盘使用情况

### 手动清理缓存
```bash
curl -X DELETE http://localhost:3070/cache
```

## 🎯 进一步优化建议

### 1. 添加 Redis 缓存层
```yaml
# docker-compose.yml
redis:
  image: redis:alpine
  container_name: easydict-redis
  restart: unless-stopped
  networks:
    - easydict-network
```

优点：
- 减少数据库查询
- 提高响应速度
- 降低 API 负载

### 2. 启用 Nginx 缓存
```nginx
# 在 nginx.conf 中添加
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=easydict:10m max_size=1g inactive=60m;

location ~ ^/([^/]+)/word/(.+)$ {
    proxy_cache easydict;
    proxy_cache_valid 200 10m;
    # ... 其他配置
}
```

### 3. 添加 Prometheus 监控
```yaml
# 添加监控服务
prometheus:
  image: prom/prometheus
  volumes:
    - ./prometheus.yml:/etc/prometheus/prometheus.yml
  ports:
    - "9090:9090"

grafana:
  image: grafana/grafana
  ports:
    - "3000:3000"
```

### 4. 使用 CDN
- 将静态资源（音频、图片）上传到 CDN
- 减少 Nginx 负载
- 提高全球访问速度

### 5. 数据库优化
```sql
-- 添加索引
CREATE INDEX idx_headword ON entries(headword);
CREATE INDEX idx_senses ON entries USING GIN(senses);
```

### 6. 启用 HTTP/2
```nginx
listen 443 ssl http2;
# 配置 SSL 证书
```

## 📈 性能基准测试

### 测试 API 响应时间
```bash
# 安装 ab (Apache Bench)
sudo apt-get install apache2-utils

# 测试
ab -n 1000 -c 10 http://localhost:3070/dictionaries
```

### 测试并发性能
```bash
# 使用 wrk
wrk -t4 -c100 -d30s http://localhost:3070/dictid653/word/example
```

## 🚨 故障排查

### 容器内存不足
```bash
# 查看容器内存使用
docker stats --no-stream

# 增加内存限制
# 编辑 docker-compose.yml
```

### 端口冲突
```bash
# 查看端口占用
sudo lsof -i :3070

# 修改端口
# 编辑 docker-compose.yml 中的端口映射
```

### 日志文件过大
```bash
# 手动清理
> logs/nginx/access.log
> logs/nginx/error.log

# 或运行优化脚本
./optimize.sh
```

## 🔄 更新部署

### 更新代码
```bash
git pull
docker-compose build
docker-compose up -d
```

### 零停机部署
```bash
# 启动新容器
docker-compose up -d --scale api=2 --no-recreate

# 优雅停止旧容器
docker-compose up -d --scale api=1
```

## 📞 技术支持

遇到问题？检查以下内容：
1. 容器状态: `docker ps`
2. 日志: `docker-compose logs`
3. 资源使用: `docker stats`
4. 端口监听: `docker port easydict-nginx`
