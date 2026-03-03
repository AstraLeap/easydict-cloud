#!/bin/bash

# EasyDict Docker 优化脚本

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}  EasyDict 优化脚本${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# 1. 清理 Docker 资源
echo -e "${YELLOW}1. 清理未使用的 Docker 资源...${NC}"
docker system prune -f --volumes

# 2. 设置日志轮转
echo -e "${YELLOW}2. 配置日志轮转...${NC}"
if [ -f /etc/cron.daily/docker-logrotate ]; then
    sudo cp logrotate.conf /etc/cron.daily/docker-logrotate
    sudo chmod +x /etc/cron.daily/docker-logrotate
    echo "日志轮转已配置"
else
    echo "跳过：需要 root 权限"
fi

# 3. 清理缓存
echo -e "${YELLOW}3. 清理 API 缓存...${NC}"
docker exec easydict-api curl -X DELETE http://localhost:8080/cache 2>/dev/null || echo "缓存清理完成或无需清理"

# 4. 检查磁盘使用
echo -e "${YELLOW}4. 磁盘使用情况：${NC}"
du -sh /home/karx/easydict/dicts/* 2>/dev/null | sort -hr

echo ""
echo -e "${GREEN}优化完成！${NC}"
echo ""
echo "建议："
echo "  - 定期运行此脚本（建议每周一次）"
echo "  - 监控容器资源使用：docker stats"
echo "  - 查看日志：docker-compose logs -f"
