# pages/11_🎙️_11语音纪要.py
import streamlit as st
import os
import tempfile

# 💡 方案一：开启国内镜像加速兜底
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import core.paths
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import SPEAKER_DIARIZATION_PROMPT

st.set_page_config(page_title="语音纪要双核提炼", page_icon="🎙️", layout="wide")

st.title("🎙️ 本地极速转写与双核纪要提炼")
st.markdown("采用 **Faster-Whisper** 在本地极速、安全地将语音转为文字，随后利用 **双大模型** 通过上下文语义智能区分说话人，并提炼会议纪要。")

# ==========================================
# 1. 侧边栏：引擎与模型配置
# ==========================================
with st.sidebar:
    st.header("⚙️ 阶段一：本地语音引擎")
    st.info("💡 模型越大越准，但所需内存和时间越多。日常推荐 small 或 base。")
    whisper_size = st.selectbox("本地 Whisper 精度", ["tiny", "base", "small", "medium", "large-v3"], index=2)
    compute_device = st.selectbox("计算设备 (Device)", ["cpu", "cuda"], index=0, help="如果你的电脑有 N 卡并配置了环境，请选 cuda 获得10倍加速！")
    
    st.markdown("---")
    st.header("⚙️ 阶段二：双核纪要引擎")
    model_a = st.text_input("方案 A 执行模型", value=settings.MODEL_TEXT or "deepseek-v3-0324")
    model_b = st.text_input("方案 B 执行模型", value=settings.MODEL_RED or "qwen2.5-72b-instruct")

# 初始化 Session State
if "raw_transcript" not in st.session_state:
    st.session_state.raw_transcript = ""

# ==========================================
# 2. 阶段一：音频上传与本地极速转写
# ==========================================
st.markdown("### 📥 第一步：音频载入与转写")
uploaded_audio = st.file_uploader(
    "上传会议录音、访谈或语音备忘录 (支持 mp3, wav, m4a 等)", 
    type=['mp3', 'wav', 'm4a', 'flac', 'webm', 'ogg']
)

if uploaded_audio:
    st.audio(uploaded_audio)
    
    if st.button("🚀 启动本地极速转写 (纯本地执行，数据不泄露)", type="primary"):
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            st.error("🚨 缺少核心依赖！请在终端运行: `pip install faster-whisper`")
            st.stop()
            
        with st.status("🎧 正在加载本地听写引擎并扫描音频...", expanded=True) as status:
            tmp_path = ""
            try:
                ext = uploaded_audio.name.split('.')[-1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp_file:
                    tmp_file.write(uploaded_audio.getvalue())
                    tmp_path = tmp_file.name
                
                # 👇👇👇 核心修复：内网智能离线加载逻辑 👇👇👇
                model_identifier = whisper_size
                # 尝试去 global_data/models/faster-whisper-{size} 寻找离线模型
                local_model_dir = os.path.join(str(core.paths.GLOBAL_DATA_DIR), "models", f"faster-whisper-{whisper_size}")
                
                if os.path.exists(local_model_dir) and os.listdir(local_model_dir):
                    st.write(f"🔄 发现内网离线模型仓库，正在从本地加载 `{whisper_size}` ...")
                    model_identifier = local_model_dir # 如果有本地文件夹，直接传绝对路径给它！
                else:
                    st.write(f"🔄 本地未找到离线文件，正在尝试从镜像站下载 `{whisper_size}` 模型...")
                
                # 初始化模型 (不管是字符串名字还是本地路径，WhisperModel 都能自动识别)
                model = WhisperModel(model_identifier, device=compute_device, compute_type="int8")
                # 👆👆👆 修复结束 👆👆👆
                
                st.write("🏃‍♂️ 开始执行语音识别 (已开启 VAD 内存防爆机制)，请稍候...")
                # 加上 vad_filter=True，彻底解决长音频内存溢出问题
                segments, info = model.transcribe(tmp_path, beam_size=5, vad_filter=True)
                
                full_text = ""
                progress_bar = st.progress(0)
                for segment in segments:
                    full_text += segment.text + " "
                    progress_bar.progress(min(segment.end / info.duration, 1.0))
                
                st.session_state.raw_transcript = full_text.strip()
                status.update(label="✅ 本地语音转写完美完成！", state="complete", expanded=False)
                
            except Exception as e:
                status.update(label="❌ 语音转写发生致命错误", state="error", expanded=True)
                st.error(f"详细报错: {e}")
                st.info("💡 如果是网络报错，请按照代码里的注释，提前在有网的电脑上下载好模型放入 `global_data/models/` 目录中。")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)

# ==========================================
# 3. 阶段二：人工核对与双核智能纪要 (A/B Test) (后续保持不变)
# ==========================================
if st.session_state.raw_transcript:
    st.divider()
    st.markdown("### 📝 第二步：核对底稿与智能梳理")
    st.caption("以下是 AI 听写的原始底稿。您可以在这里手动修正错别字，随后大模型将根据此底稿自动**区分说话人**并生成纪要。")
    
    edited_text = st.text_area("✍️ 原始语音底稿 (可修改)", value=st.session_state.raw_transcript, height=200)
    
    if st.button("⚔️ 启动双核纪要提炼 (含智能区分说话人)", type="primary", use_container_width=True):
        if not edited_text.strip():
            st.warning("底稿为空，无法生成！")
            st.stop()
            
        prompt_template = ChatPromptTemplate.from_template(SPEAKER_DIARIZATION_PROMPT)
        
        st.markdown("---")
        col_a, col_b = st.columns(2)
        
        def run_summary(model_name, container, title_prefix, color_emoji):
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
                        temperature=0.2, 
                        model_kwargs={"stream_options": {"include_usage": True}} 
                    )
                    
                    full_summary = ""
                    with get_openai_callback() as cb:
                        try:
                            for chunk in (prompt_template | llm).stream({"text": edited_text}):
                                full_summary += chunk.content
                                placeholder.markdown(full_summary + " ▌")
                            placeholder.markdown(full_summary)
                            
                            tokens = cb.total_tokens
                            if tokens == 0:
                                tokens = int((len(edited_text) + len(full_summary)) * 1.2)
                            log_usage("语音纪要(大模型提炼)", model_name, tokens)
                            
                            st.markdown("---")
                            st.download_button(
                                label=f"📥 采纳并下载 {title_prefix}", 
                                data=full_summary, 
                                file_name=f"{title_prefix}_会议纪要.md", 
                                mime="text/markdown", 
                                key=f"dl_{title_prefix}",
                                use_container_width=True
                            )
                            
                        except Exception as e:
                            placeholder.error(f"❌ 生成失败:\n {e}")

        with st.spinner(f"正在调动 {model_a} 分析语境并重构纪要 ..."):
            run_summary(model_a, col_a, "方案 A", "🔵")
            
        with st.spinner(f"正在调动 {model_b} 分析语境并重构纪要 ..."):
            run_summary(model_b, col_b, "方案 B", "🔴")
            
        st.balloons()
        st.success("✅ 智能重构完毕！请对比左右两侧对“说话人”的拆解是否准确，并挑选最满意的一版纪要。")