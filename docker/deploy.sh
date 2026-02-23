#!/bin/bash

# EasyDict Docker 部署脚本

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}  EasyDict Docker 部署脚本${NC}"
echo -e "${GREEN}================================${NC}"
echo ""

# 加载 .env 文件
if [ -f .env ]; then
    echo -e "${GREEN}加载环境变量从 .env 文件...${NC}"
    export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)
    echo ""
fi

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: Docker 未安装${NC}"
    echo "请先安装 Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# 检查 Docker Compose 是否安装
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}错误: Docker Compose 未安装${NC}"
    echo "请先安装 Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# 检查词典数据目录
if [ -z "$DICTIONARIES_PATH" ]; then
    DICTIONARIES_PATH="/data/dictionaries"
    echo -e "${YELLOW}警告: 未设置 DICTIONARIES_PATH 环境变量${NC}"
    echo -e "使用默认路径: ${DICTIONARIES_PATH}"
    echo ""
fi

# 检查词典目录是否存在
if [ ! -d "$DICTIONARIES_PATH" ]; then
    echo -e "${YELLOW}警告: 词典目录不存在: $DICTIONARIES_PATH${NC}"
    echo "请确保词典数据已正确挂载到该目录"
    echo ""
    echo "目录结构示例:"
    echo "  $DICTIONARIES_PATH/"
    echo "  ├── dictid653/"
    echo "  │   ├── dictionary.db"
    echo "  │   ├── audios/"
    echo "  │   │   └── example.mp3"
    echo "  │   └── images/"
    echo "  │       └── example.png"
    echo "  └── dictid654/"
    echo "      └── ..."
    echo ""
    read -p "是否继续? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 创建必要的目录
echo -e "${GREEN}创建必要的目录...${NC}"
mkdir -p logs/nginx

# 构建并启动服务
echo -e "${GREEN}构建并启动服务...${NC}"

# 使用 docker compose (新版) 或 docker-compose (旧版)
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# 构建镜像
$COMPOSE_CMD build

# 启动服务
$COMPOSE_CMD up -d

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}  部署成功!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "服务状态:"
$COMPOSE_CMD ps
echo ""
echo "访问地址:"
echo "  - 健康检查: http://localhost/health"
echo "  - API 文档: http://localhost/docs"
echo "  - 词典查询示例: http://localhost/dictid653/word/example"
echo ""
echo "查看日志:"
echo "  $COMPOSE_CMD logs -f"
echo ""
echo "停止服务:"
echo "  $COMPOSE_CMD down"
echo ""
