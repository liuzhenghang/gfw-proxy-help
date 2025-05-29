#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import requests
from flask import Flask, request, jsonify, Response
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/clash', methods=['GET'])
def clash_proxy():
    """
    接收base64字符串，解密后请求目标URL，返回原始内容
    """
    try:
        # 获取base64参数
        base64_str = request.args.get('url')
        if not base64_str:
            return jsonify({'error': '缺少url参数'}), 400
        
        # 解码base64
        try:
            decoded_url = base64.b64decode(base64_str).decode('utf-8')
        except Exception as e:
            logger.error(f"Base64解码失败: {e}")
            return jsonify({'error': 'Base64解码失败'}), 400
        
        # 设置请求头
        headers = {
            'User-Agent': 'clash-verge/v2.1.2'
        }
        
        # 请求目标URL
        try:
            response = requests.get(decoded_url, headers=headers, timeout=30)
            logger.info(f"请求状态码: {response.status_code}")
            # print(response.content)
            # 返回原始内容，保持原始响应头
            return response.content
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
            return jsonify({'error': f'请求失败: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"处理请求时出错: {e}")
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({'status': 'ok', 'message': '服务运行正常'})

@app.route('/', methods=['GET'])
def index():
    """首页"""
    return jsonify({
        'service': 'GFW Proxy Helper',
        'version': '1.0.0',
        'endpoints': {
            '/clash': 'GET - 代理Clash配置请求 (参数: url=base64编码的URL)',
            '/health': 'GET - 健康检查'
        }
    })

if __name__ == '__main__':
    logger.info("启动Flask服务器...")
    app.run(host='0.0.0.0', port=6789, debug=False) 