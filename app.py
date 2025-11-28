#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import requests
from flask import Flask, request, jsonify, Response, render_template
import logging
from urllib.parse import quote, urlencode
import os
import random
import fix_shortid
import yaml
import json
from datetime import datetime
import subscription_manager

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 获取当前脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
CACHE_DIR = os.path.join(BASE_DIR, 'cache')
STORAGE_FILE = os.path.join(CACHE_DIR, 'url_storage.json')

# 确保cache目录存在
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)
    logger.info(f"创建缓存目录: {CACHE_DIR}")

app = Flask(__name__, template_folder=TEMPLATE_DIR)

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

def set_storage_item(key, value):
    """保存键值对到JSON文件"""
    storage = get_storage()
    storage[key] = value
    try:
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(storage, f, ensure_ascii=False, indent=2)
        logger.info(f"保存键值对到文件: {key} -> {value}")
    except Exception as e:
        logger.error(f"保存存储文件失败: {e}")
        raise

@app.route('/clash', methods=['GET'])
def clash_proxy():
    """
    订阅代理接口
    支持: key://缓存key、http(s)://直接URL、base64编码的URL
    支持apply_sub参数，可以合并多个订阅的proxies
    """
    temp_files = []  # 用于跟踪需要清理的临时文件
    
    try:
        # 获取url参数（支持key://、http(s)://或base64）
        url_param = request.args.get('url')
        ua = request.args.get('ua')
        apply_sub_list = request.args.getlist('apply_sub')  # 获取额外订阅列表
        
        if not url_param:
            return jsonify({'error': '缺少url参数'}), 400
        if not ua:
            ua='clash-verge/v2.4.3'

        # 使用subscription_manager下载主订阅
        # 自动处理key://缓存、http(s)://直接URL、base64编码URL
        yaml_content, subscription_userinfo, status_code = subscription_manager.download_subscription(url_param, ua)
        
        if yaml_content is None:
            error_msg = f'主订阅下载失败，状态码: {status_code}'
            logger.error(error_msg)
            return jsonify({'error': error_msg}), status_code
        
        # 准备响应头
        response_headers = {}
        if subscription_userinfo:
            response_headers['Subscription-Userinfo'] = subscription_userinfo
        response_headers['Content-Type'] = 'text/yaml; charset=utf-8'
        
        # 如果没有额外订阅，直接返回内容
        if not apply_sub_list:
            return Response(
                yaml_content.encode('utf-8'),
                status=status_code,
                headers=response_headers
            )
        
        # 有额外订阅，需要合并
        logger.info(f"检测到 {len(apply_sub_list)} 个额外订阅")
        
        try:
            main_yaml = yaml.safe_load(yaml_content)
            if not isinstance(main_yaml, dict):
                logger.error("主订阅内容不是有效的YAML字典")
                return jsonify({'error': '主订阅内容格式错误'}), 500
            
            # 确保主订阅有proxies字段
            if 'proxies' not in main_yaml:
                main_yaml['proxies'] = []
            
            main_proxies = main_yaml['proxies']
            logger.info(f"主订阅包含 {len(main_proxies)} 个代理")
            
        except Exception as e:
            logger.error(f"解析主订阅YAML失败: {e}")
            return jsonify({'error': f'主订阅YAML解析失败: {str(e)}'}), 500
        
        # 处理额外订阅合并
        for idx, sub_b64 in enumerate(apply_sub_list):
            try:
                # 使用subscription_manager下载额外订阅
                sub_yaml_content, _, sub_status = subscription_manager.download_subscription(sub_b64, ua)
                
                if sub_yaml_content is None:
                    logger.warning(f"额外订阅 {idx+1} 下载失败，状态码: {sub_status}")
                    continue
                
                # 解析额外订阅YAML
                sub_yaml = yaml.safe_load(sub_yaml_content)
                
                if not isinstance(sub_yaml, dict):
                    logger.warning(f"额外订阅 {idx+1} 不是有效的YAML字典")
                    continue
                
                # 提取proxies并合并
                if 'proxies' in sub_yaml and isinstance(sub_yaml['proxies'], list):
                    sub_proxies = sub_yaml['proxies']
                    logger.info(f"额外订阅 {idx+1} 包含 {len(sub_proxies)} 个代理")
                    main_proxies.extend(sub_proxies)
                else:
                    logger.warning(f"额外订阅 {idx+1} 没有有效的proxies字段")
                    
            except Exception as e:
                logger.error(f"处理额外订阅 {idx+1} 时出错: {e}")
                continue
        
        # 更新主订阅的proxies
        main_yaml['proxies'] = main_proxies
        logger.info(f"合并完成，总共 {len(main_proxies)} 个代理")
        
        # 生成临时文件
        random_num = random.randint(100000, 999999)
        temp_filename = f"temp_merged_{random_num}.yaml"
        temp_files.append(temp_filename)
        
        # 写入临时文件
        try:
            with open(temp_filename, 'w', encoding='utf-8') as f:
                yaml.dump(main_yaml, f, allow_unicode=True, sort_keys=False)
            logger.info(f"合并内容已保存到临时文件: {temp_filename}")
            
            # 读取文件内容
            with open(temp_filename, 'r', encoding='utf-8') as f:
                merged_content = f.read()
            
        except Exception as e:
            logger.error(f"临时文件操作失败: {e}")
            return jsonify({'error': f'文件操作失败: {str(e)}'}), 500
        
        # 确保Content-Type正确设置
        if 'Content-Type' not in response_headers:
            response_headers['Content-Type'] = 'text/yaml; charset=utf-8'
        
        logger.info(f"返回headers: {response_headers}")
        
        # 返回合并后的内容
        return Response(
            merged_content.encode('utf-8'),
            status=status_code,
            headers=response_headers
        )
            
    except Exception as e:
        logger.error(f"处理请求时出错: {e}")
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500
    
    finally:
        # 清理临时文件
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logger.info(f"临时文件已删除: {temp_file}")
            except Exception as e:
                logger.error(f"删除临时文件失败 {temp_file}: {e}")

