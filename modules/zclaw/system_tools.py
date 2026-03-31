import os
import subprocess
import core.paths

WORKSPACE = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")
MEMORY_FILE = os.path.join(WORKSPACE, "experience_log.md")

def execute_bash(command: str) -> str:
    try:
        result = subprocess.run(command, shell=True, cwd=WORKSPACE, capture_output=True, text=True, timeout=120)
        output = (result.stdout + "\n" + result.stderr).strip() or "执行成功，无输出。"
        if len(output) > 4000:
            output = "...[前文已省略]...\n" + output[-4000:]
        return output
    except Exception as e: return f"终端崩溃: {str(e)}"

def read_file(filepath: str) -> str:
    try:
        safe_path = os.path.abspath(os.path.join(WORKSPACE, filepath))
        if not safe_path.startswith(os.path.abspath(WORKSPACE)):
            return "❌ 越权读取被拦截：禁止访问工作区之外的文件！"
        with open(safe_path, 'r', encoding='utf-8') as f: return f.read()[:8000]
    except Exception as e: return f"读取失败: {str(e)}"

def append_memory(lesson: str) -> str:
    try:
        with open(MEMORY_FILE, 'a', encoding='utf-8') as f: f.write(f"- {lesson}\n")
        return f"✅ 认知升级完毕，经验已刻入: {lesson}"
    except Exception as e: return f"记忆刻录失败: {str(e)}"