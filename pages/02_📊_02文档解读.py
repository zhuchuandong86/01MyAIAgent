import streamlit as st
import os
import time
from datetime import datetime
import shutil  
import hashlib 

import core.paths
from core.settings import settings

from langchain_openai import OpenAIEmbeddings, ChatOpenAI 
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

# ==========================================
# 1. 核心路径防呆设计 & 缓存目录
# ==========================================
OUTPUT_DIR = str(core.paths.GLOBAL_DATA_DIR)
UPLOAD_DIR = str(core.paths.UPLOAD_DIR)
TEMP_IMG_DIR = os.path.join(OUTPUT_DIR, "pdf_temp_images")
MD_CACHE_DIR = os.path.join(OUTPUT_DIR, "md_cache") 

TEMPLATE_MD_DIR = os.path.join(OUTPUT_DIR, "templates_md")
TEMPLATE_DB_DIR = os.path.join(OUTPUT_DIR, "template_faiss")

os.makedirs(TEMP_IMG_DIR, exist_ok=True)
os.makedirs(MD_CACHE_DIR, exist_ok=True)
os.makedirs(TEMPLATE_MD_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DB_DIR, exist_ok=True)

from modules.multi_compare.renderers.excel_builder import export_tables_to_excel
from modules.multi_compare.utils import natural_sort_key
from core.parsers.document_engine import convert_pdf_to_images
from modules.multi_compare.main import process_single_page, generate_final_summary
from modules.multi_compare.renderers.my_html_renderer import export_to_html
from modules.multi_compare.main_compare import generate_compare_summary
from modules.multi_compare.main_trend import generate_trend_summary

# ==========================================
# 🌟 全局公共组件：经验匹配与主编大脑
# ==========================================
def get_embeddings():
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL, 
        api_key=settings.API_KEY,
        base_url=settings.API_BASE,
        check_embedding_ctx_length=False
    )

def get_available_templates():
    return [f for f in os.listdir(TEMPLATE_MD_DIR) if f.endswith('.md')]

def get_style_templates(query_text, selected_strategy, status_ui):
    """将冗长的 LLM 选版逻辑封装为清爽的工具函数，供三大工作流复用"""
    templates_to_inject = []
    ai_thinking_log = None
    try:
        if selected_strategy.startswith("🤖"):
            embeddings = get_embeddings()
            db_path = os.path.join(TEMPLATE_DB_DIR, "index.faiss")
            if os.path.exists(db_path):
                vectorstore = FAISS.load_local(TEMPLATE_DB_DIR, embeddings, allow_dangerous_deserialization=True)
                status_ui.write("🔍 1. 底层 FAISS 引擎进行第一轮向量海选...")
                matched_docs = vectorstore.similarity_search(query_text[:1000], k=4)
                candidate_filenames = list(set([d.metadata.get("source") for d in matched_docs]))
                
                if candidate_filenames:
                    status_ui.write("🧠 2. 大模型主编正在评估候选模板并做出决断...")
                    llm_router = ChatOpenAI(
                        model=settings.MODEL_TEXT or "deepseek-v3-0324",
                        api_key=settings.API_KEY,
                        base_url=settings.API_BASE,
                        temperature=0.7 
                    )
                    
                    router_prompt = (
                        "你是一个眼光毒辣、极具【跨界思维】的顶级投行主编。有一份新文档需要解读，前500字如下：\n"
                        f"<new_doc>\n{query_text[:500]}\n</new_doc>\n\n"
                        f"系统基于向量检索初步捞出了以下历史优秀范例（候选池）：{candidate_filenames}\n\n"
                        "【主编选版核心铁律】：\n"
                        "1. 破除唯名字论：绝对不要因为新文档是“A公司”，就只选“A公司”的范例而排斥竞品。你要选的是【分析框架、排版结构、行文深度】最优秀的报告！跨公司的优秀范例往往能带来更好的结构启发。\n"
                        "2. 跨界与融合：我们需要你去参考“优秀怎么写”，而不是去“抄旧内容”。\n\n"
                        "请综合以上跨界思维，自主挑选最适合作为排版和行文参考的 2 到 3 个范例（必须参考多个，集百家之长）。\n"
                        "请严格按照以下格式输出你的思考过程和最终决定：\n"
                        "【主编思考】：(一句话简述理由，体现你的跨界融合与结构借鉴思维)\n"
                        "【最终选择】：(仅填入选中文件名，逗号分隔)"
                    )
                    
                    router_res = llm_router.invoke(router_prompt).content
                    ai_thinking_log = router_res 
                    
                    final_selected = [f for f in candidate_filenames if f in router_res]
                    if not final_selected:
                        final_selected = candidate_filenames[:2] 
                    
                    for fname in final_selected:
                        file_path = os.path.join(TEMPLATE_MD_DIR, fname)
                        if os.path.exists(file_path):
                            with open(file_path, "r", encoding="utf-8") as f:
                                templates_to_inject.append(f"【参考范例：{fname}】\n{f.read()[:2000]}")
                    status_ui.write(f"🎉 成功锁定最佳范例并准备融合！")
                else:
                    status_ui.write("ℹ️ 当前经验库为空，使用默认逻辑。")
            else:
                status_ui.write("ℹ️ 当前经验库未建立，使用默认逻辑。")
        else:
            file_path = os.path.join(TEMPLATE_MD_DIR, selected_strategy)
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    templates_to_inject.append(f"【指定范例：{selected_strategy}】\n{f.read()[:2500]}")
                status_ui.write(f"🎯 已精准锁定并准备融合风格模板：`{selected_strategy}`")
    except Exception as e:
        status_ui.write(f"⚠️ 经验库检索跳过: {e}")
        
    templates_str = "\n\n".join(templates_to_inject) if templates_to_inject else ""
    return templates_str, ai_thinking_log

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
    max_pages = st.number_input("原文件最大解析页数 (防超载)", min_value=1, max_value=500, value=100)
    st.markdown("---")
    use_cache = st.checkbox("⚡ 启用极速解析缓存\n\n(若勾选：曾提取过的PDF/图片将直接复用底层MD缓存。)", value=True)

