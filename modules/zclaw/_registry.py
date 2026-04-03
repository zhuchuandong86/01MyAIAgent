from modules.zclaw.coder_tools import delegate_to_coder, install_new_tool, SCHEMA as coder_schema
from modules.zclaw.memory_tools import search_memory, append_memory, evaluate_and_prune_memory, SCHEMA as memory_schema
from modules.zclaw.skill_tools import list_skills, SCHEMA as skill_schema
from modules.zclaw.web_tools import search_web, read_webpage, SCHEMA as web_schema
from modules.zclaw.system_tools import execute_bash, read_file, download_file, SCHEMA as system_schema # 🌟 增加 download_file
from modules.zclaw.vision_tools import ask_vision, SCHEMA as vision_schema
from modules.zclaw.scheduler_tools import create_cron_task, SCHEMA as scheduler_schema

# 汇总所有原子 Schema
RAW_SCHEMAS = (
    coder_schema + memory_schema + skill_schema + 
    web_schema + system_schema + vision_schema + 
    scheduler_schema # 🌟 挂载闹钟工具
)

ZCLAW_TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": s["name"], "description": s["description"], "parameters": s["input_schema"]}}
    for s in RAW_SCHEMAS
]

TOOL_DISPATCHER = {
    "delegate_to_coder": delegate_to_coder,
    "install_new_tool": install_new_tool,
    "search_memory": search_memory,
    "append_memory": append_memory,
    "evaluate_and_prune_memory": evaluate_and_prune_memory,
    "list_skills": list_skills,
    "search_web": search_web,
    "read_webpage": read_webpage,
    "execute_bash": execute_bash,
    "read_file": read_file,
    "download_file": download_file, # 🌟 挂载
    "ask_vision": ask_vision,
    "create_cron_task": create_cron_task
}