from .system_tools import execute_bash, read_file, append_memory
from .web_tools import search_web, read_webpage
from .coder_tools import delegate_to_coder
from .vision_tools import ask_vision  # 🌟 1. 导入视觉中枢

# 1. 向大模型展示的 JSON 说明书
ZCLAW_TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": "execute_bash", "description": "系统终端权限。运行脚本、装包均用此工具。", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "文本阅读。用于提取任务前的试探及代码执行后的结果审核！", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}}},
    {"type": "function", "function": {"name": "search_web", "description": "全网搜索引擎。遇到写代码报错、反爬，立刻调用查资料。", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "read_webpage", "description": "通用网页阅读器。把复杂网页转成 Markdown 给你阅读。", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "append_memory", "description": "将花费极大精力排查出的经验沉淀下来。", "parameters": {"type": "object", "properties": {"lesson": {"type": "string"}}, "required": ["lesson"]}}},
    {"type": "function", "function": {"name": "delegate_to_coder", "description": "算法外包。filepath 必须是 .py。你要教 Coder 尽量把可复用的爬虫或处理代码写在 skills/ 目录下，后续复用。", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "task_description": {"type": "string"}}, "required": ["filepath", "task_description"]}}},
    # 🌟 2. 补回视觉工具的描述
    {"type": "function", "function": {"name": "ask_vision", "description": "面对扫描件、图片等调用此接口。", "parameters": {"type": "object", "properties": {"image_filename": {"type": "string"}, "question": {"type": "string"}}, "required": ["image_filename", "question"]}}}
]

# 2. 物理路由器映射字典
TOOL_DISPATCHER = {
    "execute_bash": execute_bash,
    "read_file": read_file,
    "search_web": search_web,
    "read_webpage": read_webpage,
    "append_memory": append_memory,
    "delegate_to_coder": delegate_to_coder,
    "ask_vision": ask_vision  # 🌟 3. 接入路由分发器
}