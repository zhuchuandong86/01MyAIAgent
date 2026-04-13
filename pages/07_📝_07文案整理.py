# pages/07_📝_文案整理.py
import streamlit as st
import os
import re
import time 
import json
import concurrent.futures
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback
from langchain_text_splitters import RecursiveCharacterTextSplitter
from core.prompts import COPYWRITING_SYSTEM_PROMPT, COPYWRITING_DEFAULT_REQ

# ==========================================
# 0. 数据持久化：模版存储机制
# ==========================================
TEMPLATE_FILE = "copywriting_templates.json"

def load_templates():
    if os.path.exists(TEMPLATE_FILE):
        try:
            with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_templates(templates):
    with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
        json.dump(templates, f, ensure_ascii=False, indent=2)

if "templates" not in st.session_state:
    st.session_state.templates = load_templates()

# 预设金牌提示词 (3大场景)
PROMPT_CLIENT_MEETING = """请将以下素材整理为专业、得体的【外部会谈纪要】（通常用于向客户发送或内部记录客户核心诉求）。
【强制要求】：
1. 明确提炼“客户核心诉求/痛点”与“我方响应/承诺”。
2. 语气务必专业、得体、不卑不亢。
3. 必须包含“下一步推进计划 (Next Steps)”，明确双方责任人及时间节点。
4. 剔除内部口语化吐槽或不适宜对外的话语，使用标准的 Markdown 排版。"""

PROMPT_INTERNAL_MEETING = """请将以下素材整理为结构清晰、注重执行的【内部会议纪要】。
【强制要求】：
1. 提炼一句“会议主旨”。
2. 按照核心议题进行模块化拆分，提炼各项的“关键结论”和“争议点”。
3. 必须单独列出“待办事项 (Action Items)”模块，包含具体动作和跟进人。
4. 剔除废话，语言精炼直白，使用标准的 Markdown 标题和列表排版。"""

PROMPT_OPERATIONAL = """请将以下零散的素材整理为一份高质量、结果导向的【运作纪要】（如周报/月报/项目汇报）。
【强制要求】：
1. 重点突出“核心业绩/数据产出”与“关键项目进展”。
2. 明确列出“当前风险/求助事项”与“下一步计划”。
3. 提炼核心逻辑，把流水账转化为专业职场管理语境。
4. 语言必须客观、精炼，如果某项没有内容请标注“暂无特别项”，使用标准的 Markdown 排版。"""

# 页面基本配置
st.set_page_config(page_title="智能文案整理", page_icon="📝", layout="wide")
st.title("📝 智能文案与排版引擎")
st.markdown("输入杂乱素材，设定目标格式或**套用您保存的经验模版**，由 **双模型** 极速为您生成两版精美排版。")

# 模型阵营
model_a = settings.MODEL_TEXT or "deepseek-v3-0324"
model_b = settings.MODEL_RED or "qwen2.5-72b-instruct"
st.info(f"💡 **当前对决引擎**： 🔵 **方案 A** (`{model_a}`) 🆚 🔴 **方案 B** (`{model_b}`)")

# ==========================================
# 1. 顶部输入区与模版管理
# ==========================================
col1, col2 = st.columns([2, 1])

with col1:
    uploaded_files = st.file_uploader(
        "📂 上传本地素材 (支持多文件合并, .txt, .md)", 
        type=["txt", "md"], 
        accept_multiple_files=True
    )
    
    manual_text = st.text_area(
        "📦 原始杂乱素材 (支持直接粘贴，或结合上方文件一起使用)", 
        placeholder="请在此粘贴您的会议记录、语音转写草稿、或者杂乱无章的碎片化灵感...", 
        height=320
    )

with col2:
    requirement = st.text_area(
        "🎯 附加要求 (可选)", 
        placeholder="例如：\n1. 加上Emoji\n2. 语气要活泼\n3. 重点标红...", 
        height=100
    )

    # 永久模版录入区
    with st.expander("💾 录入并保存新【经验模版】", expanded=False):
        # st.caption("粘贴优秀的 Word 或历史纪要，保存后可供下方随时调用。")
        new_tpl_name = st.text_input("模版名称 (必填)", placeholder="例如：阿里风技术周报")
        new_tpl_content = st.text_area("模版内容", height=120)
        if st.button("✅ 永久保存模版", use_container_width=True):
            if new_tpl_name.strip() and new_tpl_content.strip():
                st.session_state.templates[new_tpl_name.strip()] = new_tpl_content.strip()
                save_templates(st.session_state.templates)
                st.success(f"模版【{new_tpl_name}】已永久保存！")
                st.rerun()
            else:
                st.warning("⚠️ 模版名称和内容均不能为空！")
    
    with st.expander("🛠️ 高级预处理选项"):
        clean_timestamps = st.checkbox("🧹 清理录音时间戳", value=True, help="自动去除 [00:01:23] 等时间戳")
        reorder_logic = st.checkbox("🧠 智能逻辑重组", value=True, help="强制要求模型先理顺乱序时间线再排版")
        enable_compression = st.checkbox("✂️ 超长文本前置并发压缩", value=True, help="超4万字时自动多线程提炼，防爆Token")

