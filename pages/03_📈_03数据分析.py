# pages/03_📈_数据分析.py
import os
import streamlit as st
import pandas as pd
from dotenv import load_dotenv

import core.paths  # 【必加】：引入全局环境变量管家
from core.token_tracker import log_usage
from langchain_community.callbacks.manager import get_openai_callback

# 【修改导入路径】：从新模块导入
from modules.data_analysis.agent import run_agent_pipeline, run_followup_chat

# 加载环境变量 (会自动读取根目录的 .env)
load_dotenv(core.paths.ENV_FILE)
API_KEY = os.getenv("INTERNAL_API_KEY")
API_BASE = os.getenv("INTERNAL_API_BASE")
MODEL_NAME = os.getenv("MODEL_TEXT", "deepseek-v3-0324")

# 页面配置
st.set_page_config(page_title="AI 数据分析终端", page_icon="📈", layout="wide")

st.title("📈 智能数据分析与洞察终端")
st.markdown("支持电信网络、财务及通用数据的自动化扫描与可视化。")

# 【修复】：统一所有的 session_state 为 `da_` 前缀
if 'da_report_html' not in st.session_state:
    st.session_state.da_report_html = None
if 'da_report_path' not in st.session_state:
    st.session_state.da_report_path = None
if 'da_context_data' not in st.session_state:
    st.session_state.da_context_data = None
if 'da_chat_history' not in st.session_state:
    st.session_state.da_chat_history = []

# 侧边栏：文件上传
with st.sidebar:
    st.header("1. 上传数据")
    uploaded_file = st.file_uploader("支持 CSV 或 Excel 文件", type=['csv', 'xlsx', 'xls'])
    
    st.header("2. 分析需求 (可选)")
    user_query = st.text_area("请输入您的具体关注点...", placeholder="例如：分析各分公司的利润趋势，或按默认策略全面扫描。")
    
    analyze_btn = st.button("🚀 开始智能分析", type="primary")

# 主界面区域：执行分析逻辑
if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
        st.write("### 📄 数据预览", df.head(3))
    except Exception as e:
        st.error(f"读取文件失败: {e}")
        st.stop()

    if analyze_btn:
        if not API_KEY:
            st.error("缺失 API KEY 配置，请检查 .env 文件！")
            st.stop()
            
        with st.spinner('🤖 AI 正在拼命敲代码、画图并思考中，请稍候...'):
            with get_openai_callback() as cb:
                html_content, report_path, context_data = run_agent_pipeline(df, user_query, API_KEY, API_BASE)
                
                # 👇【终极计费修复】：双保险机制
                tokens = cb.total_tokens
                if tokens == 0:
                    # 如果 LangGraph 把上下文吞了导致统计失败，启用强行估算。
                    # 由于是多Agent循环(写代码、反思报错等)，消耗往往是文本量的 2.5 倍
                    content_length = len(str(df.head(20))) + len(str(html_content)) + 2000
                    tokens = int(content_length * 2.5)
                
                log_usage("数据分析-全流程", MODEL_NAME, tokens)
                # 👆【修复结束】
            
            # 【修复】：全部加上 da_ 前缀，严防报错！
            st.session_state.da_report_html = html_content
            st.session_state.da_report_path = report_path
            st.session_state.da_context_data = context_data
            st.session_state.da_chat_history = []  
else:
    st.info("👈 请先在左侧上传数据文件。")


# ==============================================================
# 如果报告已经生成，渲染报告并在下方开启“追问与优化”模块
# ==============================================================
if st.session_state.da_report_html:
    st.success("✅ 分析完成！")
    
    # 渲染 HTML 报告
    st.components.v1.html(st.session_state.da_report_html, height=800, scrolling=True)
    
    # ✅ 替换为：直接使用内存中的 HTML 字符串提供下载
    st.download_button(
        label="📥 下载独立 HTML 报告",
        data=st.session_state.da_report_html,
        file_name="AI_Analysis_Report.html",
        mime="text/html"
    )
        
    st.divider()
    st.markdown("### 💬 报告深度追问与优化")
    st.caption("您可以基于上方报告继续提问，例如：'帮我深挖一下第二部分的数据'，或 '将报告的结论部分改写得更委婉一些'。")
    
    # 渲染历史聊天记录
    for msg in st.session_state.da_chat_history:
        st.chat_message(msg["role"]).write(msg["content"])
        
    # 处理用户追问输入
    if prompt := st.chat_input("在此输入您的追问或优化需求..."):
        # 记录用户问题并显示
        st.session_state.da_chat_history.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)
        
        # 调用追问 Agent 生成回复
        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            full_response = ""
            try:
                history = st.session_state.da_chat_history[:-1] 
                
                with get_openai_callback() as cb:
                    stream_generator = run_followup_chat(
                        user_query=prompt, 
                        chat_history=history, 
                        context_data=st.session_state.da_context_data, 
                        api_key=API_KEY, 
                        api_base=API_BASE
                    )
                    
                    count = 0
                    for chunk in stream_generator:
                        full_response += chunk.content
                        count += 1
                        if count % 8 == 0:
                            response_placeholder.markdown(full_response + "▌")
                    response_placeholder.markdown(full_response)
                    
                    # 👇【终极计费修复】：流式输出抓取兜底
                    tokens = cb.total_tokens
                    if tokens == 0:
                        # 1个汉字约合 1.2 个Token
                        tokens = int((len(str(history)) + len(prompt) + len(full_response)) * 1.2)
                    
                    log_usage("数据分析-深度追问", MODEL_NAME, tokens)
                    # 👆【修复结束】
                
            except Exception as e:
                full_response = f"追问请求失败: {e}"
                st.error(full_response)
                
        # 保存 AI 回复
        st.session_state.da_chat_history.append({"role": "assistant", "content": full_response})