import os
import ast
import json
import importlib.util
import streamlit as st
import core.paths
from core.settings import settings
from core.llm_factory import get_llm
from langchain_core.messages import SystemMessage, HumanMessage

def get_user_workspace():
    user = st.session_state.get("zclaw_user", "public")
    return os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"zclaw_workspace_{user}")

def get_user_skills_dir():
    ws = get_user_workspace()
    skills = os.path.join(ws, "skills")
    os.makedirs(skills, exist_ok=True)
    return skills

def delegate_to_coder(requirement: str, filepath: str) -> str:
    """让专门的模型写代码"""
    if not filepath.endswith(".py"):
        return "❌ [物理拦截] delegate_to_coder 只能生成 .py 文件！"

    workspace = get_user_workspace()
    safe_path = os.path.join(workspace, filepath)
    os.makedirs(os.path.dirname(safe_path), exist_ok=True)

    llm = get_llm(model_name=settings.MODEL_CODER, temperature=0.1, streaming=False)
    messages = [
        SystemMessage(content="你是高级Python工程师。只输出纯代码，用 Markdown 代码块包裹。"),
        HumanMessage(content=f"需求：{requirement}\n保存路径：{safe_path}")
    ]

    try:
        response = llm.invoke(messages).content
        code = response.split("```python")[1].split("```")[0].strip() if "```python" in response else response.replace("```", "").strip()
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(code)
        return f"✅ 代码已写入: {safe_path}"
    except Exception as e:
        return f"❌ 生成代码失败: {str(e)}"


# ══════════════════════════════════════════════════════════
# AST 安全审计（防止热装载危险代码）
# ══════════════════════════════════════════════════════════
_FORBIDDEN_MODULES  = {"subprocess", "pty", "ctypes", "socket", "pickle", "marshal", "multiprocessing", "importlib", "builtins"}
_FORBIDDEN_BUILTINS = {"eval", "exec", "compile", "__import__", "globals", "locals", "vars"}
_FORBIDDEN_ATTRS    = {"system", "popen", "Popen", "run", "call", "check_output", "spawn", "execve", "fork"}

def _audit(code: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误: {e}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _FORBIDDEN_MODULES:
                    return False, f"禁止导入: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in _FORBIDDEN_MODULES:
                return False, f"禁止从危险模块导入: {node.module}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_BUILTINS:
                return False, f"禁止调用: {node.func.id}()"
            elif isinstance(node.func, ast.Attribute) and node.func.attr in _FORBIDDEN_ATTRS:
                return False, f"禁止调用方法: .{node.func.attr}()"
    return True, "通过"


def install_new_tool(tool_name: str, requirement: str) -> str:
    """
    动态安装新工具并热注册到运行时。
    完整流程：LLM 写代码 → AST 审计 → 写入 skills/ → importlib 加载 → 注册进 DISPATCHER + SCHEMA
    """
    # ── Step 1: 标识符校验 ──
    if not tool_name or not tool_name.isidentifier() or tool_name.startswith("_"):
        return f"❌ 工具名 [{tool_name!r}] 不合法"

    # ── Step 2: 让 Coder 写工具代码 ──
    skills_dir = get_user_skills_dir()
    tool_path  = os.path.join(skills_dir, f"{tool_name}.py")

    # 要求 Coder 同时生成工具函数 + SCHEMA 描述
    full_requirement = f"""
请编写一个名为 `{tool_name}` 的 Python 工具函数。

业务需求：
{requirement}

输出格式要求（必须严格遵守）：
1. 文件开头写一行注释说明功能：# {tool_name}: 功能描述
2. 定义与工具名完全一致的顶层函数 `def {tool_name}(...):`
3. 在文件末尾定义 SCHEMA 变量，格式如下：
   SCHEMA = {{
       "name": "{tool_name}",
       "description": "工具的一句话描述",
       "input_schema": {{
           "type": "object",
           "properties": {{
               "参数名": {{"type": "string", "description": "参数说明"}}
           }},
           "required": ["参数名"]
       }}
   }}
只输出代码，不要任何解释。
"""
    llm = get_llm(model_name=settings.MODEL_CODER, temperature=0.1, streaming=False)
    messages = [
        SystemMessage(content="你是高级Python工程师。只输出纯代码，用 Markdown 代码块包裹。"),
        HumanMessage(content=full_requirement)
    ]

    try:
        response = llm.invoke(messages).content
        code = response.split("```python")[1].split("```")[0].strip() if "```python" in response else response.replace("```", "").strip()
    except Exception as e:
        return f"❌ Coder 生成代码失败: {e}"

    # ── Step 3: AST 安全审计 ──
    passed, reason = _audit(code)
    if not passed:
        return f"❌ 安全审计未通过: {reason}"

    # ── Step 4: 写入文件 ──
    header = f"# Auto-installed: {tool_name}\n# Installed at: {__import__('datetime').datetime.now().isoformat()}\n\n"
    with open(tool_path, "w", encoding="utf-8") as f:
        f.write(header + code + "\n")

    # ── Step 5: importlib 动态加载 ──
    try:
        spec   = importlib.util.spec_from_file_location(tool_name, tool_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        try: os.remove(tool_path)
        except: pass
        return f"❌ 模块加载失败（已回滚文件）: {e}"

    if not hasattr(module, tool_name) or not callable(getattr(module, tool_name)):
        os.remove(tool_path)
        return f"❌ 代码中未找到函数 `{tool_name}()`，请确保函数名与工具名一致"

    func   = getattr(module, tool_name)
    schema = getattr(module, "SCHEMA", None)

    # ── Step 6: 热注册进运行时 ──
    # 延迟导入避免循环依赖
    from modules.zclaw._registry import TOOL_DISPATCHER, ZCLAW_TOOLS_SCHEMA

    is_update = tool_name in TOOL_DISPATCHER
    TOOL_DISPATCHER[tool_name] = func

    if schema:
        openai_schema = {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["input_schema"],
            }
        }
        if is_update:
            for i, s in enumerate(ZCLAW_TOOLS_SCHEMA):
                if isinstance(s, dict) and s.get("function", {}).get("name") == tool_name:
                    ZCLAW_TOOLS_SCHEMA[i] = openai_schema
                    break
        else:
            ZCLAW_TOOLS_SCHEMA.append(openai_schema)

    action = "热更新" if is_update else "安装成功"
    return (
        f"✅ 工具 [{tool_name}] {action}！\n"
        f"   路径: skills/{tool_name}.py\n"
        f"   Schema 已注册: {'是' if schema else '否（下次重启生效）'}\n"
        f"   当前工具总数: {len(TOOL_DISPATCHER)}\n"
        f"   下一轮推理即可直接调用。"
    )


SCHEMA = [
    {
        "name": "delegate_to_coder",
        "description": "委托专业模型编写Python代码并存入沙箱。filepath 必须是 .py 文件。",
        "input_schema": {
            "type": "object",
            "properties": {
                "requirement": {"type": "string", "description": "详细的代码需求说明"},
                "filepath":    {"type": "string", "description": "相对于沙箱的 .py 文件路径"}
            },
            "required": ["requirement", "filepath"]
        }
    },
    {
        "name": "install_new_tool",
        "description": (
            "【自成长核心】发现能力缺口时，动态编写并安装新工具，热注册到运行时。"
            "安装成功后下一轮推理即可直接调用，无需重启。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name":   {"type": "string", "description": "工具函数名，合法 Python 标识符"},
                "requirement": {"type": "string", "description": "工具的详细功能需求"}
            },
            "required": ["tool_name", "requirement"]
        }
    }
]
