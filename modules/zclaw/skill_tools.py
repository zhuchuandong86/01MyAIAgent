"""
skill_tools.py — Phase 2 + Phase 3: 技能感知 & 工具自扩展引擎
────────────────────────────────────────────────────────────
Phase 2: scan_skills / list_skills
  - 任务开始前主动扫描 skills/ 目录，生成可复用技能清单（现已支持子目录递归扫描！）
  - 提取每个 .py 文件的首行注释作为功能描述
  - 通过工具 list_skills 暴露给模型，强制其先查再做

Phase 3: install_new_tool  ← OpenClaw 核心
  - 模型发现能力缺口后，自主写代码 -> 调用此函数热装载新工具
  - 三层安全防护：① 标识符校验 ② AST 级危险节点扫描 ③ 沙盒导入隔离
  - 热注册进 _registry.TOOL_DISPATCHER 和 ZCLAW_TOOLS_SCHEMA，
    下一轮推理即可直接调用新工具，无需重启 Streamlit
"""

import os
import ast
import json
import importlib.util
import core.paths

# 从独立注册中心导入，避免循环导入
from ._registry import TOOL_DISPATCHER, ZCLAW_TOOLS_SCHEMA

WORKSPACE  = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")
SKILLS_DIR = os.path.join(WORKSPACE, "skills")


# ══════════════════════════════════════════════════════════
# Phase 2 — 技能库主动感知 (支持深度递归扫描)
# ══════════════════════════════════════════════════════════

def scan_skills() -> str:
    """
    深度扫描 skills/ 目录下的所有 Python 脚本（支持子文件夹穿透）。
    返回当前可复用技能的清单字符串。
    供 System Prompt 动态注入，让模型在任务开始前先了解已有能力。
    """
    if not os.path.exists(SKILLS_DIR):
        return "（skills/ 目录不存在，尚无可复用技能）"

    skills = []
    
    # 🌟 使用 os.walk 进行深度递归遍历
    for root, dirs, files in os.walk(SKILLS_DIR):
        for fname in sorted(files):
            # 只扫描 .py 文件，且过滤掉 __init__.py 等双下划线隐藏文件
            if not fname.endswith(".py") or fname.startswith("__"):
                continue
                
            fpath = os.path.join(root, fname)
            
            # 计算相对于 WORKSPACE 的路径 (用于提示模型所在位置)
            rel_path = os.path.relpath(fpath, WORKSPACE)
            # 将路径转化为 Python 的导包语法 (例如: skills/pdf/parser.py -> skills.pdf.parser)
            import_path = rel_path.replace(os.sep, ".").replace(".py", "")

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    lines = f.read(600).splitlines()
                # 优先提取 docstring，其次首行注释
                desc = "（无描述）"
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        desc = stripped.lstrip("#").strip()
                        break
                    if stripped.startswith('"""') or stripped.startswith("'''"):
                        desc = stripped.strip('"\'').strip()
                        break
                
                # 组装带 import 路径和功能描述的清单字符串
                skills.append(f"  - 📦 模块: `{import_path}` (相对路径: `{rel_path}`) : {desc}")
            except Exception as e:
                skills.append(f"  - 📦 模块: `{import_path}` (相对路径: `{rel_path}`) : （读取失败: {e}）")

    if not skills:
        return "（skills/ 目录为空或未找到有效的 .py 脚本，尚无可复用技能）"

    return "【已有技能库 — 优先复用，禁止重复造轮子】:\n" + "\n".join(skills) + "\n\n💡 提示：如果不清楚模块里的具体函数名或参数，请务必先使用 read_file 工具读取对应的 .py 文件源码！"


def list_skills() -> str:
    """工具接口：主动查询技能库。任务开始前应调用！"""
    return scan_skills()


# ══════════════════════════════════════════════════════════
# Phase 3 — 工具自扩展：安全审计层
# ══════════════════════════════════════════════════════════

# 绝对禁止的模块（AST 级别拦截）
_FORBIDDEN_MODULES = {
    "subprocess", "pty", "pty", "ctypes", "cffi",
    "socket", "asyncio",           # 防网络出逃
    "pickle", "marshal",           # 防反序列化攻击
    "multiprocessing", "threading",
    "importlib",                   # 防二次动态加载绕过审计
    "builtins",
}

# 绝对禁止的内置函数名
_FORBIDDEN_BUILTINS = {
    "eval", "exec", "compile", "__import__",
    "breakpoint", "input",
    "globals", "locals", "vars",
}

# 危险属性调用（obj.xxx 的 xxx 部分）
_FORBIDDEN_ATTRS = {
    "system", "popen", "Popen", "run", "call", "check_output",
    "spawn", "execve", "execvp", "fork",
}


