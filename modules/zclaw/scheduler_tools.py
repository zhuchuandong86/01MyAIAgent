# modules/zclaw/scheduler_tools.py
import os
import platform
import subprocess
import streamlit as st
import core.paths

def get_user_workspace():
    user = st.session_state.get("zclaw_user", "public")
    return os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"zclaw_workspace_{user}")

def create_cron_task(time_str: str, command: str, task_id: str) -> str:
    """
    创建定时任务。
    time_str: Linux格式 "0 12 * * *" 或 Windows格式 "12:00"
    command: 要执行的完整 bash/python 命令
    """
    system = platform.system()
    workspace = get_user_workspace()
    
    try:
        if system == "Windows":
            # 使用 Windows schtasks
            # 格式: schtasks /create /tn "ZClaw_Task_ID" /tr "cmd /c cd /d path && command" /sc daily /st 12:00 /f
            cmd = f'schtasks /create /tn "ZClaw_{task_id}" /tr "cmd /c cd /d {workspace} && {command}" /sc daily /st {time_str} /f'
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            return f"✅ Windows 任务计划已创建：ID 为 ZClaw_{task_id}，时间 {time_str}。"
        
        else:
            # 使用 Linux crontab
            # 这里的 time_str 应该是 "0 12 * * *"
            cron_cmd = f'({subprocess.getoutput("crontab -l 2>/dev/null")}; echo "{time_str} cd {workspace} && {command}") | crontab -'
            subprocess.run(cron_cmd, shell=True, check=True)
            return f"✅ Linux Crontab 任务已添加：时间 {time_str}。"
            
    except Exception as e:
        return f"❌ 定时任务创建失败：{str(e)}"

SCHEMA = [
    {
        "name": "create_cron_task",
        "description": "在操作系统层面创建一个真实的定时任务（闹钟）。用于每日定时汇报、定时抓取数据等。Windows需提供HH:mm格式，Linux需提供标准cron格式。",
        "input_schema": {
            "type": "object",
            "properties": {
                "time_str": {"type": "string", "description": "触发时间。Windows如'12:00'，Linux如'0 12 * * *'"},
                "command": {"type": "string", "description": "要运行的命令，如 'python a_stock_report.py'"},
                "task_id": {"type": "string", "description": "任务的唯一简短英文标识符"}
            },
            "required": ["time_str", "command", "task_id"]
        }
    }
]