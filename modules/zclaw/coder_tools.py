"""
coder_tools.py — Coder 专员（基本不变，细节完善）
────────────────────────────────────────────────────────────
变更说明（对比旧版）：

[安全修复 #2 同步] 路径越权检查使用 os.sep 后缀，与 system_tools 保持一致。
[细节] Markdown 代码块清理更健壮（支持带语言标记的多种写法）。
"""

import os
import re
from openai import OpenAI
import core.paths
from core.settings import settings
from core.token_tracker import log_usage

WORKSPACE = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")

# 独立实例化 Coder 客户端（超时 120s，写代码任务通常较慢）
coder_client = OpenAI(
    api_key=settings.API_KEY,
    base_url=settings.API_BASE,
    timeout=120.0,
)
c_model = getattr(settings, "MODEL_CODER", settings.MODEL_TEXT)

# 清除 Markdown 代码块标记的正则（支持 ```python、```py、``` 等）
_CODE_FENCE = re.compile(r"^```[a-z]*\n?|```$", re.MULTILINE)


def delegate_to_coder(filepath: str, task_description: str) -> str:
    """
    算法外包：让 Coder 专员撰写 Python 脚本并保存到指定路径。
    filepath 必须是 .py 文件。可复用逻辑应存入 skills/ 目录。
    """
    if not filepath.strip().endswith(".py"):
        return "❌ filepath 必须以 .py 结尾！Coder 只写 Python 脚本，不写其他格式。"

    sys_prompt = (
        "你是底层算法架构师。只输出独立可运行的 Python 代码，"
        "绝对不要任何 Markdown 标记或多余的解释。"
        "如果涉及读写，注意编码（utf-8）。"
        "如果代码可复用，在文件顶部写一行注释说明功能，方便未来索引。"
    )

    try:
        response = coder_client.chat.completions.create(
            model=c_model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {
                    "role": "user",
                    "content": f"目标路径: {filepath}\n\n严苛需求:\n{task_description}",
                },
            ],
            temperature=0.1,
        )

        # Token 计量
        if hasattr(response, "usage") and response.usage:
            log_usage("ZClaw-Coder专员", response.model, response.usage.total_tokens)

        # 清除 Markdown 代码块标记
        raw = response.choices[0].message.content or ""
        code_content = _CODE_FENCE.sub("", raw).strip()

        # 路径安全校验（与 system_tools 修复保持一致）
        workspace_abs = os.path.abspath(WORKSPACE) + os.sep
        safe_path     = os.path.abspath(os.path.join(WORKSPACE, filepath))
        if not (safe_path + os.sep).startswith(workspace_abs) and safe_path != os.path.abspath(WORKSPACE):
            return (
                f"❌ 代码注入越权拦截！\n"
                f"   请求路径 {safe_path} 超出沙盒范围 {os.path.abspath(WORKSPACE)}"
            )

        os.makedirs(os.path.dirname(safe_path), exist_ok=True)

        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(code_content)

        return (
            f"👨‍💻 Coder 已成功构建代码并保存至 `{filepath}`。\n"
            f"   请用 execute_bash 运行它，观察输出后决定下一步。"
        )

    except Exception as e:
        return f"❌ Coder 脑力过载: {str(e)}"