st.markdown("### 📊 AI 材料深度解读工作台")
st.markdown("基于多模态大模型，支持上传 PDF、图片、MD 混合格式，进行单文档解析、多文件横评与纵向趋势推演。")

# ==========================================
# 阅后即焚的文件解析引擎 (带MD5指纹)
# ==========================================
def parse_files_to_text_dict(uploaded_files, max_pages, ui_container, enable_cache):
    result_dict = {}
    for file in uploaded_files:
        ext = os.path.splitext(file.name)[1].lower()
        base_name = os.path.splitext(file.name)[0]
        
        if ext == '.md':
            ui_container.info(f"📄 秒读 Markdown 文本: {file.name}")
            result_dict[base_name] = file.getvalue().decode("utf-8")
        else:
            file_bytes = file.getvalue()
            file_md5 = hashlib.md5(file_bytes).hexdigest()
            cache_file_path = os.path.join(MD_CACHE_DIR, f"{base_name}_{file_md5[:8]}.md")
            
            if enable_cache and os.path.exists(cache_file_path):
                ui_container.success(f"⚡ 物理指纹匹配成功！命中全系统级缓存: {file.name}")
                with open(cache_file_path, "r", encoding="utf-8") as f:
                    result_dict[base_name] = f.read()
                continue
                
            ui_container.warning(f"👁️ 正在激活视觉引擎，逐页提取新文件: {file.name} ...")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_filename = f"{timestamp}_{file.name}"
            file_path = os.path.join(UPLOAD_DIR, safe_filename)
            
            with open(file_path, "wb") as f: f.write(file_bytes)
                
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
            
            with open(cache_file_path, "w", encoding="utf-8") as f:
                f.write(all_content)
                
            try:
                if os.path.exists(file_path): os.remove(file_path)
                for img_path in image_paths:
                    if os.path.exists(img_path): os.remove(img_path)
                ui_container.success(f"✅ {file.name} 解析完成，已存入物理指纹缓存池！")
            except Exception as e:
                ui_container.warning(f"✅ {file.name} 解析完成，但清理临时文件遇到小问题: {e}")
                
            result_dict[base_name] = all_content
            
    return result_dict

