# pages/03_📈_03数据分析.py
import os
import streamlit as st
import pandas as pd
from dotenv import load_dotenv

import core.paths  
from core.token_tracker import log_usage
from langchain_community.callbacks.manager import get_openai_callback
from modules.data_analysis.agent import run_agent_pipeline, run_followup_chat

load_dotenv(core.paths.ENV_FILE)
API_KEY = os.getenv("INTERNAL_API_KEY")
API_BASE = os.getenv("INTERNAL_API_BASE")
MODEL_NAME = os.getenv("MODEL_TEXT", "deepseek-v3-0324")

st.set_page_config(page_title="AI 数据分析终端", page_icon="📈", layout="wide")

st.title("📈 智能数据分析与洞察终端")
st.markdown("支持**多文件上传**与**Excel多Sheet并发读取**，AI将自动进行跨表关联与全面洞察。")

if 'da_report_html' not in st.session_state:
    st.session_state.da_report_html = None
if 'da_report_path' not in st.session_state:
    st.session_state.da_report_path = None
if 'da_context_data' not in st.session_state:
    st.session_state.da_context_data = None
if 'da_chat_history' not in st.session_state:
    st.session_state.da_chat_history = []

with st.sidebar:
    st.header("1. 上传数据")
    uploaded_files = st.file_uploader(
        "支持 CSV 或 Excel 文件 (可多选)", 
        type=['csv', 'xlsx', 'xls'], 
        accept_multiple_files=True
    )
    
    st.header("2. 分析需求 (可选)")
    user_query = st.text_area("请输入您的具体关注点...", placeholder="例如：将销售表和省份表关联起来，分析各省业绩。")
    analyze_btn = st.button("🚀 开始智能分析", type="primary")

if uploaded_files:
    all_dfs = {}
    for file in uploaded_files:
        try:
            if file.name.endswith('.csv'):
                df_temp = pd.read_csv(file)
                all_dfs[file.name] = df_temp
            else:
                xls_dict = pd.read_excel(file, sheet_name=None)
                if len(xls_dict) == 1:
                    all_dfs[file.name] = list(xls_dict.values())[0]
                else:
                    for sheet_name, df_sheet in xls_dict.items():
                        all_dfs[f"{file.name} - [{sheet_name}]"] = df_sheet
        except Exception as e:
            st.sidebar.error(f"读取文件 {file.name} 失败: {e}")
    
    if not all_dfs:
        st.error("未能成功解析任何数据文件，请检查文件格式。")
        st.stop()
        
    st.write("### 📂 分析范围确认")
    # 👇 核心改进：使用 multiselect 并默认全选所有加载出来的表
    selected_dataset_names = st.multiselect(
        "已自动解析以下表单，**默认全部进行联合分析**。您可以手动取消不需要的表：", 
        list(all_dfs.keys()),
        default=list(all_dfs.keys()) # 默认全选
    )
    
    if not selected_dataset_names:
        st.warning("请至少保留一个表格用于分析！")
        st.stop()
        
    # 组装最终需要送给大模型的字典
    target_dfs = {name: all_dfs[name] for name in selected_dataset_names}
    st.success(f"✅ 准备就绪，共将 {len(target_dfs)} 张表送入 AI 分析引擎。")

    if analyze_btn:
        if not API_KEY:
            st.error("缺失 API KEY 配置！")
            st.stop()
            
        with st.status(f"🤖 Multi-Agent 正在对 {len(target_dfs)} 张表进行联合思考与代码编写...", expanded=True) as status:
            with get_openai_callback() as cb:
                # 传入的是一个字典 target_dfs
                html_content, report_path, context_data = run_agent_pipeline(target_dfs, user_query, API_KEY, API_BASE)
                
                tokens = cb.total_tokens
                if tokens == 0:
                    tokens = 8000 # 多表模式耗费较大，基础兜底
                log_usage("数据分析-多表模式", MODEL_NAME, tokens)
            
            status.update(label="✅ 跨表数据分析流执行完毕！(点击展开查看代码与报错排查史)", state="complete", expanded=False)
            
        st.session_state.da_report_html = html_content
        st.session_state.da_report_path = report_path
        st.session_state.da_context_data = context_data
        st.session_state.da_chat_history = []  
else:
    st.info("👈 请先在左侧上传数据文件。")

# ==============================================================
# 报告渲染与追问模块 (保持不变)
# ==============================================================
if st.session_state.da_report_html:
    st.success("✅ 分析完成！")
    st.components.v1.html(st.session_state.da_report_html, height=800, scrolling=True)
    st.download_button("📥 下载独立 HTML 报告", data=st.session_state.da_report_html, file_name="AI_Analysis_Report.html", mime="text/html")
        
    st.divider()
    st.markdown("### 💬 报告深度追问与优化")
    for msg in st.session_state.da_chat_history:
        st.chat_message(msg["role"]).write(msg["content"])
        
    if prompt := st.chat_input("在此输入您的追问或优化需求..."):
        st.session_state.da_chat_history.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)
        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            full_response = ""
            try:
                history = st.session_state.da_chat_history[:-1] 
                with get_openai_callback() as cb:
                    stream_generator = run_followup_chat(
                        user_query=prompt, chat_history=history, 
                        context_data=st.session_state.da_context_data, 
                        api_key=API_KEY, api_base=API_BASE
                    )
                    count = 0
                    for chunk in stream_generator:
                        full_response += chunk.content
                        count += 1
                        if count % 8 == 0: response_placeholder.markdown(full_response + "▌")
                    response_placeholder.markdown(full_response)
            except Exception as e:
                full_response = f"追问失败: {e}"
                st.error(full_response)
        st.session_state.da_chat_history.append({"role": "assistant", "content": full_response})
