# pages/07_📝_文案整理.py
import streamlit as st
import os
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import COPYWRITING_SYSTEM_PROMPT, COPYWRITING_DEFAULT_REQ

# 页面基本配置
st.set_page_config(page_title="智能文案整理", page_icon="📝", layout="wide")

st.title("📝 智能文案与排版引擎")
st.markdown("输入杂乱的草稿、会议转写或碎片化灵感，设定目标格式，由 **双模型** 同时为您生成两版精美排版，方便对比与挑选。")

# ==========================================
# 1. 模型阵营展示 (直接读取 .env 配置，禁止修改)
# ==========================================
# 优先读取专门的 EDITOR 模型，没有则使用 TEXT 或 RED 兜底
model_a = settings.MODEL_TEXT or "deepseek-v3-0324"
model_b = settings.MODEL_RED or "qwen2.5-72b-instruct"

st.info(f"💡 **当前对决引擎**： 🔵 **方案 A** (`{model_a}`) 🆚 🔴 **方案 B** (`{model_b}`)")

# ==========================================
# 2. 顶部输入区布局 (2:1 比例，视觉更平衡)
# ==========================================
col1, col2 = st.columns([2, 1])
with col1:
    raw_text = st.text_area(
        "📦 原始素材 (支持超长文本)", 
        placeholder="请在此粘贴您的会议记录、语音转写草稿、或者杂乱无章的碎片化灵感...", 
        height=300
    )
with col2:
    requirement = st.text_area(
        "🎯 整理与排版要求 (选填)", 
        placeholder="例如：\n1. 整理成正式的周报格式\n2. 提取核心结论，分点列出\n3. 语气要严肃专业、精炼", 
        height=300
    )

st.write("") # 增加一点呼吸空间

# ==========================================
# 3. 核心生成逻辑
# ==========================================
if st.button("🚀 启动双核整理 (A/B Test)", type="primary", use_container_width=True):
    if not raw_text.strip():
        st.warning("⚠️ 请输入需要整理的原始素材！")
        st.stop()
        
    # 默认金牌提示词
    final_req = requirement.strip() if requirement.strip() else COPYWRITING_DEFAULT_REQ

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", COPYWRITING_SYSTEM_PROMPT),
        ("user", "【整理要求】\n{req}\n\n【原始素材】\n{text}")
    ])

    st.divider()
    
    # 左右双分栏
    col_a, col_b = st.columns(2)

    def run_and_stream(model_name, container, title_prefix, color_emoji):
        with container:
            # 🌟 核心美化：使用带有 border 的卡片式容器包裹输出！
            with st.container(border=True):
                st.markdown(f"### {color_emoji} {title_prefix}")
                st.caption(f"🧠 驱动模型: `{model_name}`")
                st.markdown("---") # 卡片内的分割线
                
                placeholder = st.empty()
                
                llm = ChatOpenAI(
                    model=model_name,
                    api_key=settings.API_KEY,
                    base_url=settings.API_BASE,
                    temperature=0.3,
                    model_kwargs={"stream_options": {"include_usage": True}} 
                )
                
                full_text = ""
                with get_openai_callback() as cb:
                    try:
                        for chunk in (prompt_template | llm).stream({"req": final_req, "text": raw_text}):
                            full_text += chunk.content
                            placeholder.markdown(full_text + " ▌")
                        placeholder.markdown(full_text)
                        
                        # 计费拦截
                        tokens = cb.total_tokens
                        if tokens == 0:
                            tokens = int((len(raw_text) + len(final_req) + len(full_text)) * 1.2)
                        log_usage("文案双核整理", model_name, tokens)
                        
                        st.markdown("---")
                        st.download_button(
                            label=f"📥 采纳并下载 {title_prefix}", 
                            data=full_text, 
                            file_name=f"{title_prefix}_排版结果.md", 
                            mime="text/markdown", 
                            key=f"dl_{title_prefix}",
                            use_container_width=True
                        )
                        
                    except Exception as e:
                        placeholder.error(f"❌ 生成失败或响应超时:\n {e}")

    # 依次调用双模型渲染
    with st.spinner(f"正在调动 {model_a} 撰写方案 A ..."):
        run_and_stream(model_a, col_a, "方案 A", "🔵")
        
    with st.spinner(f"正在调动 {model_b} 撰写方案 B ..."):
        run_and_stream(model_b, col_b, "方案 B", "🔴")
        
    st.balloons()
    st.success("✅ 双方案生成完毕！请对比左右两侧的排版与语感，挑选您最满意的一版。")