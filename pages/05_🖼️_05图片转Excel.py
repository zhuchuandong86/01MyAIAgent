# pages/04_🖼️_图片转Excel.py
import os
import io
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
import core.paths
from modules.img2excel.core import process_image_to_df

# 加载全局环境变量
load_dotenv(core.paths.ENV_FILE)
API_KEY = os.getenv("INTERNAL_API_KEY")
API_BASE = os.getenv("INTERNAL_API_BASE")

# --- 从环境变量读取模型配置 ---
MODEL_VISION = os.getenv("MODEL_VISION")
MODEL_VISION_BLUE = os.getenv("MODEL_VISION_Blue", "").strip()
MODEL_VISION_JUDGE = os.getenv("MODEL_VISION_Judge", "").strip()

st.set_page_config(page_title="图片转Excel", page_icon="🖼️", layout="wide")
st.title("🖼️ 智能 OCR：图片提取转 Excel")
st.markdown("上传含有表格的截图或照片，支持**多选**和**Ctrl+V直接粘贴**，AI 将自动提取并允许您下载为标准 Excel 文件。")

# ==========================================
# ⚙️ 新增：提取模式选择 (简单 vs 专业)
# ==========================================
mode = st.radio(
    "⚙️ 请选择提取模式",
    options=[
        "🟢 简单模式：极速单模型提取 (省时、省Token，适合清晰简单的表格)", 
        "🔥 专业模式：多模型交叉校验 (耗时、高Token，适合畸变、模糊、复杂的表格)"
    ],
    horizontal=False
)

# 根据用户选择动态组装模型列表
if "简单模式" in mode:
    active_extract_models = [MODEL_VISION]
    active_reviewer_model = None
    st.caption(f"💡 当前生效：极速提取引擎 (`{MODEL_VISION}`)")
else:
    active_extract_models = [MODEL_VISION]
    if MODEL_VISION_BLUE:
        active_extract_models.append(MODEL_VISION_BLUE)
    active_reviewer_model = MODEL_VISION_JUDGE if MODEL_VISION_JUDGE else None
    
    if len(active_extract_models) > 1 or active_reviewer_model:
        st.caption(f"💡 当前生效：多核交叉校验引擎 (提取: `{', '.join(active_extract_models)}` | 审阅: `{active_reviewer_model or active_extract_models[0]}`)")
    else:
        st.caption(f"⚠️ 当前生效：单模型提取 (`{MODEL_VISION}`) —— 注: 您未在环境变量配置蓝军或审阅模型，已自动降级。")

st.divider()

# 左侧上传，右侧预览
col1, col2 = st.columns([1, 1])

with col1:
    uploaded_files = st.file_uploader(
        "📂 上传/粘贴图片 (支持多选及快捷键粘贴)", 
        type=['png', 'jpg', 'jpeg'], 
        accept_multiple_files=True
    )

with col2:
    if uploaded_files:
        st.write(f"已加载 {len(uploaded_files)} 张图片：")
        preview_cols = st.columns(min(len(uploaded_files), 3))
        for i, file in enumerate(uploaded_files):
            with preview_cols[i % 3]:
                st.image(file, caption=file.name, use_container_width=True)

st.divider()

# 执行逻辑
if uploaded_files:
    if st.button("🚀 开始批量提取表格数据", type="primary", use_container_width=True):
        if not API_KEY:
            st.error("缺失 API KEY 配置，请检查根目录的 .env 文件！")
            st.stop()
            
        all_dfs = []
        all_mds = []
        total_files = len(uploaded_files)
        
        # 使用 st.status 创建一个可折叠的“执行状态面板”
        with st.status("🤖 视觉模型正在扫描并提取数据...", expanded=True) as status:
            progress_bar = st.progress(0)
            
            # 用于记录失败的文件
            failed_files = []
            
            for idx, uploaded_file in enumerate(uploaded_files):
                st.write(f"🔄 正在处理第 {idx+1}/{total_files} 张图片: `{uploaded_file.name}` ...")
                
                # 👇 核心修改：将 try-except 放进循环内部，单张失败不导致整体崩溃
                try:
                    # 传入用户动态选择的 active_extract_models
                    df, raw_md = process_image_to_df(
                        image_bytes=uploaded_file.getvalue(), 
                        api_key=API_KEY, 
                        api_base=API_BASE, 
                        extract_models=active_extract_models,
                        reviewer_model=active_reviewer_model
                    )
                    
                    all_dfs.append(df)
                    all_mds.append(f"### {uploaded_file.name} 提取结果 ###\n{raw_md}")
                    st.write(f"✅ `{uploaded_file.name}` 处理完成！")
                    
                except Exception as e:
                    # 捕获失败，记录日志，但让程序继续处理下一张图片
                    st.error(f"❌ `{uploaded_file.name}` 提取失败: {e}")
                    failed_files.append(uploaded_file.name)
                
                # 无论成功失败，都推进进度条
                progress_bar.progress((idx + 1) / total_files)
            
            # 循环结束后，根据结果更新顶部状态面板
            if failed_files:
                if len(failed_files) == total_files:
                    status.update(label="❌ 全部图片提取失败，请检查网络或模型状态", state="error", expanded=True)
                else:
                    status.update(label=f"⚠️ 部分提取完成 (成功 {len(all_dfs)} 张，失败 {len(failed_files)} 张)", state="complete", expanded=True)
            else:
                status.update(label="🎉 全部图片提取成功！", state="complete", expanded=False)
        
        # 数据展示与下载区
        if all_dfs:
            st.success("✅ 数据提取与整合完毕！预览如下：")
            
            final_df = pd.concat(all_dfs, ignore_index=True)
            st.dataframe(final_df, use_container_width=True)
            
            excel_buffer = io.BytesIO()
            final_df.to_excel(excel_buffer, index=False)
            excel_data = excel_buffer.getvalue()
            
            col_btn, _ = st.columns([1, 3])
            with col_btn:
                st.download_button(
                    label="📥 一键下载合并后的 Excel",
                    data=excel_data,
                    file_name="批量表格提取结果.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )
                
            with st.expander("🛠️ 查看大模型原始 Markdown 返回值 (含降级提示)"):
                st.markdown("\n\n---\n\n".join(all_mds))