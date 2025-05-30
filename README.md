# GFW Proxy Helper

一个基于Flask的代理服务，用于处理Clash配置请求。
有的机场要求客户端版本，使用openwrt-OpenClash的用户没办法获取到订阅信息，实测OpenClash内的ua设置无效，这里写了个代理请求，指定UA如下，这样就可以使用OpenClash来订阅机场了

可以部署在软理由、群晖、云主机等任何地方，只需构建Docker即可
## 功能特性

- 🚀 基于Flask框架，轻量高效
- 🔐 支持Base64解码URL
- 🌐 使用clash-verge/v2.1.2 User-Agent
- 🐳 支持Docker部署
- 📊 内置健康检查

## API接口

### GET /clash

代理Clash配置请求

**参数：**
- `url`: Base64编码的目标URL
- `ua`: 可选的User-Agent，默认为clash-verge/v2.1.2

**示例：**
```bash
# 先将URL进行Base64编码
echo "https://example.com/clash-config" | base64

# 然后请求接口
curl "http://localhost:6789/clash?url=aHR0cHM6Ly9leGFtcGxlLmNvbS9jbGFzaC1jb25maWcK"
```

### GET /clash_convert

Clash配置转换接口

**参数：**
- `url`: Base64编码的订阅URL
- `config`: Base64编码的配置内容
- `convert_url`: Base64编码的转换服务URL

**功能：**
向指定的转换服务发送请求，自动添加以下参数：
- target=clash
- new_name=true
- emoji=true
- udp=true
- scv=true
- fdn=true
- classic=true
- 其他转换参数

**示例：**
```bash
# Base64编码各个参数
subscription_url=$(echo "https://example.com/subscription" | base64)
config_content=$(echo "your-config-content" | base64)
converter_url=$(echo "https://api.v1.mk/sub" | base64)

# 请求转换接口
curl "http://localhost:6789/clash_convert?url=${subscription_url}&config=${config_content}&convert_url=${converter_url}"
```

### GET /health

健康检查接口

**响应：**
```json
{
  "status": "ok",
  "message": "服务运行正常"
}
```

### GET /

服务信息接口

## 本地开发

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 运行服务：
```bash
python app.py
```

服务将在 `http://0.0.0.0:6789` 启动。

## Docker部署

1. 构建镜像：
```bash
chmod +x build.sh
./build.sh
```

2. 运行容器：
```bash
docker run -d -p 6789:6789 --name gfw-proxy-help-container gfw-proxy-help
```

3. 查看日志：
```bash
docker logs -f gfw-proxy-help-container
```

4. 停止服务：
```bash
docker stop gfw-proxy-help-container
docker rm gfw-proxy-help-container
```

## 使用示例

```python
import base64
import requests

# 要代理的URL
target_url = "https://example.com/clash-config"

# Base64编码
encoded_url = base64.b64encode(target_url.encode()).decode()

# 请求代理服务
response = requests.get(f"http://localhost:6789/clash?url={encoded_url}")
print(response.text)
```

## 环境要求

- Python 3.10+
- Docker (可选)

## 注意事项

- 服务监听所有网络接口 (0.0.0.0:6789)
- 请求超时时间为30秒
- 使用gunicorn作为生产环境WSGI服务器 