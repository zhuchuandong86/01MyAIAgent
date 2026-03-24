import streamlit as st
import os
import time
from datetime import datetime
import shutil  # 【新增】：用于强制清理垃圾文件

# 【必加】：引入全局路径管家
import core.paths

# ==========================================
# 1. 核心路径防呆设计 & 缓存目录
# ==========================================
OUTPUT_DIR = str(core.paths.GLOBAL_DATA_DIR)
UPLOAD_DIR = str(core.paths.UPLOAD_DIR)
TEMP_IMG_DIR = os.path.join(OUTPUT_DIR, "pdf_temp_images")
MD_CACHE_DIR = os.path.join(OUTPUT_DIR, "md_cache") 

os.makedirs(TEMP_IMG_DIR, exist_ok=True)
os.makedirs(MD_CACHE_DIR, exist_ok=True)

from modules.multi_compare.renderers.excel_builder import export_tables_to_excel
from modules.multi_compare.utils import natural_sort_key
from core.parsers.document_engine import convert_pdf_to_images
from modules.multi_compare.main import process_single_page, generate_final_summary
from modules.multi_compare.renderers.my_html_renderer import export_to_html
from modules.multi_compare.main_compare import generate_compare_summary
from modules.multi_compare.main_trend import generate_trend_summary

