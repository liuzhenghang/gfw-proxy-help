#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import requests
from flask import Flask, request, jsonify, Response
import logging
from urllib.parse import quote, urlencode
import os
import random
import fix_shortid
import yaml

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/clash', methods=['GET'])
def clash_proxy():
    """
    接收base64字符串，解密后请求目标URL，返回原始内容
    支持apply_sub参数，可以合并多个订阅的proxies
    """
    temp_files = []  # 用于跟踪需要清理的临时文件
    
    try:
        # 获取base64参数
        base64_str = request.args.get('url')
        ua = request.args.get('ua')
        apply_sub_list = request.args.getlist('apply_sub')  # 获取额外订阅列表
        
        if not base64_str:
            return jsonify({'error': '缺少url参数'}), 400
        if not ua:
            ua='clash-verge/v2.3.1'

        # 解码base64
        try:
            decoded_url = base64.b64decode(base64_str).decode('utf-8')
        except Exception as e:
            logger.error(f"Base64解码失败: {e}")
            return jsonify({'error': 'Base64解码失败'}), 400
        
        # 设置请求头
        headers = {
            'User-Agent': ua
        }
        print(headers)
        
        # 请求目标URL
        try:
            response = requests.get(decoded_url, headers=headers, timeout=30)
            logger.info(f"请求状态码: {response.status_code}")
            
            # 提取特定的响应头
            response_headers = {}
            headers_to_copy = ['Strict-Transport-Security', 'Subscription-Userinfo', 'Vary', 'X-Cache']
            for header_name in headers_to_copy:
                if header_name in response.headers:
                    response_headers[header_name] = response.headers[header_name]
            
            # 如果没有额外订阅，直接返回原始内容
            if not apply_sub_list:
                return Response(
                    response.content,
                    status=response.status_code,
                    headers=response_headers
                )
            
            # 处理额外订阅合并
            logger.info(f"检测到 {len(apply_sub_list)} 个额外订阅")
            
            # 解析主订阅内容
            try:
                main_yaml = yaml.safe_load(response.content)
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
            
            # 遍历额外订阅
            for idx, sub_b64 in enumerate(apply_sub_list):
                try:
                    # 解码额外订阅URL
                    sub_url = base64.b64decode(sub_b64).decode('utf-8')
                    logger.info(f"下载额外订阅 [{idx+1}/{len(apply_sub_list)}]: {sub_url}")
                    
                    # 下载额外订阅
                    sub_response = requests.get(sub_url, headers=headers, timeout=30)
                    
                    if sub_response.status_code != 200:
                        logger.warning(f"额外订阅 {idx+1} 下载失败，状态码: {sub_response.status_code}")
                        continue
                    
                    # 解析额外订阅YAML
                    sub_yaml = yaml.safe_load(sub_response.content)
                    
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
            
            # 返回合并后的内容
            return Response(
                merged_content.encode('utf-8'),
                status=response.status_code,
                headers=response_headers
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
            return jsonify({'error': f'请求失败: {str(e)}'}), 500
            
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
                convert_url = "https://url.v1.mk/sub"
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
            '/clash': 'GET - 代理Clash配置请求 (参数: url=base64编码的URL, ua=可选的User-Agent)',
            '/clash_convert': 'GET - Clash配置转换 (参数: url=base64编码的订阅URL, config=base64编码的配置, convert_url=base64编码的转换服务URL)',
            '/health': 'GET - 健康检查'
        }
    })

if __name__ == '__main__':
    logger.info("启动Flask服务器...")
    app.run(host='0.0.0.0', port=6789, debug=False) 