import os
import base64
from openai import OpenAI

import core.paths
from core.settings import settings
from core.token_tracker import log_usage

WORKSPACE = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")

# 独立实例化 Vision 客户端
vision_client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE, timeout=60.0)
v_model = getattr(settings, "MODEL_VISION", None)

def ask_vision(image_filename: str, question: str) -> str:
    if not v_model: 
        return "视觉神经未接入 (模型为空)。"
    
    lower_filename = image_filename.lower()
    if lower_filename.endswith('.pdf'):
        return "❌ 工具致命报错：ask_vision 只能处理 .jpg / .png / .jpeg 等图片格式，无法直接把 .pdf 喂给视觉模型！\n【系统建议】：请立即调用 delegate_to_coder 写一个 Python 脚本将 PDF 转为图片后再处理。"
    elif not (lower_filename.endswith('.jpg') or lower_filename.endswith('.png') or lower_filename.endswith('.jpeg')):
        return f"❌ 工具报错：不支持的文件格式 {image_filename}。视觉模型只支持图片。"

    try:
        strict_prompt = question + "\n\n【最高优先级系统指令】：如果是表格或密集数据，你必须化身为无感情的机器。逐行逐列提取原文，用Markdown表格输出。严禁做归纳总结！"
        
        img_path = os.path.join(WORKSPACE, image_filename)
        with open(img_path, "rb") as f: 
            b64_img = base64.b64encode(f.read()).decode('utf-8')
        
        response = vision_client.chat.completions.create(
            model=v_model,
            messages=[{"role": "user", "content": [{"type": "text", "text": strict_prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}]}]
        )
        
        # 🌟 记录多模态视觉请求的 Token 消耗
        if hasattr(response, 'usage') and response.usage:
            total_tokens = response.usage.total_tokens
            log_usage("ZClaw-视觉中枢", v_model, total_tokens)
            
        return f"👁️ 视觉中枢反馈: {response.choices[0].message.content}"

    except Exception as e: 
        return f"视觉中枢崩溃: {str(e)}"