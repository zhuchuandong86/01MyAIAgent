# modules/zclaw/system_tools.py
import os
import subprocess
import streamlit as st
import core.paths
import time

def get_user_workspace():
    user = st.session_state.get("zclaw_user", "public")
    return os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"zclaw_workspace_{user}")

def download_file(url: str, filename: str) -> str:
    """从 URL 下载二进制文件，加入自动重试与长超时。"""
    workspace = get_user_workspace()
    target_path = os.path.join(workspace, filename)
    
    import urllib.parse
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    proxy_host = os.getenv("PROXY_HOST")
    proxy_user = os.getenv("PROXY_USER")
    proxy_pass = os.getenv("PROXY_PASS")
    proxies = None
    if proxy_host:
        if proxy_user and proxy_pass:
            safe_user = urllib.parse.quote(proxy_user, safe="")
            safe_pass = urllib.parse.quote(proxy_pass, safe="")
            proxy_url = f"http://{safe_user}:{safe_pass}@{proxy_host.replace('http://', '')}"
        else:
            proxy_url = f"http://{proxy_host.replace('http://', '')}"
        proxies = {"http": proxy_url, "https": proxy_url}

    # 🌟 增强：加入 3 次重试机制，应对 504 偶发超时
    for attempt in range(3):
        try:
            # 增加 timeout 到 60 秒
            response = requests.get(url, proxies=proxies, verify=False, timeout=60, stream=True)
            response.raise_for_status()
            with open(target_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return f"✅ 文件已成功下载: {filename} (耗时: {response.elapsed.total_seconds():.1f}s)"
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
                continue
            return f"❌ 下载彻底失败 (3次尝试): {str(e)}。建议：该链接可能已被公司防火墙策略物理切断，请尝试搜索其他镜像下载链接。"

def execute_bash(command: str) -> str:
    workspace = get_user_workspace()
    try:
        # 🌟 增强：执行前先检查当前路径，并在返回中附带路径信息
        result = subprocess.run(command, shell=True, cwd=workspace, capture_output=True, text=True, timeout=60)
        output = result.stdout if result.returncode == 0 else result.stderr
        if not output and result.returncode == 0:
            return f"✅ 命令执行成功 (CWD: {workspace})"
        return output.strip()
    except Exception as e:
        return f"❌ 执行异常: {str(e)}"

def read_file(filepath: str) -> str:
    workspace = get_user_workspace()
    target = os.path.join(workspace, filepath)
    if not os.path.exists(target):
        return f"❌ 文件不存在: {filepath}。可用文件: {os.listdir(workspace)}"
    try:
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
            return (content[:5000] + "\n...[数据过长，已截断]") if len(content) > 5000 else content
    except Exception as e:
        return f"❌ 读取失败: {str(e)}"

SCHEMA = [
    {"name": "download_file", "description": "下载二进制文件。支持自动重试，应对 504 超时。", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}, "filename": {"type": "string"}}, "required": ["url", "filename"]}},
    {"name": "execute_bash", "description": "执行终端命令。会在用户专属沙箱目录中运行。", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "读取文本。若文件不存在会返回当前目录清单。", "input_schema": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}}
]