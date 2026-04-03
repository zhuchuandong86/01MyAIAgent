import os
import base64
import streamlit as st
import core.paths
from core.settings import settings
from core.llm_factory import get_llm
from langchain_core.messages import HumanMessage

def get_user_workspace():
    user = st.session_state.get("zclaw_user", "public")
    return os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"zclaw_workspace_{user}")

def ask_vision(image_filename: str, prompt: str) -> str:
    """调用视觉模型解析图片"""
    workspace = get_user_workspace()
    target_path = os.path.join(workspace, image_filename)
    if not os.path.exists(target_path):
        return f"❌ 找不到图片文件: {image_filename} (请确认它在您的专属沙箱中)"

    try:
        with open(target_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        ext = os.path.splitext(image_filename)[1].lower().replace('.', '')
        if ext == 'jpg': ext = 'jpeg'

        llm = get_llm(model_name=settings.MODEL_VISION, temperature=0.1, streaming=False)
        message = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{image_data}"}}
        ])

        response = llm.invoke([message]).content
        return f"👁️ 视觉模型返回结果:\n{response}"
    except Exception as e:
        return f"❌ 视觉解析失败: {str(e)}"

SCHEMA = [
    {
        "name": "ask_vision",
        "description": "当遇到图片文件时，调用此工具看图并提取信息。",
        "input_schema": {
            "type": "object",
            "properties": {"image_filename": {"type": "string"}, "prompt": {"type": "string"}},
            "required": ["image_filename", "prompt"]
        }
    }
]