st.write("") 

# ==========================================
# 2. 快捷指令与启动区 (含模版选择与删除)
# ==========================================
st.markdown("#### ⚡ 选择场景模式与模版，启动双核对决")
col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)

active_instruction = None
action_name = ""
custom_req = requirement.strip()

def build_final_prompt(base_prompt, current_req, ref_temp):
    inst = base_prompt
    if current_req:
        inst += f"\n\n【用户的额外特殊要求】(必须优先满足)：\n{current_req}"
    if ref_temp:
        inst += f"\n\n【参考经验模版】(请参考此模版的排版结构、大纲层级和语言风格进行内容填充)：\n{ref_temp}"
    return inst

# 供下拉框使用的选项列表
tpl_options = ["(不使用模版)"] + list(st.session_state.templates.keys())

# 封装列内部的 UI 逻辑
def render_action_column(col, title, action_key, is_primary=False):
    with col:
        # 1. 核心触发按钮
        btn_clicked = st.button(title, use_container_width=True, type="primary" if is_primary else "secondary")
        
        # 2. 模版选择下拉框 (置于按钮下方)
        selected_tpl = st.selectbox(
            f"👇 为【{title.split(' ')[1]}】配置模版", 
            options=tpl_options, 
            key=f"sel_{action_key}",
            label_visibility="collapsed"
        )
        
        # 3. 删除按钮 (仅当选中某模版时显现)
        if selected_tpl != "(不使用模版)":
            if st.button(f"🗑️ 删除该模版", key=f"del_{action_key}", help="从系统中永久删除此模版"):
                del st.session_state.templates[selected_tpl]
                save_templates(st.session_state.templates)
                st.rerun() # 立即刷新 UI
                
        return btn_clicked, selected_tpl

# 渲染 4 个按钮列并获取状态
c1_btn, c1_tpl = render_action_column(col_btn1, "🤝 外部会谈纪要", "btn1")
c2_btn, c2_tpl = render_action_column(col_btn2, "📋 内部会议纪要", "btn2")
c3_btn, c3_tpl = render_action_column(col_btn3, "📊 日常运作纪要", "btn3")
c4_btn, c4_tpl = render_action_column(col_btn4, "🚀 自由自定义", "btn4")

# 逻辑分发
if c1_btn:
    r_temp = st.session_state.templates.get(c1_tpl, "") if c1_tpl != "(不使用模版)" else ""
    active_instruction = build_final_prompt(PROMPT_CLIENT_MEETING, custom_req, r_temp)
    action_name = "外部会谈纪要"

elif c2_btn:
    r_temp = st.session_state.templates.get(c2_tpl, "") if c2_tpl != "(不使用模版)" else ""
    active_instruction = build_final_prompt(PROMPT_INTERNAL_MEETING, custom_req, r_temp)
    action_name = "内部会议纪要"

elif c3_btn:
    r_temp = st.session_state.templates.get(c3_tpl, "") if c3_tpl != "(不使用模版)" else ""
    active_instruction = build_final_prompt(PROMPT_OPERATIONAL, custom_req, r_temp)
    action_name = "日常运作纪要"

elif c4_btn:
    r_temp = st.session_state.templates.get(c4_tpl, "") if c4_tpl != "(不使用模版)" else ""
    base_inst = ""
    if not custom_req and not r_temp:
        base_inst = COPYWRITING_DEFAULT_REQ
    active_instruction = build_final_prompt(base_inst, custom_req, r_temp)
    action_name = "自定义排版"

