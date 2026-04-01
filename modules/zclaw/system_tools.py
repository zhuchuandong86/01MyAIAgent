"""
system_tools.py — 系统原子操作（安全加固版）
────────────────────────────────────────────────────────────
变更说明（对比旧版）：

[安全修复 #1] execute_bash — 双层命令过滤
  - 灾难级黑名单：直接拒绝（rm -rf /、fork bomb 等）
  - 高危警告级：允许执行但在输出前追加红色警告（curl|bash 等）
  - cwd=WORKSPACE 保持原有默认目录限制

[安全修复 #2] read_file — 路径越权修复
  - 旧版 startswith(WORKSPACE) 存在边界漏洞：
    /workspace2 会被误判为 /workspace 的子目录
  - 新版强制追加 os.sep 后再比较，彻底修复

[架构变更] append_memory 已迁移至 memory_tools.py
  - 此文件不再定义 append_memory
  - __init__.py 从 memory_tools 导入
"""

import os
import re
import subprocess
import core.paths

WORKSPACE   = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")
MEMORY_FILE = os.path.join(WORKSPACE, "experience_log.md")   # 保留供 read_file 访问


# ══════════════════════════════════════════════════════════
# 安全规则表
# ══════════════════════════════════════════════════════════

# 【灾难级】：直接拒绝，不执行
_BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(r"rm\s+-rf\s+[/~]"),                     # 删根目录 / 家目录
    re.compile(r"rm\s+--no-preserve-root"),              # 强制删根
    re.compile(r"mkfs"),                                 # 格式化磁盘
    re.compile(r"dd\s+if=.+of=/dev/(?!null)"),           # 覆盖设备（/dev/null 豁免）
    re.compile(r":\(\)\s*\{.*\|.*:.*&.*\}"),             # fork bomb
    re.compile(r">\s*/dev/sd[a-z]"),                     # 覆写磁盘设备
    re.compile(r"chmod\s+-R\s+[0-7]*7\s+/(?!home|tmp)"),# 危险权限变更根目录
    re.compile(r"/etc/shadow"),                          # 读写密码文件
    re.compile(r"/etc/passwd\s*>"),                      # 覆写用户文件
    re.compile(r"shutdown|reboot|halt|poweroff"),        # 系统级操作
]

# 【高危警告级】：允许执行，但在结果前追加警告（方便模型看到并反思）
_WARNING_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"curl.+\|\s*(ba)?sh"),   "⚠️ 警告：检测到 curl|shell 管道执行，请确认脚本来源可信！"),
    (re.compile(r"wget.+\|\s*(ba)?sh"),   "⚠️ 警告：检测到 wget|shell 管道执行，请确认脚本来源可信！"),
    (re.compile(r"pip\s+install"),        "ℹ️ 提示：正在安装 Python 包，若失败请检查包名拼写或网络。"),
    (re.compile(r"sudo\s"),               "⚠️ 警告：检测到 sudo 提权操作，请确认必要性！"),
]


def _check_command(command: str) -> tuple[bool, str]:
    """
    双层检查命令安全性。
    返回 (allowed: bool, prefix_message: str)
    """
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(command):
            matched = pattern.pattern
            return False, f"🚫 命令被安全层拦截（灾难级规则: `{matched}`）\n命令: {command}"

    warnings = []
    for pattern, msg in _WARNING_PATTERNS:
        if pattern.search(command):
            warnings.append(msg)

    return True, "\n".join(warnings)


# ══════════════════════════════════════════════════════════
# 公开工具函数
# ══════════════════════════════════════════════════════════

def execute_bash(command: str) -> str:
    """
    系统终端权限。运行脚本、装包均用此工具。
    已内置双层安全过滤，灾难级命令会被直接拒绝。
    """
    command = command.strip()

    # 安全检查
    allowed, prefix_msg = _check_command(command)
    if not allowed:
        return prefix_msg  # 直接返回拦截消息，不执行

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw_output = (result.stdout + "\n" + result.stderr).strip() or "执行成功，无输出。"

        # 超长截断（保留尾部，尾部通常是报错信息）
        if len(raw_output) > 4000:
            raw_output = "...[前文已省略，显示最后 4000 字符]...\n" + raw_output[-4000:]

        output = (prefix_msg + "\n\n" if prefix_msg else "") + raw_output
        return output

    except subprocess.TimeoutExpired:
        return "❌ 执行超时（120 秒），进程已被强制终止。请检查是否有死循环或阻塞 IO。"
    except Exception as e:
        return f"❌ 终端崩溃: {str(e)}"


def read_file(filepath: str) -> str:
    """
    文本阅读。用于任务前探测及代码执行后的结果审核。
    ⚠️ 安全修复：使用 os.sep 后缀比较，防止路径前缀误判漏洞。
    """
    try:
        workspace_abs = os.path.abspath(WORKSPACE) + os.sep  # ← 关键修复
        safe_path     = os.path.abspath(os.path.join(WORKSPACE, filepath))

        # 路径必须在沙盒内（结尾 os.sep 防止 /workspace2 被误判为子目录）
        if not (safe_path + os.sep).startswith(workspace_abs) and safe_path != os.path.abspath(WORKSPACE):
            return (
                f"❌ 越权读取被拦截：禁止访问工作区之外的文件！\n"
                f"   请求路径: {safe_path}\n"
                f"   沙盒根目录: {os.path.abspath(WORKSPACE)}"
            )

        with open(safe_path, "r", encoding="utf-8") as f:
            content = f.read(8000)

        if len(content) == 8000:
            content += "\n\n...[文件过长，已截断至前 8000 字符]..."

        return content

    except FileNotFoundError:
        return f"❌ 文件不存在: {filepath}（相对于工作区 {WORKSPACE}）"
    except UnicodeDecodeError:
        return f"❌ 文件编码错误，可能是二进制文件，无法用 read_file 读取: {filepath}"
    except Exception as e:
        return f"❌ 读取失败: {str(e)}"