# ==========================================
# 2. 页面基本设置 & CSS
# ==========================================
st.set_page_config(page_title="AI 材料深度解读工作台", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stMarkdown p { font-size: 16px !important; line-height: 1.7 !important; margin-bottom: 12px !important; }
    .stMarkdown li { margin-bottom: 6px !important; }
    .stMarkdown li > p { margin-bottom: 0px !important; margin-top: 0px !important; }
    .stMarkdown ul, .stMarkdown ol { margin-bottom: 20px !important; padding-left: 28px !important; }
    .stMarkdown h2 { font-size: 22px !important; color: #1a202c !important; border-bottom: 2px solid #ebf4ff !important; padding-bottom: 8px !important; margin-top: 35px !important; margin-bottom: 16px !important; }
    .stMarkdown h3 { font-size: 18px !important; color: #2b6cb0 !important; margin-top: 24px !important; margin-bottom: 12px !important; font-weight: 600 !important; }
    .stMarkdown strong { color: #111827 !important; }
    </style>
    """, unsafe_allow_html=True)

with st.sidebar:
    # st.image("https://img.icons8.com/color/96/000000/combo-chart--v1.png", width=60)
    # st.title("系统面板")
    # st.markdown("---")
    max_pages = st.number_input("原文件最大解析页数 (防超载)", min_value=1, max_value=500, value=100)
    
    st.markdown("---")
    use_cache = st.checkbox("⚡ 启用极速解析缓存\n\n(若勾选：曾提取过的PDF/图片将直接复用底层MD缓存。)", value=True)
    
    # st.markdown("---")
    # st.success(f"📁 **数据存储路径已锁定:**\n\n`{OUTPUT_DIR}`")

st.markdown("### 📊 AI 材料深度解读工作台")
st.markdown("基于多模态大模型，支持上传 PDF、图片、MD 混合格式，进行单文档解析、多文件横评与纵向趋势推演。")

# ==========================================
# 【核心升级】：带智能缓存与“阅后即焚”的文件解析引擎
# ==========================================
def parse_files_to_text_dict(uploaded_files, max_pages, ui_container, enable_cache):
    """智能分拣器：判断缓存 -> 解析 -> 保存MD缓存 -> 【彻底清理临时图片和原文件】"""
    result_dict = {}
    for file in uploaded_files:
        ext = os.path.splitext(file.name)[1].lower()
        base_name = os.path.splitext(file.name)[0]
        
        if ext == '.md':
            ui_container.info(f"📄 秒读 Markdown 文本: {file.name}")
            result_dict[base_name] = file.getvalue().decode("utf-8")
        else:
            cache_file_path = os.path.join(MD_CACHE_DIR, f"{base_name}.md")
            if enable_cache and os.path.exists(cache_file_path):
                ui_container.success(f"⚡ 命中缓存池！已极速加载历史解析底稿: {base_name}")
                with open(cache_file_path, "r", encoding="utf-8") as f:
                    result_dict[base_name] = f.read()
                continue
                
            ui_container.warning(f"👁️ 正在激活视觉引擎，逐页提取新文件: {file.name} ...")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_filename = f"{timestamp}_{file.name}"
            file_path = os.path.join(UPLOAD_DIR, safe_filename)
            
            with open(file_path, "wb") as f: f.write(file.getbuffer())
                
            image_paths = []
            if ext == '.pdf':
                pdf_imgs = convert_pdf_to_images(file_path, TEMP_IMG_DIR, max_pages)
                image_paths.extend(pdf_imgs)
            else:
                image_paths.append(file_path)
                
            if max_pages: image_paths = image_paths[:max_pages]
            total_pages = len(image_paths)
            
            if total_pages == 0:
                ui_container.error(f"❌ {file.name} 提取失败！")
                continue
                
            all_content = ""
            progress_bar = ui_container.progress(0)
            
            for i, path in enumerate(image_paths):
                res = process_single_page(path, i + 1)
                all_content += f"\n\n> 📁 **[来源文件：{base_name}]** - 第 {i+1} 页提取内容\n{res}\n"
                progress_bar.progress((i + 1) / total_pages)
                
            progress_bar.empty()
            
            # 1. 提取成功，存入极其轻量的 MD 缓存
            with open(cache_file_path, "w", encoding="utf-8") as f:
                f.write(all_content)
                
            # 2. 👇【核心新增】：阅后即焚，立刻清理临时大文件！
            try:
                # 删掉上传的原 PDF/图片
                if os.path.exists(file_path): 
                    os.remove(file_path)
                # 删掉 PDF 拆解出来的所有分页高清大图
                for img_path in image_paths:
                    if os.path.exists(img_path):
                        os.remove(img_path)
                ui_container.success(f"✅ {file.name} 解析完成，已存入缓存并自动销毁了临时大文件！")
            except Exception as e:
                ui_container.warning(f"✅ {file.name} 解析完成，但清理临时文件时遇到小问题: {e}")
                
            result_dict[base_name] = all_content
            
    return result_dict

# ==========================================
# 3. 终极工作流（三大清爽标签页设计）
# ==========================================
tab1, tab2, tab3 = st.tabs([
    "🚀 单份文档智能解析", 
    "⚔️ 多公司竞品横评",
    "📈 历史纵向趋势推演"
])

# ---------------------------------------------------------
# 工作流 A：单份文档智能解析
# ---------------------------------------------------------
with tab1:
    st.markdown("###### 📥 上传文档 (支持混传 PDF / JPG / MD)")
    uploaded_files = st.file_uploader("请拖拽文件至此", type=["pdf", "png", "jpg", "jpeg", "md"], accept_multiple_files=True, key="tab1_uploader")
    user_requirement_full = st.text_area("🎯 自定义分析侧重点 (选填)", placeholder="例如：请重点提取各省份的 ARPU 值对比...", height=100)

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1: btn_extract_only = st.button("📝 仅提取数据底稿 (生成 MD)", use_container_width=True)
    with col_btn2: btn_full_pipeline = st.button("🚀 开始全流程深度研判", type="primary", use_container_width=True)

    if btn_extract_only or btn_full_pipeline:
        if not uploaded_files:
            st.warning("⚠️ 请先上传文件！")
            st.stop()
            
        status_container = st.container()
        text_dict = parse_files_to_text_dict(uploaded_files, max_pages, status_container, use_cache)
        
        all_content = "\n".join(text_dict.values())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(uploaded_files[0].name)[0] if len(uploaded_files) == 1 else "多文件合并"
        
        if btn_extract_only:
            file_name_md = f"{base_name}_底稿_{timestamp}.md"
            temp_md_path = os.path.join(OUTPUT_DIR, file_name_md)
            with open(temp_md_path, "w", encoding="utf-8") as f: f.write(all_content)
            st.info("💡 提取完毕！您可以直接下载该 Markdown 文件用于其他平台的预处理。")
            with open(temp_md_path, "r", encoding="utf-8") as f:
                st.download_button("⬇️ 一键下载 MD 数据底稿", data=f, file_name=file_name_md, mime="text/markdown", type="primary")
            st.stop()
            
        if btn_full_pipeline:
            st.markdown("###### 🧠 深度研判报告生成中")
            with st.spinner('红蓝军对抗与财务推演中...'):
                summary = generate_final_summary(all_content, user_requirement_full)
                
            st.success("🎉 研判报告已生成！")
            st.markdown("---")
            st.markdown(summary, unsafe_allow_html=True)
            
            final_md_content = f"# AI 深度洞察与业务研判报告\n\n{summary}\n\n---\n## 📚 附录：原始底层数据\n<details markdown=\"1\">\n<summary>👉 点击展开查看各页原始核心数据</summary>\n\n{all_content}\n</details>"
            
            md_name = f"{base_name}_研判报告_{timestamp}.md"
            html_name = f"{base_name}_网页版_{timestamp}.html"
            excel_name = f"{base_name}_数据表_{timestamp}.xlsx"
            
            final_md_file = os.path.join(OUTPUT_DIR, md_name)
            final_html_file = os.path.join(OUTPUT_DIR, html_name)
            final_excel_file = os.path.join(OUTPUT_DIR, excel_name)
            
            with open(final_md_file, "w", encoding="utf-8") as f: f.write(final_md_content)
            export_to_html(final_md_content, final_html_file)
            has_excel = export_tables_to_excel(final_md_content, final_excel_file)
            
            st.markdown("### 💾 导出报告")
            cols = st.columns(3 if has_excel else 2)
            with cols[0]:
                with open(final_md_file, "r", encoding="utf-8") as f: st.download_button("⬇️ Markdown版", f, file_name=md_name)
            with cols[1]:
                with open(final_html_file, "r", encoding="utf-8") as f: st.download_button("🌐 HTML网页版", f, file_name=html_name)
            if has_excel:
                with cols[2]:
                    with open(final_excel_file, "rb") as f: st.download_button("📊 Excel数据表", f, file_name=excel_name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------------------------------------------------------
# 工作流 B：多公司竞品横评
# ---------------------------------------------------------
with tab2:
    st.markdown("###### ⚔️ 上传多家公司的报告 (支持混传 PDF / JPG / MD)")
    st.info("💡 提示：无论您传原文件还是MD底稿，请**直接用公司名称命名文件**（如：`中国移动.pdf`、`中国电信.md`）。")
    compare_files = st.file_uploader("批量拖拽多个公司的文件至此", type=["pdf", "png", "jpg", "jpeg", "md"], accept_multiple_files=True, key="tab2_uploader")
    
    if st.button("⚔️ 启动多 Agent 竞品横评", type="primary", key="btn_compare"):
        if not compare_files or len(compare_files) < 2:
            st.warning("⚠️ 进行横评至少需要上传 2 份不同公司的文件！")
            st.stop()
            
        status_container = st.container()
        company_dict = parse_files_to_text_dict(compare_files, max_pages, status_container, use_cache)
            
        st.markdown("###### 🧠 多模态竞品大脑生成中")
        with st.spinner('正在并行提纯各家数据，并由首席主编进行横向评测...'):
            compare_summary = generate_compare_summary(company_dict)
            
        st.success("🎉 竞品横评报告已生成！")
        st.markdown("---")
        st.markdown(compare_summary, unsafe_allow_html=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_md_content = f"# ⚔️ 行业竞品横向对比研判报告\n\n{compare_summary}"
        
        names = list(company_dict.keys())
        prefix = "vs".join(names[:3]) + ("等" if len(names)>3 else "")
        
        md_name = f"{prefix}_竞品横评_{timestamp}.md"
        html_name = f"{prefix}_竞品横评_{timestamp}.html"
        
        final_md_file = os.path.join(OUTPUT_DIR, md_name)
        final_html_file = os.path.join(OUTPUT_DIR, html_name)
        
        with open(final_md_file, "w", encoding="utf-8") as f: f.write(final_md_content)
        export_to_html(final_md_content, final_html_file)
        
        col1, col2 = st.columns(2)
        with col1:
            with open(final_md_file, "r", encoding="utf-8") as f: st.download_button("⬇️ 下载 Markdown 报告", f, file_name=md_name)
        with col2:
            with open(final_html_file, "r", encoding="utf-8") as f: st.download_button("🌐 下载 HTML 网页版", f, file_name=html_name)

# ---------------------------------------------------------
# 工作流 C：历史纵向趋势推演
# ---------------------------------------------------------
with tab3:
    st.markdown("###### 📈 上传连续多年的报告 (支持混传 PDF / JPG / MD)")
    st.info("💡 提示：无论您传原文件还是MD底稿，请**直接用年份命名文件**（如：`2021.pdf`、`2022.md`）。")
    trend_files = st.file_uploader("批量拖拽多年的文件至此", type=["pdf", "png", "jpg", "jpeg", "md"], accept_multiple_files=True, key="tab3_uploader")
    
    if st.button("📈 启动历史趋势推演", type="primary", key="btn_trend"):
        if not trend_files or len(trend_files) < 2:
            st.warning("⚠️ 进行趋势推演至少需要上传 2 个年份的文件！")
            st.stop()
            
        status_container = st.container()
        yearly_dict = parse_files_to_text_dict(trend_files, max_pages, status_container, use_cache)
            
        st.markdown("###### 🧠 历史趋势大脑生成中")
        with st.spinner('正在按时间轴梳理数据，推演企业生命周期...'):
            trend_summary = generate_trend_summary(yearly_dict)
            
        st.success("🎉 纵向战略演进报告已生成！")
        st.markdown("---")
        st.markdown(trend_summary, unsafe_allow_html=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_md_content = f"# 📈 企业纵向战略演进与周期复盘报告\n\n{trend_summary}"
        
        years = sorted(list(yearly_dict.keys()))
        prefix = f"{years[0]}至{years[-1]}年" if len(years) > 1 else years[0]
        
        md_name = f"{prefix}_演进趋势_{timestamp}.md"
        html_name = f"{prefix}_演进趋势_{timestamp}.html"
        
        final_md_file = os.path.join(OUTPUT_DIR, md_name)
        final_html_file = os.path.join(OUTPUT_DIR, html_name)
        
        with open(final_md_file, "w", encoding="utf-8") as f: f.write(final_md_content)
        export_to_html(final_md_content, final_html_file)
        
        col1, col2 = st.columns(2)
        with col1:
            with open(final_md_file, "r", encoding="utf-8") as f: st.download_button("⬇️ 下载 Markdown 报告", f, file_name=md_name)
        with col2:
            with open(final_html_file, "r", encoding="utf-8") as f: st.download_button("🌐 下载 HTML 网页版", f, file_name=html_name)
