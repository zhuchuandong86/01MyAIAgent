import streamlit as st
import os
import tempfile
import base64

# 开启国内镜像加速兜底
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 【核心引入】：统一配置与兵工厂
import core.paths
from core.settings import settings
from core.llm_factory import get_llm
from core.token_tracker import log_usage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import SPEAKER_DIARIZATION_PROMPT

st.set_page_config(page_title="语音纪要双核提炼", page_icon="🎙️", layout="wide")

st.title("🎙️ 智能语音纪要引擎")
st.markdown("支持 **本地 Faster-Whisper 转写 + 双大模型提炼** 的经典模式，与 **全模态端到端直连** 模式。")

# ==========================================
# 1. 侧边栏：引擎与模型配置
# ==========================================
with st.sidebar:
    st.header("⚙️ 引擎 1：本地语音识别")
    st.info("💡 经典瀑布流：先转成文本，再由大模型提炼。适合超长会议与普通大模型。")
    whisper_size = st.selectbox("本地 Whisper 精度", ["tiny", "base", "small", "medium", "large-v3"], index=2)
    compute_device = st.selectbox("计算设备 (Device)", ["cpu", "cuda"], index=0, help="如果有N卡并配置了环境，请选cuda！")
    
    st.markdown("---")
    st.header("⚙️ 引擎 2：文本双核纪要")
    # [优化] 使用统一 settings 兜底
    model_a = st.text_input("方案 A 执行模型", value=settings.MODEL_TEXT)
    model_b = st.text_input("方案 B 执行模型", value=settings.MODEL_RED)
    
    st.markdown("---")
    st.header("⚙️ 引擎 3：全模态端到端")
    st.info("💡 注意：前提是您的内网 API 网关必须支持以下配置的 Omni(音频) 模型，否则会报错。")
    model_omni = settings.MODEL_RTS

# 初始化 Session State
if "raw_transcript" not in st.session_state:
    st.session_state.raw_transcript = ""

# ==========================================
# 2. 音频上传与分支选择
# ==========================================
st.markdown("### 📥 第一步：音频载入")
uploaded_audio = st.file_uploader(
    "上传会议录音、访谈或语音备忘录 (支持 mp3, wav, m4a 等)", 
    type=['mp3', 'wav', 'm4a', 'flac', 'webm', 'ogg']
)

