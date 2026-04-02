"""
modules/zclaw/__init__.py — 工具总装配线（OpenClaw 版）
────────────────────────────────────────────────────────────
架构升级说明：

1. 引入 _registry.py 作为全局注册中心，避免 skill_tools ↔ __init__ 循环导入
2. 新增工具：search_memory / list_skills / install_new_tool / evaluate_and_prune_memory
3. TOOL_DISPATCHER 和 ZCLAW_TOOLS_SCHEMA 从 _registry 导入后 in-place 填充，
   保证 skill_tools.py 热注册时所有模块共享同一对象引用
4. append_memory 已迁移至 memory_tools，system_tools 不再导出此函数
"""

# ── 工具函数导入 ──────────────────────────────────────────
from .system_tools  import execute_bash, read_file
from .web_tools     import search_web, read_webpage
from .coder_tools   import delegate_to_coder
from .vision_tools  import ask_vision
from .memory_tools  import append_memory, search_memory, evaluate_and_prune_memory
from .skill_tools   import list_skills, install_new_tool

# 👇 新增：优雅导入 Anthropic 专家工具组
from .anthropic_tools import ANTHROPIC_SCHEMA, ANTHROPIC_DISPATCHER

# ── 注册中心（其他模块必须从这里导入，保证对象唯一）──────
from ._registry import TOOL_DISPATCHER, ZCLAW_TOOLS_SCHEMA

# 👇 增加这一行，只要项目一启动，20个技能就会瞬间完成强制装载！
# ══════════════════════════════════════════════════════════
# 工具说明书（大模型看到的 JSON Schema）
# ══════════════════════════════════════════════════════════
_SCHEMA = [
    # ── 系统原子工具 ──
    {
        "type": "function",
        "function": {
            "name": "execute_bash",
            "description": (
                "系统终端权限。运行脚本、装包均用此工具。"
                "内置双层安全过滤，灾难级命令会被自动拦截。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "要执行的 Shell 命令"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "文本阅读。用于提取任务前的试探及代码执行后的结果审核！仅限沙盒内文件。",
            "parameters": {
                "type": "object",
                "properties": {"filepath": {"type": "string", "description": "相对于工作区的文件路径"}},
                "required": ["filepath"],
            },
        },
    },
    # ── 网络工具 ──
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "全网搜索引擎。遇到写代码报错、反爬，立刻调用查资料。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_webpage",
            "description": "通用网页阅读器。把复杂网页转成 Markdown 给你阅读。支持 Jina 降级到本地解析。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    # ── 记忆工具（Phase 1：结构化记忆引擎）──
    {
        "type": "function",
        "function": {
            "name": "append_memory",
            "description": (
                "将花费极大精力排查出的经验永久沉淀。"
                "带自动去重，相似度 > 70% 的经验会被跳过。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lesson":  {"type": "string", "description": "经验正文"},
                    "tags":    {"type": "string", "description": "逗号分隔的标签，如 '爬虫,反爬,requests'"},
                    "success": {"type": "boolean", "description": "是否为成功经验（失败教训传 false）"},
                },
                "required": ["lesson"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "按需检索记忆库中与当前任务最相关的历史经验。"
                "【用法】：任务开始前先调用，获取相关先验知识。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query":  {"type": "string", "description": "检索关键词，描述当前任务"},
                    "top_k":  {"type": "integer", "description": "返回条数，默认 8", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_and_prune_memory",
            "description": (
                "Phase 4 记忆剪枝：清除超期未引用的低质量记忆，防止记忆库无限膨胀。"
                "建议每隔一段时间或感知到记忆质量下降时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_threshold": {
                        "type": "integer",
                        "description": "超过多少天未被引用的记忆视为低价值（默认 90 天）",
                        "default": 90,
                    },
                    "min_use_count": {
                        "type": "integer",
                        "description": "使用次数低于此值的记忆才会被清除（默认 1）",
                        "default": 1,
                    },
                },
                "required": [],
            },
        },
    },
    # ── 代码外包 ──
    {
        "type": "function",
        "function": {
            "name": "delegate_to_coder",
            "description": (
                "算法外包。filepath 必须是 .py。"
                "尽量把可复用代码写在 skills/ 目录下，后续用 list_skills 查询后复用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath":         {"type": "string", "description": "目标 .py 文件路径（相对工作区）"},
                    "task_description": {"type": "string", "description": "对 Coder 的详细需求说明"},
                },
                "required": ["filepath", "task_description"],
            },
        },
    },
    # ── 视觉工具 ──
    {
        "type": "function",
        "function": {
            "name": "ask_vision",
            "description": "面对扫描件、图片等调用此接口。支持 jpg/png/gif/webp，不支持 PDF。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_filename": {"type": "string", "description": "工作区内的图片文件名"},
                    "question":       {"type": "string", "description": "对图片提出的问题"},
                },
                "required": ["image_filename", "question"],
            },
        },
    },
    # ── 技能库工具（Phase 2：主动感知）──
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": (
                "【任务开始前必须调用！】查询已有技能库，"
                "避免重复造轮子。返回 skills/ 目录下所有可复用脚本的清单。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── 自扩展工具（Phase 3：OpenClaw 核心）──
    {
        "type": "function",
        "function": {
            "name": "install_new_tool",
            "description": (
                "【OpenClaw 核心能力】发现自身能力缺口时，动态安装新工具并热注册到运行时。"
                "工具代码经过 AST 安全审计，下一轮推理即可直接调用新工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "工具函数名（合法 Python 标识符，与代码中函数名一致）",
                    },
                    "tool_code": {
                        "type": "string",
                        "description": "工具的完整 Python 源码（包含与 tool_name 同名的顶层函数）",
                    },
                    "tool_schema_json": {
                        "type": "string",
                        "description": (
                            'JSON Schema 字符串，格式: {"type":"function","function":{"name":"...","description":"...","parameters":{...}}}'
                        ),
                    },
                },
                "required": ["tool_name", "tool_code", "tool_schema_json"],
            },
        },
    },
]

# ══════════════════════════════════════════════════════════
# 物理路由器映射字典
# ══════════════════════════════════════════════════════════
_DISPATCHER = {
    "execute_bash":              execute_bash,
    "read_file":                 read_file,
    "search_web":                search_web,
    "read_webpage":              read_webpage,
    "append_memory":             append_memory,
    "search_memory":             search_memory,
    "evaluate_and_prune_memory": evaluate_and_prune_memory,
    "delegate_to_coder":         delegate_to_coder,
    "ask_vision":                ask_vision,
    "list_skills":               list_skills,
    "install_new_tool":          install_new_tool,
}

# 👇 新增：将 Anthropic 的近 20 个专家技能，完美合并进局部装配线
_SCHEMA.extend(ANTHROPIC_SCHEMA)
_DISPATCHER.update(ANTHROPIC_DISPATCHER)

# ── In-place 填充注册中心（保证 skill_tools 热注册时引用一致）──
ZCLAW_TOOLS_SCHEMA.extend(_SCHEMA)
TOOL_DISPATCHER.update(_DISPATCHER)
