#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import requests
from flask import Flask, request, jsonify, Response, render_template
import logging
from urllib.parse import quote, urlencode
import os
import random
import re
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
        cover_url_b64 = request.args.get('cover_url')
        mix_subs_list = request.args.getlist('mix_subs')  # 混合订阅列表（支持 key://、http(s)://、base64）
        
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

            cover_url = None
            if cover_url_b64:
                cover_url = base64.b64decode(cover_url_b64).decode('utf-8')
                logger.info(f"覆盖配置URL: {cover_url}")

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

                # 处理混合订阅：在覆盖逻辑之前，把 mix_subs 下载到的 proxies 合并进 main_yaml
                if mix_subs_list:
                    try:
                        main_yaml_for_mix = yaml.safe_load(content_str)
                        if not isinstance(main_yaml_for_mix, dict):
                            logger.error("转换后的主配置不是有效的YAML字典，无法执行 mix_subs 合并")
                            return jsonify({'error': '主配置内容格式错误，无法执行mix_subs合并'}), 500

                        main_proxies_for_mix = main_yaml_for_mix.get('proxies')
                        if not isinstance(main_proxies_for_mix, list):
                            # main_yaml 可能没有 proxies 字段，或者类型不对，统一兜底
                            main_proxies_for_mix = []
                            main_yaml_for_mix['proxies'] = main_proxies_for_mix

                        mixed_total = 0
                        for idx, mix_url in enumerate(mix_subs_list):
                            try:
                                mix_content, _, mix_status = subscription_manager.download_subscription(
                                    mix_url, 'clash-verge/v2.4.3'
                                )
                                if mix_content is None:
                                    logger.warning(f"mix_subs {idx+1} 下载失败，状态码: {mix_status}")
                                    continue

                                mix_yaml = yaml.safe_load(mix_content)
                                if not isinstance(mix_yaml, dict):
                                    logger.warning(f"mix_subs {idx+1} 不是有效的YAML字典")
                                    continue

                                mix_proxies = mix_yaml.get('proxies', [])
                                if isinstance(mix_proxies, list) and mix_proxies:
                                    main_proxies_for_mix.extend(mix_proxies)
                                    mixed_total += len(mix_proxies)
                                else:
                                    logger.warning(f"mix_subs {idx+1} 没有有效的proxies字段")
                            except Exception as e:
                                logger.error(f"处理 mix_subs {idx+1} 时出错: {e}")
                                continue

                        if mixed_total > 0:
                            main_yaml_for_mix['proxies'] = main_proxies_for_mix
                            content_str = yaml.dump(main_yaml_for_mix, allow_unicode=True, sort_keys=False)
                            logger.info(f"mix_subs 合并完成，新增 proxies: {mixed_total}，总 proxies: {len(main_proxies_for_mix)}")
                        else:
                            logger.info("mix_subs 未合并到任何 proxies（可能都下载失败或无proxies）")
                    except Exception as e:
                        logger.error(f"mix_subs 合并处理失败: {e}")
                        return jsonify({'error': f'mix_subs 合并处理失败: {str(e)}'}), 500

                # 处理覆盖逻辑
                if cover_url:
                    try:
                        logger.info("开始处理覆盖逻辑...")
                        # 使用 subscription_manager 下载
                        cover_content, _, _ = subscription_manager.download_subscription(cover_url, 'clash-verge/v2.4.3')
                        
                        if cover_content:
                            main_yaml = yaml.safe_load(content_str)
                            cover_yaml = yaml.safe_load(cover_content)
                            
                            if isinstance(main_yaml, dict) and isinstance(cover_yaml, dict):
                                main_groups = main_yaml.get('proxy-groups', [])
                                cover_groups = cover_yaml.get('proxy-groups', [])
                                
                                if isinstance(main_groups, list) and isinstance(cover_groups, list):
                                    # 创建映射以加快查找
                                    main_group_map = {g.get('name'): i for i, g in enumerate(main_groups) if isinstance(g, dict) and 'name' in g}
                                    
                                    covered_count = 0
                                    added_count = 0
                                    for c_group in cover_groups:
                                        if not isinstance(c_group, dict): continue

                                        # 扩展 proxy-groups.use：按 main_yaml 的 proxy-providers 做全匹配/正则匹配，然后改写 use 列表
                                        # 规则：use 是 list；每个元素先尝试完全匹配 provider 名，不中则当正则去匹配多个 provider
                                        # 顺序：按 use 原顺序处理；正则匹配结果按 main_yaml.proxy-providers 的 key 顺序输出；去重保序
                                        try:
                                            if 'use' in c_group and isinstance(c_group.get('use'), list):
                                                providers = main_yaml.get('proxy-providers', {})
                                                if isinstance(providers, dict) and providers:
                                                    provider_names = list(providers.keys())
                                                    new_use = []
                                                    seen = set()
                                                    for use_item in c_group.get('use', []):
                                                        if not isinstance(use_item, str) or not use_item:
                                                            continue

                                                        # 1) 完全匹配优先
                                                        if use_item in providers:
                                                            if use_item not in seen:
                                                                new_use.append(use_item)
                                                                seen.add(use_item)
                                                            continue

                                                        # 2) 正则匹配（合法正则才生效）
                                                        try:
                                                            reg = re.compile(use_item)
                                                        except re.error:
                                                            logger.warning(f"proxy-group use 项不是合法正则且无完全匹配: {use_item}")
                                                            continue

                                                        matched_any = False
                                                        for pname in provider_names:
                                                            try:
                                                                if reg.search(pname):
                                                                    matched_any = True
                                                                    if pname not in seen:
                                                                        new_use.append(pname)
                                                                        seen.add(pname)
                                                            except Exception:
                                                                continue

                                                        if not matched_any:
                                                            logger.warning(f"proxy-group use 正则未匹配到任何 proxy-providers: {use_item}")

                                                    if new_use:
                                                        c_group['use'] = new_use
                                                else:
                                                    logger.warning("main_yaml 没有有效的 proxy-providers，跳过 proxy-group use 改写")
                                        except Exception as e:
                                            logger.error(f"处理 proxy-group use 改写时出错: {e}")

                                        c_name = c_group.get('name')
                                        if c_name:
                                            if c_name in main_group_map:
                                                idx = main_group_map[c_name]
                                                main_groups[idx] = c_group
                                                covered_count += 1
                                            else:
                                                main_groups.append(c_group)
                                                added_count += 1
                                    
                                    if covered_count > 0 or added_count > 0:
                                        main_yaml['proxy-groups'] = main_groups
                                        logger.info(f"成功覆盖了 {covered_count} 个, 新增了 {added_count} 个 proxy-groups")
                                    else:
                                        logger.info("没有匹配的 proxy-groups 需要处理")
                                else:
                                    logger.warning("main_yaml 或 cover_yaml 的 proxy-groups 不是列表")
                                
                                # 处理 dialers 字段，给 proxies 添加 dialer-proxy
                                dialers = cover_yaml.get('dialers', [])
                                if isinstance(dialers, list) and len(dialers) > 0:
                                    # name 支持：完全匹配 或 正则表达式匹配
                                    exact_dialer_map = {}
                                    regex_dialers = []
                                    for d in dialers:
                                        if not (isinstance(d, dict) and 'name' in d and 'dialer-proxy' in d):
                                            continue
                                        name_pat = d.get('name')
                                        dialer_proxy = d.get('dialer-proxy')
                                        if not isinstance(name_pat, str) or not name_pat:
                                            continue
                                        # exact 优先，regex 放列表按顺序匹配
                                        exact_dialer_map[name_pat] = dialer_proxy
                                        try:
                                            regex_dialers.append((name_pat, re.compile(name_pat), dialer_proxy))
                                        except re.error:
                                            # 不是合法正则也没关系，照样保留 exact
                                            pass

                                    if exact_dialer_map or regex_dialers:
                                        logger.info(f"发现 dialer 配置: exact={len(exact_dialer_map)}, regex={len(regex_dialers)}")

                                        main_proxies = main_yaml.get('proxies', [])
                                        if not isinstance(main_proxies, list):
                                            main_proxies = []
                                            main_yaml['proxies'] = main_proxies

                                        dialer_count = 0
                                        for proxy in main_proxies:
                                            if not (isinstance(proxy, dict) and 'name' in proxy):
                                                continue
                                            proxy_name = proxy.get('name')
                                            if not isinstance(proxy_name, str):
                                                continue

                                            # 1) 完全匹配优先
                                            if proxy_name in exact_dialer_map:
                                                proxy['dialer-proxy'] = exact_dialer_map[proxy_name]
                                                dialer_count += 1
                                                continue

                                            # 2) 正则匹配（按 cover_yaml 的 dialers 顺序）
                                            for _, reg, dialer_proxy in regex_dialers:
                                                try:
                                                    if reg.search(proxy_name):
                                                        proxy['dialer-proxy'] = dialer_proxy
                                                        dialer_count += 1
                                                        break
                                                except Exception:
                                                    continue

                                        if dialer_count > 0:
                                            main_yaml['proxies'] = main_proxies
                                            logger.info(f"成功为 {dialer_count} 个代理添加了 dialer-proxy")
                                
                                # 重新生成 content_str
                                content_str = yaml.dump(main_yaml, allow_unicode=True, sort_keys=False)
                            else:
                                logger.warning("解析后的 YAML 不是字典")
                        else:
                            logger.warning("cover_url 下载内容为空")
                            
                    except Exception as e:
                        logger.error(f"处理 cover_url 覆盖逻辑时出错: {e}")
                
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
        uploaded_file = request.files.get('yaml_file')
        response_json = request.form.get('response_json', '').lower() == 'true'
        try_update = request.form.get('try_update', '').lower() == 'true'

        if not key:
             if response_json:
                return jsonify({'error': '缺少Key参数'}), 400
             return '缺少Key参数', 400
        
        if not url and not uploaded_file:
            if response_json:
                return jsonify({'error': '缺少URL或文件'}), 400
            return '请提供URL或上传YAML文件', 400

        try:
            yaml_content = None
            subscription_userinfo = ''
            
            # 优先处理文件上传
            if uploaded_file and uploaded_file.filename:
                try:
                    content = uploaded_file.read()
                    # 尝试解码
                    try:
                        yaml_content = content.decode('utf-8')
                    except UnicodeDecodeError:
                        yaml_content = content.decode('gbk') # 尝试GBK
                    
                    # 验证YAML格式
                    yaml.safe_load(yaml_content)
                    logger.info(f"文件上传成功: {uploaded_file.filename}")
                    
                    # 如果是文件上传，url可以为空，或者是文件名
                    if not url:
                        url = f"file://{uploaded_file.filename}"
                        
                except Exception as e:
                    error_msg = f'文件解析失败: {str(e)}'
                    logger.error(error_msg)
                    if response_json:
                        return jsonify({'error': error_msg}), 400
                    return error_msg, 400
            
            # 如果没有文件，则处理URL
            elif url:
                # 使用subscription_manager下载yaml配置和订阅信息
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
            '/clash_convert': 'GET - Clash配置转换 (参数: url=base64编码的订阅URL, config=base64编码的配置, convert_url=base64编码的转换服务URL, cover_url=base64编码的覆盖配置URL)',
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