# ==========================================
# 3. 核心生成逻辑与数据预处理 (原汁原味保留)
# ==========================================
if active_instruction:
    # 1. 拼接文本
    file_content = ""
    if uploaded_files:
        for file in uploaded_files:
            file_content += f"\n\n--- 【文件素材: {file.name}】 ---\n"
            file_content += file.getvalue().decode("utf-8", errors='ignore')
            
    raw_text = manual_text.strip() + "\n" + file_content.strip()

    if not raw_text.strip():
        st.warning("⚠️ 请输入需要整理的原始素材，或上传相关文件！")
        st.stop()

    # 2. 清理时间戳
    if clean_timestamps:
        raw_text = re.sub(r'\[?\b\d{1,2}:\d{2}(:\d{2})?(\.\d{1,3})?\b\]?', '', raw_text)
        raw_text = re.sub(r'\n\s*\n', '\n\n', raw_text)

    # 3. 逻辑重组
    final_instruction = active_instruction
    if reorder_logic:
        final_instruction += "\n\n【特殊处理要求】：注意，提供的素材可能是碎片化或乱序拼接的（如不同人员发言错位、A段B段顺序颠倒）。请在正式整理前，务必先通过理解上下文理顺正确的时间线和逻辑主线，拼贴重组后，再进行输出。"

    # 4. 并发压缩
    if enable_compression and len(raw_text) > 40000:
        st.divider()
        st.info("⚠️ 检测到素材内容达到超长规模，正在启动【长文本并发分片压缩】流程...")
        
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=25000, chunk_overlap=3000)
        chunks = text_splitter.split_text(raw_text)
        
        compress_llm = ChatOpenAI(
            model=model_a, 
            api_key=settings.API_KEY, 
            base_url=settings.API_BASE, 
            temperature=0.1,
            model_kwargs={"request_timeout": 180} 
        )
        
        progress_bar = st.progress(0, text=f"准备处理 {len(chunks)} 个文本块 (为防超时，限制并发数)...")
        compressed_chunks = [""] * len(chunks)
        
        def process_chunk(index, chunk_text):
            chunk_prompt = f"请提取以下文本的核心信息、关键数据和有效结论，去除寒暄和废话，必须保留核心业务逻辑和数据。文本：\n{chunk_text}"
            max_retries = 3 
            for attempt in range(max_retries):
                try:
                    res = compress_llm.invoke(chunk_prompt)
                    return index, f"\n\n【分段 {index+1} 核心提炼】:\n{res.content}"
                except Exception as e:
                    error_msg = str(e)
                    if "504" in error_msg or "Timeout" in error_msg or "502" in error_msg:
                        if attempt < max_retries - 1:
                            time.sleep(2 ** (attempt + 1))
                            continue 
                    return index, f"\n\n【分段 {index+1} 压缩失败 (报错: {error_msg[:50]}...)，降级保留原文】:\n{chunk_text}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(process_chunk, i, chunk) for i, chunk in enumerate(chunks)]
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                progress_bar.progress(completed / len(chunks), text=f"🚀 提炼中... (已完成 {completed}/{len(chunks)} 块)")
                idx, result_text = future.result()
                compressed_chunks[idx] = result_text

        raw_text = "".join(compressed_chunks)
        log_usage("长文本预处理并发压缩", model_a, int(len(raw_text) * 0.8))
        st.success("✅ 前置压缩完成！准备进入最终排版环节...")

    # ==========================================
    # 5. 双模型对决
    # ==========================================
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", COPYWRITING_SYSTEM_PROMPT),
        ("user", "【整理要求】\n{req}\n\n【原始素材】\n{text}")
    ])

    st.divider()
    st.markdown(f"### 🤖 正在为您进行 {action_name} A/B 方案生成...")
    col_a, col_b = st.columns(2)

    def run_and_stream(model_name, container, title_prefix, color_emoji):
        with container:
            with st.container(border=True):
                st.markdown(f"### {color_emoji} {title_prefix}")
                st.caption(f"🧠 驱动模型: `{model_name}`")
                st.markdown("---") 
                
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
                        for chunk in (prompt_template | llm).stream({"req": final_instruction, "text": raw_text}):
                            full_text += chunk.content
                            placeholder.markdown(full_text + " ▌")
                        placeholder.markdown(full_text)
                        
                        tokens = cb.total_tokens if cb.total_tokens > 0 else int((len(raw_text) + len(final_instruction) + len(full_text)) * 1.2)
                        log_usage("文案双核整理", model_name, tokens)
                        
                        st.markdown("---")
                        st.download_button(
                            label=f"📥 采纳并下载 {title_prefix}", 
                            data=full_text, 
                            file_name=f"{action_name}_{title_prefix}.md", 
                            mime="text/markdown", 
                            key=f"dl_{title_prefix}_{model_name}",
                            use_container_width=True
                        )
                    except Exception as e:
                        placeholder.error(f"❌ 生成失败或响应超时:\n {e}")

    with st.spinner(f"正在调动 {model_a} 撰写方案 A ..."):
        run_and_stream(model_a, col_a, "方案 A", "🔵")
        
    with st.spinner(f"正在调动 {model_b} 撰写方案 B ..."):
        run_and_stream(model_b, col_b, "方案 B", "🔴")
        
    st.balloons()
    st.success("✅ 双方案生成完毕！请对比左右两侧的排版与语感，挑选您最满意的一版。")