@app.route('/clash_convert', methods=['GET'])
def clash_convert():
    """
    Clash配置转换接口
    接收url、config、convert_url三个base64参数，向convert_url发送转换请求
    """
    try:
        # 获取base64参数
        url_b64 = request.args.get('url')
        config_b64 = request.args.get('config')
        convert_url_b64 = request.args.get('convert_url')
        
        # 检查必需参数
        if not url_b64:
            return jsonify({'error': '缺少url参数'}), 400
        if config_b64:
            config = base64.b64decode(config_b64).decode('utf-8')
        else:
            config = 'https://testingcf.jsdelivr.net/gh/Aethersailor/Custom_OpenClash_Rules@main/cfg/Custom_Clash.ini'
        # 解码base64
        try:
            url = base64.b64decode(url_b64).decode('utf-8')

            if not convert_url_b64:
                convert_url = "https://api.asailor.org/sub"
            else:
                convert_url = base64.b64decode(convert_url_b64).decode('utf-8')
            logger.info(f"转换URL: {convert_url}")
        except Exception as e:
            logger.error(f"Base64解码失败: {e}")
            return jsonify({'error': 'Base64解码失败'}), 400
        
        # 构建请求参数
        params = {
            'target': 'clash',
            'new_name': 'true',
            'url': url,
            'config': config,
            'include': '',
            'exclude': '',
            'emoji': 'true',
            'list': 'false',
            'sort': 'false',
            'udp': 'true',
            'scv': 'true',
            'append_type': 'false',
            'fdn': 'true',
            'expand': 'false',
            'classic': 'true'
        }
        # 组装convert_url
        convert_url = convert_url + '?' + urlencode(params)
        # 发送GET请求到转换服务
        try:
            response = requests.get(convert_url, timeout=60)
            logger.info(f"转换请求状态码: {response.status_code}")
            
            # 提取特定的响应头
            response_headers = {}
            headers_to_copy = ['Strict-Transport-Security', 'Subscription-Userinfo', 'Vary', 'X-Cache']
            for header_name in headers_to_copy:
                if header_name in response.headers:
                    response_headers[header_name] = response.headers[header_name]
            
            # 获取响应内容
            content = response.content
            
            # 生成随机数作为文件名
            random_num = random.randint(100000, 999999)
            temp_filename = f"temp_clash_{random_num}.yaml"
            fix_temp_filename = 'fix_'+temp_filename

            # 确保内容以UTF-8编码保存到临时文件
            try:
                # 如果content是bytes，尝试解码为字符串
                if isinstance(content, bytes):
                    try:
                        content_str = content.decode('utf-8')
                    except UnicodeDecodeError:
                        # 如果不是UTF-8，尝试其他编码
                        try:
                            content_str = content.decode('gbk')
                        except UnicodeDecodeError:
                            # 如果都失败，使用错误替换模式
                            content_str = content.decode('utf-8', errors='replace')
                else:
                    content_str = content
                
                # 保存到临时文件
                with open(temp_filename, 'w', encoding='utf-8') as f:
                    f.write(content_str)
                logger.info(f"内容已保存到临时文件: {temp_filename}")
                fix_shortid.fix_short_id(temp_filename,fix_temp_filename)
                logger.info(f"short-id修复: {temp_filename}")
                # 读取文件内容
                with open(fix_temp_filename, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                
                # 删除临时文件
                os.remove(temp_filename)
                os.remove(fix_temp_filename)
                logger.info(f"临时文件已删除: {temp_filename}、{fix_temp_filename}")
                
            except Exception as e:
                logger.error(f"文件操作失败: {e}")
                return jsonify({'error': f'文件操作失败: {str(e)}'}), 500
            
            # 设置文件下载响应头
            response_headers['Content-Type'] = 'application/octet-stream; charset=utf-8'
            response_headers['Content-Disposition'] = 'attachment; filename="clash_sub.yaml"'
            
            # 返回文件内容
            return Response(
                file_content.encode('utf-8'),
                status=response.status_code,
                headers=response_headers
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"转换请求失败: {e}")
            return jsonify({'error': f'转换请求失败: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"处理转换请求时出错: {e}")
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

@app.route('/input', methods=['GET', 'POST'])
def input_page():
    """键值对输入页面"""
    if request.method == 'POST':
        key = request.form.get('key')
        url = request.form.get('url')
        response_json = request.form.get('response_json', '').lower() == 'true'
        try_update = request.form.get('try_update', '').lower() == 'true'

        if not key or not url:
            if response_json:
                return jsonify({'error': '缺少参数'}), 400
            return '缺少参数', 400

        # 使用subscription_manager下载yaml配置和订阅信息
        try:
            ua = 'clash-verge/v2.4.3'
            
            logger.info(f"下载URL配置: {url}")
            yaml_content, subscription_userinfo, status_code = subscription_manager.download_subscription(url, ua)
            
            if yaml_content is None:
                error_msg = f'下载失败，状态码: {status_code}'
                logger.error(error_msg)
                if response_json:
                    return jsonify({'error': error_msg}), status_code
                return error_msg, status_code
            
            # 保存到缓存，包含时间戳
            cache_data = {
                'url': url,
                'yaml_content': yaml_content,
                'subscription_userinfo': subscription_userinfo,
                'cached_time': datetime.now().isoformat(),
                'try_update': try_update
            }
            
            set_storage_item(key, cache_data)
            logger.info(f"缓存成功: {key}, 时间: {cache_data['cached_time']}")
            
            if response_json:
                return jsonify({'status': 'ok', 'key': key, 'cached_time': cache_data['cached_time']})
            
            return render_template('success.html', key=key, url=url)
            
        except Exception as e:
            error_msg = f'处理失败: {str(e)}'
            logger.error(error_msg)
            if response_json:
                return jsonify({'error': error_msg}), 500
            return error_msg, 500

    # GET请求，显示表单
    key = request.args.get('key', '')
    return render_template('input.html', key=key)

@app.route('/generator', methods=['GET'])
def clash_generator():
    """Clash参数生成器页面"""
    return render_template('clash_generator.html')

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
            '/clash': 'GET - 代理Clash配置请求 (参数: url=key://缓存key|http(s)://直接URL|base64编码的URL, apply_sub=额外订阅URL(同url格式), ua=可选的User-Agent)',
            '/clash_convert': 'GET - Clash配置转换 (参数: url=base64编码的订阅URL, config=base64编码的配置, convert_url=base64编码的转换服务URL)',
            '/input': 'GET/POST - 键值对URL存储页面 (POST参数: key=缓存key, url=订阅URL, response_json=true返回json)',
            '/generator': 'GET - Clash参数生成器页面',
            '/health': 'GET - 健康检查'
        }
    })

if __name__ == '__main__':
    logger.info("启动Flask服务器...")
    for rule in app.url_map.iter_rules():
        logger.info("注册路由: %s -> %s", rule.rule, rule.endpoint)
    app.run(host='0.0.0.0', port=6789, debug=False)