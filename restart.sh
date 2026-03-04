#!/bin/bash

# EasyDict Docker 快速重启脚本（仅重启容器，不重建镜像）

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}  EasyDict Docker 快速重启${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# 加载 .env 文件
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)
fi

# 确定使用的 docker compose 命令
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo -e "${GREEN}重启所有容器...${NC}"
$COMPOSE_CMD restart

echo ""
echo -e "${BLUE}等待服务启动...${NC}"
sleep 3

echo ""
echo -e "${BLUE}容器状态:${NC}"
$COMPOSE_CMD ps

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}  重启完成!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "等待健康检查通过（最多30秒）..."
echo ""

# 等待服务健康
max_attempts=12
attempt=1
while [ $attempt -le $max_attempts ]; do
    echo -ne "${BLUE}[${attempt}/${max_attempts}]${NC} 检查服务健康状态... "
    
    if curl -s http://localhost/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 所有服务正常${NC}"
        echo ""
        exit 0
    fi
    
    echo -e "${YELLOW}等待中...${NC}"
    sleep 2.5
    attempt=$((attempt + 1))
done

echo ""
echo -e "${YELLOW}警告: 部分服务可能未完全就绪，请查看日志:${NC}"
echo "  $COMPOSE_CMD logs -f"
