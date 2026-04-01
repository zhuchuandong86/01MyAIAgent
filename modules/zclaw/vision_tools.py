"""
vision_tools.py — 视觉中枢（MIME 类型修复版）
────────────────────────────────────────────────────────────
变更说明（对比旧版）：

[安全修复 #4] MIME 类型硬编码问题
  - 旧版无论文件是 .png 还是 .jpg，都强制声明 image/jpeg
  - 部分视觉模型会因 MIME 不匹配导致解析错误或静默失败
  - 新版使用 mimetypes 标准库自动推断，并提供合理兜底值
"""

import os
import base64
import mimetypes
from openai import OpenAI

import core.paths
from core.settings import settings
from core.token_tracker import log_usage

WORKSPACE = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")

# 独立实例化 Vision 客户端（与主控 brain_client 解耦）
vision_client = OpenAI(
    api_key=settings.API_KEY,
    base_url=settings.API_BASE,
    timeout=60.0,
)
v_model = getattr(settings, "MODEL_VISION", None)

# 支持的图片扩展名 → MIME 类型白名单
_SUPPORTED_MIME: dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}


def ask_vision(image_filename: str, question: str) -> str:
    """
    面对扫描件、图片等调用此接口。
    仅支持图片格式（jpg/jpeg/png/gif/webp），不支持 PDF。
    """
    if not v_model:
        return "❌ 视觉神经未接入（MODEL_VISION 未配置）。"

    lower = image_filename.lower()

    # ── PDF 专项拦截（附带解决方案提示）──
    if lower.endswith(".pdf"):
        return (
            "❌ ask_vision 不支持 PDF 格式！\n"
            "【解决方案】: 请调用 delegate_to_coder，写一个 Python 脚本将 PDF 转为图片\n"
            "（推荐使用 pdf2image 库：pip install pdf2image），再用 ask_vision 处理图片。"
        )

    # ── 格式校验 ──
    ext = os.path.splitext(lower)[1]
    if ext not in _SUPPORTED_MIME:
        return (
            f"❌ 不支持的文件格式: {image_filename}\n"
            f"   支持的格式: {', '.join(_SUPPORTED_MIME.keys())}"
        )

    # ── MIME 推断（修复：不再硬编码 image/jpeg）──
    mime_type, _ = mimetypes.guess_type(image_filename)
    if mime_type not in _SUPPORTED_MIME.values():
        # fallback：按扩展名白名单查找，比 mimetypes 更可靠
        mime_type = _SUPPORTED_MIME.get(ext, "image/jpeg")

    try:
        img_path = os.path.join(WORKSPACE, image_filename)

        with open(img_path, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode("utf-8")

        strict_prompt = (
            question
            + "\n\n【最高优先级系统指令】：如果是表格或密集数据，"
            "你必须化身为无感情的机器。逐行逐列提取原文，用 Markdown 表格输出。"
            "严禁做归纳总结！"
        )

        response = vision_client.chat.completions.create(
            model=v_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": strict_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                # 修复：使用正确的 mime_type 而非硬编码 image/jpeg
                                "url": f"data:{mime_type};base64,{b64_img}"
                            },
                        },
                    ],
                }
            ],
        )

        # Token 计量
        if hasattr(response, "usage") and response.usage:
            log_usage("ZClaw-视觉中枢", v_model, response.usage.total_tokens)

        return f"👁️ 视觉中枢反馈:\n{response.choices[0].message.content}"

    except FileNotFoundError:
        return f"❌ 图片文件不存在: {image_filename}（工作区: {WORKSPACE}）"
    except Exception as e:
        return f"❌ 视觉中枢崩溃: {str(e)}"
