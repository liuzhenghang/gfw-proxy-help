#!/bin/bash

# 镜像名称
IMAGE_NAME="gfw-proxy-help"

echo "正在构建Docker镜像: $IMAGE_NAME"

# 构建镜像
docker build -t $IMAGE_NAME .

if [ $? -eq 0 ]; then
    echo "✅ 镜像构建成功！"
    echo ""
    echo "运行命令："
    echo "docker run -d -p 6789:6789 --name gfw-proxy-help-container $IMAGE_NAME"
    echo ""
    echo "停止容器："
    echo "docker stop gfw-proxy-help-container"
    echo ""
    echo "删除容器："
    echo "docker rm gfw-proxy-help-container"
    echo ""
    echo "查看日志："
    echo "docker logs -f gfw-proxy-help-container"
    echo ""
    echo "测试接口："
    echo "curl http://localhost:6789/health"
else
    echo "❌ 镜像构建失败！"
    exit 1
fi 