#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import logging
import json
import os
import base64

logger = logging.getLogger(__name__)

# 获取当前脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, 'cache')
STORAGE_FILE = os.path.join(CACHE_DIR, 'url_storage.json')

# 确保cache目录存在
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)
    logger.info(f"创建缓存目录: {CACHE_DIR}")


def get_storage():
    """从JSON文件读取存储数据"""
    try:
        if os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {}
    except Exception as e:
        logger.error(f"读取存储文件失败: {e}")
        return {}


def get_storage_item(key):
    """从JSON文件获取指定key的值"""
    storage = get_storage()
    return storage.get(key)


def download_subscription(url, ua='clash-verge/v2.4.3'):
    """
    下载订阅配置
    
    参数:
        url: 订阅URL、key://格式的key或base64编码的URL
        ua: User-Agent
    
    返回:
        tuple: (yaml_content, subscription_userinfo, status_code)
        如果失败返回 (None, None, status_code)
    """
    # 1. 检查是否是key://格式
    if url.startswith('key://'):
        key_name = url[6:]  # 去掉'key://'
        cache_data = get_storage_item(key_name)
        
        if not cache_data:
            logger.error(f"Key不存在: {key_name}")
            return None, None, 404
        
        # 缓存一律是新格式
        if not isinstance(cache_data, dict) or 'yaml_content' not in cache_data:
            logger.error(f"缓存数据格式错误: {key_name}")
            return None, None, 500
        
        # 直接从缓存读取
        yaml_content = cache_data.get('yaml_content')
        subscription_userinfo = cache_data.get('subscription_userinfo', '')
        cached_time = cache_data.get('cached_time', 'unknown')
        logger.info(f"使用缓存的YAML: {key_name}, 缓存时间: {cached_time}")
        return yaml_content, subscription_userinfo, 200
    
    # 2. 检查是否是http开头
    if url.startswith('http://') or url.startswith('https://'):
        actual_url = url
    else:
        # 3. 不是http开头，当做base64解码
        try:
            actual_url = base64.b64decode(url).decode('utf-8')
            logger.info(f"Base64解码URL: {actual_url}")
        except Exception as e:
            logger.error(f"Base64解码失败: {e}")
            return None, None, 400
    
    # 下载订阅
    headers = {'User-Agent': ua}
    
    try:
        logger.info(f"下载订阅: {actual_url}")
        response = requests.get(actual_url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"订阅下载失败，状态码: {response.status_code}")
            return None, None, response.status_code
        
        yaml_content = response.text
        subscription_userinfo = response.headers.get('Subscription-Userinfo', '')
        
        logger.info(f"订阅下载成功，大小: {len(yaml_content)} 字节")
        return yaml_content, subscription_userinfo, 200
        
    except requests.exceptions.RequestException as e:
        logger.error(f"下载订阅时出错: {e}")
        return None, None, 500
    except Exception as e:
        logger.error(f"处理订阅时出错: {e}")
        return None, None, 500