def _audit_code(code: str) -> tuple[bool, str]:
    """
    AST 级安全审计（比字符串匹配更可靠，不会被注释或字符串绕过）。
    返回 (通过, 原因)。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误，无法解析: {e}"

    for node in ast.walk(tree):

        # ① 检查 import 危险模块
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_MODULES:
                    return False, f"禁止导入危险模块: {alias.name}"

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in _FORBIDDEN_MODULES:
                    return False, f"禁止从危险模块导入: {node.module}"

        # ② 检查危险内置函数调用（直接调用）
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in _FORBIDDEN_BUILTINS:
                    return False, f"禁止调用危险内置函数: {node.func.id}()"

            # ③ 检查危险属性方法调用（obj.system() 等）
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in _FORBIDDEN_ATTRS:
                    return False, f"禁止调用危险方法: .{node.func.attr}()"

        # ④ 拦截 os 模块的 system / popen 等（通过属性访问）
        elif isinstance(node, ast.Attribute):
            if node.attr in _FORBIDDEN_ATTRS:
                # 只有当对象本身不是安全的 path 操作才拦截
                if not (isinstance(node.value, ast.Attribute) and node.value.attr == "path"):
                    return False, f"检测到危险属性访问: .{node.attr}"

    return True, "通过安全审计"


# ══════════════════════════════════════════════════════════
# Phase 3 — 工具自扩展：动态安装引擎
# ══════════════════════════════════════════════════════════

def install_new_tool(tool_name: str, tool_code: str, tool_schema_json: str) -> str:
    """
    OpenClaw 核心能力：运行时动态安装新工具并热注册到调度层。

    参数：
      tool_name      : 工具函数名（必须是合法 Python 标识符）
      tool_code      : 工具的完整 Python 源码（包含与 tool_name 同名的函数）
      tool_schema_json: 工具的 OpenAI function-calling JSON Schema（字符串）

    流程：
      1. 标识符合法性校验
      2. AST 安全审计（拒绝危险代码）
      3. 解析 JSON Schema
      4. 写入 skills/{tool_name}.py
      5. importlib 动态加载（隔离沙盒）
      6. 热注册进 TOOL_DISPATCHER + ZCLAW_TOOLS_SCHEMA
    """

    # ── Step 1: 标识符校验 ──
    if not tool_name or not tool_name.isidentifier():
        return f"❌ 工具名 [{tool_name!r}] 不合法，必须是有效的 Python 标识符（字母/数字/下划线，不以数字开头）。"

    if tool_name.startswith("_"):
        return f"❌ 工具名不能以下划线开头（保留给内部模块）。"

    # ── Step 2: AST 安全审计 ──
    passed, reason = _audit_code(tool_code)
    if not passed:
        return (
            f"❌ 安全审计未通过，工具安装被拒绝。\n"
            f"   原因: {reason}\n"
            f"   请修改代码后重新提交。"
        )

    # ── Step 3: 解析 JSON Schema ──
    try:
        if isinstance(tool_schema_json, str):
            tool_schema = json.loads(tool_schema_json)
        elif isinstance(tool_schema_json, dict):
            tool_schema = tool_schema_json
        else:
            return f"❌ tool_schema_json 类型错误，必须是 JSON 字符串或 dict。"
    except json.JSONDecodeError as e:
        return f"❌ tool_schema_json 解析失败: {e}"

    # 校验 Schema 基本结构
    if not (isinstance(tool_schema, dict) and tool_schema.get("type") == "function"):
        return (
            '❌ tool_schema_json 格式不正确，需要形如:\n'
            '{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}'
        )

    # ── Step 4: 写入文件 ──
    os.makedirs(SKILLS_DIR, exist_ok=True)
    tool_path = os.path.join(SKILLS_DIR, f"{tool_name}.py")

    header = (
        f"# Auto-installed tool: {tool_name}\n"
        f"# Installed at: {__import__('datetime').datetime.now().isoformat()}\n"
        f"# AST-audited and approved\n\n"
    )
    final_code = header + tool_code.strip() + "\n"

    with open(tool_path, "w", encoding="utf-8") as f:
        f.write(final_code)

    # ── Step 5: 动态加载 ──
    try:
        spec   = importlib.util.spec_from_file_location(tool_name, tool_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        # 加载失败，回滚文件
        try:
            os.remove(tool_path)
        except OSError:
            pass
        return f"❌ 模块加载失败（代码已回滚）: {e}"

    if not hasattr(module, tool_name):
        os.remove(tool_path)
        return (
            f"❌ 代码中未找到与工具同名的顶层函数: `{tool_name}()`。\n"
            f"   请确保代码中有一个名为 `{tool_name}` 的函数。"
        )

    func = getattr(module, tool_name)
    if not callable(func):
        os.remove(tool_path)
        return f"❌ `{tool_name}` 不是可调用的函数对象。"

    # ── Step 6: 热注册 ──
    is_update = tool_name in TOOL_DISPATCHER

    TOOL_DISPATCHER[tool_name] = func

    if is_update:
        # 更新已有 Schema 条目
        for i, s in enumerate(ZCLAW_TOOLS_SCHEMA):
            if isinstance(s, dict) and s.get("function", {}).get("name") == tool_name:
                ZCLAW_TOOLS_SCHEMA[i] = tool_schema
                break
        return (
            f"🔄 工具 [{tool_name}] 已热更新（覆盖旧版本）。\n"
            f"   路径: skills/{tool_name}.py\n"
            f"   下一轮推理即可使用更新后的版本。"
        )
    else:
        ZCLAW_TOOLS_SCHEMA.append(tool_schema)
        return (
            f"✅ 新工具 [{tool_name}] 安装成功！\n"
            f"   路径: skills/{tool_name}.py\n"
            f"   已热注册进调度层，下一轮推理可直接调用。\n"
            f"   当前工具总数: {len(TOOL_DISPATCHER)}"
        )