# ==========================================
# 3. 终极工作流（包含全部四个 Tab）
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs([
    "🚀 单份文档智能解析", 
    "⚔️ 多公司竞品横评",
    "📈 历史纵向趋势推演",
    "📚 金牌模板库 (AI经验池)" 
])

# ---------------------------------------------------------
# 工作流 A：单份文档智能解析
# ---------------------------------------------------------
with tab1:
    st.markdown("###### 📥 上传待解读文档 (支持混传 PDF / JPG / MD)")
    uploaded_files = st.file_uploader("请拖拽文件至此", type=["pdf", "png", "jpg", "jpeg", "md"], accept_multiple_files=True, key="tab1_uploader")
    
    col_req, col_tpl = st.columns([2, 1])
    with col_req:
        user_requirement_full = st.text_area("🎯 自定义分析侧重点 (选填)", placeholder="例如：请重点提取各省份的 ARPU 值对比...", height=100)
    with col_tpl:
        options = ["🤖 AI 自动匹配金牌范例 (推荐)"] + get_available_templates()
        selected_strategy = st.selectbox("🎯 选择报告行文风格：", options, key="tab1_strategy")
        st.caption("选自动匹配，大模型将亲自阅读并从模板库海选最像的参考。")

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
            with st.status("🧠 正在检索并研判人类金牌经验库...", expanded=True) as status:
                templates_str, ai_thinking_log = get_style_templates(all_content, selected_strategy, status)
            
            if selected_strategy.startswith("🤖") and ai_thinking_log:
                st.info(f"🤖 **大模型主编的选版笔记**：\n\n{ai_thinking_log}")

            # 🌟【最高优先级】：用户需求置顶
            enhanced_requirement = ""
            if user_requirement_full.strip():
                enhanced_requirement += (
                    "<USER_ABSOLUTE_PRIORITY>\n"
                    "【最高优执行指令】\n"
                    "用户亲自下达了自定义的专业分析要求，本要求的优先级绝对高于一切系统默认维度和经验模板。你必须首要且完美地满足以下核心关切：\n"
                    f"{user_requirement_full}\n"
                    "</USER_ABSOLUTE_PRIORITY>\n\n"
                )
            
            cognitive_protocol = (
                "<COGNITIVE_PROTOCOL>\n"
                "【顶级投行深度思考与防幻觉协议 (极其重要)】\n"
                "在输出正式研报前，你必须先在 `<thought_process>你的盘点草稿...</thought_process>` 中理清逻辑：\n"
                "1. 盘点你到底拥有哪些确实存在的数据。\n"
                "2. 强制深度推演：绝对禁止简单的数值罗列！用顶级投行分析师的视角，穿透数据看本质（例如：为什么会涨跌？反映了什么战略？有何隐性风险？）。打开思维，进行商业深度的剖析。\n"
                "3. 零幻觉底线：如果某项业务没有数据支撑，强制自己在草稿中划掉它，坚决不在正式报告中胡编乱造！\n"
                "4. 确认无误后，再在 `<thought_process>` 标签外部输出正式报告。\n"
                "</COGNITIVE_PROTOCOL>\n"
            )
            enhanced_requirement += cognitive_protocol

            if templates_str:
                style_fusion_prompt = (
                    "\n<STYLE_FUSION>\n"
                    "【系统排版、多重经验与投行视角融合指令】\n"
                    "系统在底层为你设定了固定的分析结构（如五大维度）。\n"
                    "为了让报告更丰满、专业，请**综合借鉴以下多个【金牌范例】**的排版大纲、标题层级和逻辑深度。\n"
                    "⚠️ 铁律三连：\n"
                    "1. 既要遵循底层的维度要求，又要吸收多个范例的优秀表达方式。\n"
                    "2. 必须严格遵守底层设定的溯源要求（带来源角标）！\n"
                    "3. 绝不能把范例里的数值编造进新报告！真实数据只来源于本次提取的内容。\n"
                    "=== 供深度借鉴的多个优秀范例 ===\n"
                    f"{templates_str}\n"
                    "</STYLE_FUSION>\n"
                    "<CHART_GENERATION>\n"
                    "【强制图表输出指令】\n"
                    "在梳理核心数据时，如果遇到多项数值对比，你**必须**使用 Markdown 的 Mermaid 语法直接在报告正文中绘制可视化图表（如 pie 饼图、xychart 柱状图）。\n"
                    "</CHART_GENERATION>"
                )
                enhanced_requirement += style_fusion_prompt

            st.markdown("###### 🧠 深度研判报告生成中")
            with st.spinner('红蓝军对抗与模板融合推演中...'):
                summary = generate_final_summary(all_content, enhanced_requirement)
                
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
    st.info("💡 提示：无论您传原文件还是MD底稿，请**直接用公司名称命名文件**。")
    
    # 🌟【新增】：为横评也加上用户自定义需求框
    col_req_b, col_tpl_b = st.columns([2, 1])
    with col_req_b:
        user_requirement_b = st.text_area("🎯 自定义分析侧重点 (选填)", placeholder="例如：请重点对比各家在5G专网和云服务市场上的战略差异...", height=100, key="tab2_req")
    with col_tpl_b:
        options = ["🤖 AI 自动匹配金牌范例 (推荐)"] + get_available_templates()
        selected_strategy_b = st.selectbox("🎯 选择报告行文风格：", options, key="tab2_strategy")
        st.caption("选自动匹配，大模型将亲自阅读并从模板库海选最像的参考。")

    compare_files = st.file_uploader("批量拖拽多个公司的文件至此", type=["pdf", "png", "jpg", "jpeg", "md"], accept_multiple_files=True, key="tab2_uploader")
    
    if st.button("⚔️ 启动多 Agent 竞品横评", type="primary", key="btn_compare"):
        if not compare_files or len(compare_files) < 2:
            st.warning("⚠️ 进行横评至少需要上传 2 份不同公司的文件！")
            st.stop()
            
        status_container = st.container()
        company_dict = parse_files_to_text_dict(compare_files, max_pages, status_container, use_cache)
        
        all_content_for_search = "\n".join(list(company_dict.values()))[:1000]
        with st.status("🧠 正在检索并研判人类金牌经验库...", expanded=True) as status:
            templates_str, ai_thinking_log = get_style_templates(all_content_for_search, selected_strategy_b, status)
            
        if selected_strategy_b.startswith("🤖") and ai_thinking_log:
            st.info(f"🤖 **大模型主编的选版笔记**：\n\n{ai_thinking_log}")

        style_instruction = ""
        
        # 🌟【最高优先级】：用户横评需求置顶
        if user_requirement_b.strip():
            style_instruction += (
                "<USER_ABSOLUTE_PRIORITY>\n"
                "【最高优执行指令】\n"
                "用户亲自下达了自定义的横评核心焦点，本要求的优先级绝对高于一切系统大纲和经验模板！你必须将大部分笔墨用于回答和剖析以下问题：\n"
                f"{user_requirement_b}\n"
                "</USER_ABSOLUTE_PRIORITY>\n\n"
            )

        style_instruction += (
            "<COGNITIVE_PROTOCOL>\n"
            "【顶级投行错位竞争与非对称对比协议 (极其重要)】\n"
            "在写报告前，先输出 `<thought_process>分析草稿...</thought_process>` 进行逻辑推演！\n"
            "1. 交叉验证与淘汰：提取各公司数据。若某对比项（如算力）A有B没有，绝不允许写“推测B相当”这种废话！\n"
            "2. 升维打击（错位对比）：打开思维！当口径不对齐时，不要报错，而是上升到战略分歧的高度进行投行视角的分析（如“A死守基本盘，B狂奔云端”）。\n"
            "3. 深度推演：对于共有数据，绝对禁止简单罗列！必须剖析竞争压迫感、市占率趋势及背后战略意图。\n"
            "4. 零幻觉底线：没数据就坚决不编造。\n"
            "</COGNITIVE_PROTOCOL>\n"
        )
        
        if templates_str:
            style_instruction += (
                "<STYLE_FUSION>\n"
                "【系统排版、多重经验与投行视角融合指令】\n"
                "请重点吸收以下**多个**【金牌范例】的排版骨架、行文语气和结构深度，集百家之长进行横评输出。\n"
                "⚠️ 铁律：只学语气和逻辑深度，结合底层提示词要求，严禁照抄旧数值！\n"
                "=== 金牌范例 ===\n"
                f"{templates_str}\n"
                "</STYLE_FUSION>\n"
                "<CHART_GENERATION>\n"
                "【强制图表输出指令】\n"
                "在对比多家公司的核心数据时，你**必须**使用 Markdown 的 Mermaid 语法直接在正文中绘制出可视化图表（如 xychart 柱状对比图等）。\n"
                "</CHART_GENERATION>"
            )

        if style_instruction:
            company_dict["_STYLE_INSTRUCTION_"] = style_instruction
            
        st.markdown("###### 🧠 多模态竞品大脑生成中")
        with st.spinner('正在强制大模型交叉校验数据，剔除无据猜测...'):
            compare_summary = generate_compare_summary(company_dict)
            
        st.success("🎉 竞品横评报告已生成！")
        st.markdown("---")
        st.markdown(compare_summary, unsafe_allow_html=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_md_content = f"# ⚔️ 行业竞品横向对比研判报告\n\n{compare_summary}"
        
        names = [k for k in company_dict.keys() if k != "_STYLE_INSTRUCTION_"]
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
    st.info("💡 提示：无论您传原文件还是MD底稿，请**直接用年份命名文件**。")
    
    # 🌟【新增】：为趋势演进也加上用户自定义需求框
    col_req_c, col_tpl_c = st.columns([2, 1])
    with col_req_c:
        user_requirement_c = st.text_area("🎯 自定义分析侧重点 (选填)", placeholder="例如：重点推演近三年这几家公司研发投入的飙升幅度，以及对未来利润率的隐性侵蚀...", height=100, key="tab3_req")
    with col_tpl_c:
        options = ["🤖 AI 自动匹配金牌范例 (推荐)"] + get_available_templates()
        selected_strategy_c = st.selectbox("🎯 选择报告行文风格：", options, key="tab3_strategy")
        st.caption("选自动匹配，大模型将亲自阅读并从模板库海选最像的参考。")

    trend_files = st.file_uploader("批量拖拽多年的文件至此", type=["pdf", "png", "jpg", "jpeg", "md"], accept_multiple_files=True, key="tab3_uploader")
    
    if st.button("📈 启动历史趋势推演", type="primary", key="btn_trend"):
        if not trend_files or len(trend_files) < 2:
            st.warning("⚠️ 进行趋势推演至少需要上传 2 个年份的文件！")
            st.stop()
            
        status_container = st.container()
        yearly_dict = parse_files_to_text_dict(trend_files, max_pages, status_container, use_cache)
        
        all_content_for_search = "\n".join(list(yearly_dict.values()))[:1000]
        with st.status("🧠 正在检索并研判人类金牌经验库...", expanded=True) as status:
            templates_str, ai_thinking_log = get_style_templates(all_content_for_search, selected_strategy_c, status)
            
        if selected_strategy_c.startswith("🤖") and ai_thinking_log:
            st.info(f"🤖 **大模型主编的选版笔记**：\n\n{ai_thinking_log}")

        style_instruction = ""
        
        # 🌟【最高优先级】：用户推演需求置顶
        if user_requirement_c.strip():
            style_instruction += (
                "<USER_ABSOLUTE_PRIORITY>\n"
                "【最高优执行指令】\n"
                "用户亲自下达了自定义的历史趋势推演焦点，本要求的优先级绝对高于一切系统大纲和经验模板！你必须在报告中最优先满足以下推演要求：\n"
                f"{user_requirement_c}\n"
                "</USER_ABSOLUTE_PRIORITY>\n\n"
            )

        style_instruction += (
            "<COGNITIVE_PROTOCOL>\n"
            "【顶级投行生命周期与防幻觉协议 (极其重要)】\n"
            "在写报告前，先在 `<thought_process>草稿...</thought_process>` 中理清历年数据！\n"
            "1. 甄别断层：如果某项指标只有2021年有，后续断更，严禁捏造“持续增长”，必须换连续指标分析！\n"
            "2. 商业周期推演：打开思维！用顶级投行视角，看穿连年数据的演进，指出战略拐点、第二曲线的兴衰和结构性隐患，拒绝平铺直叙。\n"
            "</COGNITIVE_PROTOCOL>\n"
        )
        
        if templates_str:
            style_instruction += (
                "<STYLE_FUSION>\n"
                "【系统排版、多重经验与投行视角融合指令】\n"
                "请重点吸收以下**多个**【金牌范例】的排版骨架、行文语气和结构深度，集百家之长进行趋势推演。\n"
                "⚠️ 铁律：只学语气和逻辑深度，结合底层提示词要求，严禁照抄旧数值！\n"
                "=== 金牌范例 ===\n"
                f"{templates_str}\n"
                "</STYLE_FUSION>\n"
                "<CHART_GENERATION>\n"
                "【强制图表输出指令】\n"
                "在分析多年历史趋势数据时，你**必须**使用 Markdown 的 Mermaid 语法直接在正文中绘制出可视化图表（如 xychart 折线图/柱状图等）。\n"
                "</CHART_GENERATION>"
            )

        if style_instruction:
            yearly_dict["_STYLE_INSTRUCTION_"] = style_instruction

        st.markdown("###### 🧠 历史趋势大脑生成中")
        with st.spinner('正在梳理历年时间轴，甄别断层数据...'):
            trend_summary = generate_trend_summary(yearly_dict)
            
        st.success("🎉 纵向战略演进报告已生成！")
        st.markdown("---")
        st.markdown(trend_summary, unsafe_allow_html=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_md_content = f"# 📈 企业纵向战略演进与周期复盘报告\n\n{trend_summary}"
        
        years = sorted([k for k in yearly_dict.keys() if k != "_STYLE_INSTRUCTION_"])
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

# ---------------------------------------------------------
# Tab 4 - 经验库沉淀区 
# ---------------------------------------------------------
with tab4:
    st.markdown("#### 📥 投喂人工极品报告，让大模型越用越聪明")
    st.info("💡 提示：您可以上传任何文件。系统具备全局指纹识别能力：只要文件在其他页面解析过，这里将实现【毫秒级穿透】，不再耗费任何大模型算力！")
    
    template_files = st.file_uploader("上传历史优秀报告作为金牌模板", accept_multiple_files=True, key="template_uploader")
    
    if st.button("🚀 提炼并入库经验池", type="secondary"):
        if not template_files:
            st.warning("请先上传文件！")
        else:
            status_container = st.container()
            with st.status("🧠 正在吸收人类智慧入库...", expanded=True) as status:
                embeddings = get_embeddings()
                
                db_path = os.path.join(TEMPLATE_DB_DIR, "index.faiss")
                vectorstore = FAISS.load_local(TEMPLATE_DB_DIR, embeddings, allow_dangerous_deserialization=True) if os.path.exists(db_path) else None
                
                status.write("正在调用全系统指纹高速缓存与分拣引擎...")
                tpl_dict = parse_files_to_text_dict(template_files, max_pages, status_container, enable_cache=use_cache)
                
                new_docs = []
                for base_name, content in tpl_dict.items():
                    md_filename = f"{base_name}.md"
                    with open(os.path.join(TEMPLATE_MD_DIR, md_filename), "w", encoding="utf-8") as f:
                        f.write(content)
                    
                    feature_text = content[:1500]
                    new_docs.append(Document(page_content=feature_text, metadata={"source": md_filename}))
                    status.write(f"✅ `{base_name}` 经验已成功向量化并吸收！")
                
                if new_docs:
                    if vectorstore is None:
                        vectorstore = FAISS.from_documents(new_docs, embeddings)
                    else:
                        vectorstore.add_documents(new_docs)
                    vectorstore.save_local(TEMPLATE_DB_DIR)
                    status.update(label="🎉 经验库更新完成！全局指纹系统已打通！", state="complete")
    
    st.divider()
    st.markdown("#### 🏆 已收录的金牌模板清单")
    existing_tpls = get_available_templates()
    if existing_tpls:
        for tpl in existing_tpls:
            st.markdown(f"- 📄 `{tpl}`")
    else:
        st.markdown("*当前经验库为空，请上传您的第一份金牌报告！*")