if uploaded_audio:
    st.audio(uploaded_audio)
    col_route1, col_route2 = st.columns(2)
    
    # ---------------------------------------------------------
    # 路线 A：全模态直连 (Qwen2.5-Omni / GPT-4o-Audio)
    # ---------------------------------------------------------
    with col_route2:
        st.info("🟣 **端到端模式**：无需转文字，AI直接听音频。能够捕捉情绪和重叠对话。需网关支持。")
        if st.button("🎧 启动 Omni 全模态纪要", type="primary", use_container_width=True):
            st.divider()
            st.markdown("### 🟣 全模态纪要结果")
            
            with st.status(f"🎧 正在将音频发送至 `{model_omni}` ...", expanded=True) as status:
                try:
                    ext = uploaded_audio.name.split('.')[-1].lower()
                    audio_bytes = uploaded_audio.getvalue()
                    base64_audio = base64.b64encode(audio_bytes).decode('utf-8')
                    
                    message = HumanMessage(content=[
                        {
                            "type": "text", 
                            "text": "请听这段录音，直接整理成详细的会议纪要，并根据声音特征准确区分说话人。"
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64_audio,
                                "format": ext if ext in ["wav", "mp3"] else "mp3"
                            }
                        }
                    ])
                    
                    # [核心优化] 使用统一的兵工厂
                    llm_omni = get_llm(model_name=model_omni, temperature=0.2, streaming=True)
                    
                    status.update(label="🧠 Omni 模型正在思考与输出...", state="running")
                    placeholder_omni = st.empty()
                    full_omni_summary = ""
                    
                    with get_openai_callback() as cb:
                        count = 0
                        for chunk in llm_omni.stream([message]):
                            if chunk.content:
                                full_omni_summary += chunk.content
                                count += 1
                                # [核心修复] 加入节流器防浏览器崩溃
                                if count % 8 == 0:
                                    placeholder_omni.markdown(full_omni_summary + " ▌")
                        placeholder_omni.markdown(full_omni_summary)
                        
                        tokens = cb.total_tokens if cb.total_tokens > 0 else int(len(full_omni_summary) * 1.5)
                        log_usage("全模态语音纪要", model_omni, tokens)
                            
                    status.update(label="✅ 全模态端到端处理完成！", state="complete", expanded=False)
                    st.balloons()
                    
                    st.download_button(
                        label="📥 下载 Omni 会议纪要", 
                        data=full_omni_summary, 
                        file_name="Omni_会议纪要.md", 
                        mime="text/markdown",
                        use_container_width=True
                    )
                    
                except Exception as e:
                    status.update(label="❌ 全模态调用发生错误", state="error")
                    st.error(f"⚠️ 调用失败！请确认您的 API 网关中是否真实配置了该音频模型。\n详细报错: \n{e}")
                    
            st.stop() 

    # ---------------------------------------------------------
    # 路线 B：经典本地转写 (Faster-Whisper)
    # ---------------------------------------------------------
    with col_route1:
        st.info("🔵 **经典瀑布流 (推荐)**：纯本地极速提取文字底稿，不挑模型，可手动修改错别字后再双大模型提炼。")
        if st.button("🚀 启动本地极速转写底稿", use_container_width=True):
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
                    
                    model_identifier = whisper_size
                    local_model_dir = os.path.join(str(core.paths.GLOBAL_DATA_DIR), "models", f"faster-whisper-{whisper_size}")
                    
                    if os.path.exists(local_model_dir) and os.listdir(local_model_dir):
                        st.write(f"🔄 从本地硬盘加载 `{whisper_size}` 模型...")
                        model_identifier = local_model_dir 
                    else:
                        st.write(f"🔄 尝试从镜像站下载 `{whisper_size}` 模型...")
                    
                    model = WhisperModel(model_identifier, device=compute_device, compute_type="int8")
                    
                    st.write("🏃‍♂️ 开始执行语音识别 (已开启 VAD 防爆内存)...")
                    segments, info = model.transcribe(tmp_path, beam_size=5, vad_filter=True)
                    
                    full_text = ""
                    progress_bar = st.progress(0)
                    for segment in segments:
                        full_text += segment.text + " "
                        progress_bar.progress(min(segment.end / info.duration, 1.0))
                    
                    st.session_state.raw_transcript = full_text.strip()
                    status.update(label="✅ 本地语音转写完成！", state="complete", expanded=False)
                    
                except Exception as e:
                    status.update(label="❌ 语音转写发生错误", state="error", expanded=True)
                    st.error(f"详细报错: {e}")
                finally:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)

# ==========================================
# 3. 经典模式的第二阶段：核对与双核智能纪要
# ==========================================
if st.session_state.raw_transcript:
    st.divider()
    st.markdown("### 📝 第二步：核对底稿与双核智能梳理")
    st.caption("以下是 AI 听写的原始底稿。您可以在这里手动修正错别字，随后大模型将根据此底稿自动**区分说话人**并生成标准纪要。")
    
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
                    
                    # [核心优化] 使用统一兵工厂
                    llm = get_llm(model_name=model_name, temperature=0.2, streaming=True)
                    
                    full_summary = ""
                    with get_openai_callback() as cb:
                        try:
                            count = 0
                            for chunk in (prompt_template | llm).stream({"text": edited_text}):
                                if chunk.content:
                                    full_summary += chunk.content
                                    count += 1
                                    # [核心修复] 渲染节流防假死
                                    if count % 8 == 0:
                                        placeholder.markdown(full_summary + " ▌")
                            placeholder.markdown(full_summary)
                            
                            tokens = cb.total_tokens if cb.total_tokens > 0 else int((len(edited_text) + len(full_summary)) * 1.2)
                            log_usage("文本纪要提炼", model_name, tokens)
                            
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