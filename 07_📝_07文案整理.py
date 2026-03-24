# pages/07_📝_文案整理.py
import streamlit as st
import os
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import COPYWRITING_SYSTEM_PROMPT, COPYWRITING_DEFAULT_REQ

# ==========================================
# 0. 预设金牌提示词 (Prompt as a Service)
# ==========================================
PROMPT_MEETING = """请将以下素材整理为专业、结构极其清晰的【会议纪要】。
【强制要求】：
1. 提炼一句“会议主旨”。
2. 按照核心议题进行模块化拆分，提炼各项的“关键结论”。
3. 必须单独列出“待办事项 (Action Items)”模块，包含具体动作和可能的跟进人。
4. 剔除所有口语化废话、重复和寒暄，使用标准的 Markdown 标题和列表排版。"""

PROMPT_WEEKLY = """请将以下零散的素材整理为一份高质量、结果导向的【工作周报】。
【强制要求】：
1. 严格按照以下四个模块重构文本：“本周核心工作（按项目分类）”、“重点业绩/数据产出”、“遇到的问题与协同需求”、“下周工作计划”。
2. 提炼核心逻辑，把流水账转化为专业职场用语。
3. 如果原文没有提到某个模块，请在该模块下精简注明“暂无特别项”。
4. 语言必须客观、精炼，使用标准的 Markdown 排版。"""

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
        height=200
    )
with col2:
    requirement = st.text_area(
        "🎯 整理与排版要求 (自定义模式需填)", 
        placeholder="例如：\n1. 整理成小红书文案\n2. 加上Emoji\n3. 语气要活泼", 
        height=200
    )

st.write("") # 增加一点呼吸空间

# ==========================================
# 3. 快捷指令与启动区 (UI 融合)
# ==========================================
st.markdown("#### ⚡ 选择整理模式并启动双核对决")
col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])

active_instruction = None
action_name = ""

with col_btn1:
    if st.button("📋 一键生成【会议纪要】", use_container_width=True, type="secondary"):
        active_instruction = PROMPT_MEETING
        action_name = "会议纪要"

with col_btn2:
    if st.button("📊 一键生成【工作周报】", use_container_width=True, type="secondary"):
        active_instruction = PROMPT_WEEKLY
        action_name = "工作周报"

with col_btn3:
    if st.button("🚀 启动自定义整理 (A/B Test)", type="primary", use_container_width=True):
        active_instruction = requirement.strip() if requirement.strip() else COPYWRITING_DEFAULT_REQ
        action_name = "自定义排版"

# ==========================================
# 4. 核心生成逻辑 (完美保留原有的双模型并发和卡片UI)
# ==========================================
if active_instruction:
    if not raw_text.strip():
        st.warning("⚠️ 请输入需要整理的原始素材！")
        st.stop()
        
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", COPYWRITING_SYSTEM_PROMPT),
        ("user", "【整理要求】\n{req}\n\n【原始素材】\n{text}")
    ])

    st.divider()
    st.markdown(f"### 🤖 正在为您进行 {action_name} A/B 方案生成...")
    
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
                        for chunk in (prompt_template | llm).stream({"req": active_instruction, "text": raw_text}):
                            full_text += chunk.content
                            placeholder.markdown(full_text + " ▌")
                        placeholder.markdown(full_text)
                        
                        # 计费拦截
                        tokens = cb.total_tokens
                        if tokens == 0:
                            tokens = int((len(raw_text) + len(active_instruction) + len(full_text)) * 1.2)
                        log_usage("文案双核整理", model_name, tokens)
                        
                        st.markdown("---")
                        st.download_button(
                            label=f"📥 采纳并下载 {title_prefix}", 
                            data=full_text, 
                            file_name=f"{action_name}_{title_prefix}.md", 
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