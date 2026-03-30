# pages/01_💬_01对话大厅.py
import streamlit as st
import sqlite3
import os
import tempfile
import pandas as pd
import json
import re
from datetime import datetime
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_community.callbacks.manager import get_openai_callback
import core.paths

# 👇 引入真实底层引擎
from modules.data_analysis.agent import run_agent_pipeline
from core.parsers.document_engine import smart_parse_document
from modules.rag.query_service import build_query_chain, format_docs

st.set_page_config(page_title="通用智能大管家", page_icon="🤖", layout="wide")

# ==========================================
# 0. 初始化全局工作区
# ==========================================
if "workspace_dir" not in st.session_state:
    st.session_state.workspace_dir = tempfile.mkdtemp(prefix="agent_workspace_")

# ==========================================
# 1. 纯手工打造：硬核工具箱 (已移除查时间工具)
# ==========================================
def analyze_workspace_data(query: str = "综合分析", **kwargs) -> str:
    """真实数据分析与画图工具"""
    workspace = st.session_state.workspace_dir
    dfs = {}
    for f in os.listdir(workspace):
        if f.endswith(('.csv', '.xlsx', '.xls')):
            try:
                if f.endswith('.csv'): dfs[f] = pd.read_csv(os.path.join(workspace, f))
                else: dfs[f] = pd.read_excel(os.path.join(workspace, f))
            except Exception as e:
                return f"文件 {f} 读取失败: {str(e)}"
                
    if not dfs:
        return "【失败】工作区内没有任何表格。请提示用户先上传数据文件。"

    try:
        html_string, report_out, context_data = run_agent_pipeline(
            dfs=dfs, user_query=query, api_key=settings.API_KEY, api_base=settings.API_BASE
        )
        return f"【成功】底层执行日志：\n{context_data.get('data', '无')}\n请告诉用户底层图表状态机已跑通并生成结果。"
    except Exception as e:
        return f"【报错】底层数据引擎异常：{str(e)}"

def read_workspace_document(file_name: str, query: str = "提取核心内容", **kwargs) -> str:
    """真实单文档深度解析引擎 (带智能MD缓存)"""
    workspace = st.session_state.workspace_dir
    file_path = os.path.join(workspace, file_name)
    
    if not os.path.exists(file_path):
        return f"【失败】找不到文件 {file_name}，请确认用户是否已上传。"
        
    try:
        docs = smart_parse_document(file_path)
        if not docs:
            return f"【失败】未能从 {file_name} 中提取有效文本。"
            
        full_content = "\n".join([doc.page_content for doc in docs])
        truncated_content = full_content[:15000] # 截断保护
        suffix = "\n\n...(截断)" if len(full_content) > 15000 else ""
        
        return f"【文件 {file_name} 真实读取成功】：\n{truncated_content}{suffix}\n\n请严格基于此内容回答：{query}"
    except Exception as e:
        return f"【解析报错】：{str(e)}"

def search_knowledge_base(query: str, **kwargs) -> str:
    """真实企业 RAG 检索引擎 (财报级强溯源)"""
    try:
        _, retriever = build_query_chain()
        source_docs = retriever.invoke(query)
        
        if not source_docs:
            return f"在企业全局知识库中未能检索到与 '{query}' 相关的信息。"
            
        real_rag_result = format_docs(source_docs)
        return f"【知识库真实检索成功】：\n{real_rag_result}\n\n请严格使用以上检索到的数据回答用户问题，并在回答的关键数据后，保留 [1] [2] 这种溯源角标！"
    except FileNotFoundError:
        return "【失败】找不到知识库索引文件。请告诉用户需要先去『06_RAG检索』页面入库文档。"
    except Exception as e:
        return f"【RAG 报错】：{str(e)}"

def search_internet(query: str, **kwargs) -> str:
    """真实全网搜索引擎 (带企业内网防崩溃隔离)"""
    try:
        from langchain_community.tools import DuckDuckGoSearchRun
        search = DuckDuckGoSearchRun()
        
        safe_query = query[:50] 
        result = search.invoke(safe_query)
        
        if not result or "No good DuckDuckGo Search Result was found" in result:
            return f"【互联网检索失败】：未能找到关于 '{query}' 的有效信息。"
            
        return f"【互联网真实检索成功】：\n{result}\n\n请严格整理上述网络最新信息来回答用户，标注信息来源于互联网。"
        
    except ImportError:
        return "【系统致命错误】：缺少 duckduckgo-search 库，请管理员在服务器运行 pip install duckduckgo-search"
    except Exception as e:
        error_msg = str(e)
        if "Timeout" in error_msg or "ProxyError" in error_msg or "SSLError" in error_msg:
            return "【网络拦截警告】：请求被企业内网防火墙或代理拦截。请告诉用户当前处于内网环境，无法访问外部互联网。"
        return f"【搜索组件异常】：{error_msg}"

AVAILABLE_TOOLS = {
    "analyze_workspace_data": analyze_workspace_data,
    "read_workspace_document": read_workspace_document,
    "search_knowledge_base": search_knowledge_base,
    "search_internet": search_internet
}

# 🌟 大管家最高指令法则基座 (去掉了时间工具)
SUPERVISOR_SYSTEM_PROMPT_BASE = """你是一个极其专业的企业级全能AI大管家。你有能力自主思考，并调用系统工具来辅助回答用户。

【可用工具库】
1. name: analyze_workspace_data
   args: {"query": "用户的具体分析需求"}
2. name: read_workspace_document
   args: {"file_name": "完整的文件名带后缀", "query": "用户的疑问"}
3. name: search_knowledge_base
   description: 当询问公司规章、财报、历史资料时检索全局库。
   args: {"query": "提炼出的精准搜索关键词"}
4. name: search_internet
   description: 当用户询问当下的实时新闻、外部公开信息、或超出你知识库范围的外部问题时，调用此工具去公网搜索。
   args: {"query": "提取出的核心搜索关键词"}

【执行规范】(最高优先级)
如果你决定调用工具，必须且只能输出如下 XML 结构，禁止输出其他废话：
<tool_call>
{"name": "工具名", "args": {"参数名": "参数值"}}
</tool_call>

如果已经收到【系统通知：工具执行结果】，请直接用优美的排版回答用户，**并务必保留检索结果中的 [1] [2] 等来源角标**！
"""

# ==========================================
# 2. 数据库与记忆引擎
# ==========================================
DB_PATH = core.paths.get_db_path("chat_memory.db")
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS dual_chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, track TEXT, 
            role TEXT, content TEXT, timestamp DATETIME)''')
init_db()

def get_history(user_id, limit=10):
    with sqlite3.connect(DB_PATH) as conn:
        query = "SELECT role, content FROM dual_chat_history WHERE user_id = ? AND track = 'SUPERVISOR' ORDER BY id ASC"
        return conn.execute(query, (user_id,)).fetchall()[-(limit * 2):] if limit else conn.execute(query, (user_id,)).fetchall()

def save_message(user_id, role, content):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO dual_chat_history (user_id, track, role, content, timestamp) VALUES (?, 'SUPERVISOR', ?, ?, ?)",
            (user_id, role, content, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

# ==========================================
# 3. 侧边栏：Agent 物理工作区
# ==========================================
with st.sidebar:
    st.header("👤 身份与记忆隔离")
    user_id = st.text_input("专属身份 ID", value="Admin_01")
    model_name = st.text_input("🧠 核心调度模型", value=settings.MODEL_TEXT or "deepseek-v3-0324")
    
    st.divider()
    st.header("📥 Agent 工作区 (大管家视界)")
    uploaded_files = st.file_uploader("支持文档与表格", accept_multiple_files=True, type=['csv', 'xlsx', 'xls', 'pdf', 'docx', 'txt'])
    if uploaded_files:
        for uf in uploaded_files:
            with open(os.path.join(st.session_state.workspace_dir, uf.name), "wb") as f:
                f.write(uf.getbuffer())
        st.success(f"已载入 {len(uploaded_files)} 个文件入工作区！")

# ==========================================
# 4. 主干逻辑：ReAct 循环引擎 (带动态时间注入)
# ==========================================
st.title("🤖 商业级全能大管家")
st.markdown("通过 Prompt 物理引擎重构的通用智能体，已挂载**真实分析引擎**、**RAG知识库**与**公网搜索**。")

history = get_history(user_id, limit=10)
for role, content in history:
    with st.chat_message(role, avatar="🧑‍💻" if role == "user" else "🤖"):
        st.markdown(content)

if prompt := st.chat_input("试着问时间、查询昨日新闻、或者上传表格让它分析..."):
    save_message(user_id, 'user', prompt)
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)
        
    # 🌟 架构升维：每次发起对话前，动态获取此刻的物理时间，并悄悄注入到系统大本营里
    current_time_str = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
    dynamic_sys_prompt = SUPERVISOR_SYSTEM_PROMPT_BASE + f"\n\n【系统内部状态】：当前的准确物理时间是 {current_time_str}。在搜索实时新闻或回答时间相关问题时，请务必以此为时间锚点。"
    
    messages = [SystemMessage(content=dynamic_sys_prompt)]
    for r, c in history: messages.append(HumanMessage(content=c) if r == 'user' else AIMessage(content=c))
    messages.append(HumanMessage(content=prompt))

    with st.chat_message("assistant", avatar="🤖"):
        status = st.status("🧠 大管家正在推演行动路线...", expanded=True)
        llm = ChatOpenAI(model=model_name, api_key=settings.API_KEY, base_url=settings.API_BASE, temperature=0.1)
        
        final_answer = ""
        for step in range(4): # 最大推演步数
            try:
                response = llm.invoke(messages).content
                messages.append(AIMessage(content=response)) 
                tool_match = re.search(r'<tool_call>\s*(.*?)\s*</tool_call>', response, re.DOTALL)
                
                if tool_match:
                    try:
                        tool_req = json.loads(tool_match.group(1))
                        t_name, t_args = tool_req.get("name"), tool_req.get("args", {})
                        status.write(f"🛠️ 决定调用工具: `{t_name}` | 参数: `{t_args}`")
                        
                        tool_res = AVAILABLE_TOOLS[t_name](**t_args) if t_name in AVAILABLE_TOOLS else f"找不到工具: {t_name}"
                        status.write(f"✅ 工具底层结果已返回 (长度:{len(str(tool_res))})")
                        messages.append(HumanMessage(content=f"【系统通知：工具 {t_name} 执行结果】\n{tool_res}"))
                    except json.JSONDecodeError:
                        messages.append(HumanMessage(content="【系统警告】：工具调用的 JSON 格式不规范，请重试。"))
                else:
                    final_answer = response
                    break
            except Exception as e:
                final_answer = f"大管家推演中断: {str(e)}"
                break
        
        if not final_answer: final_answer = "推演达到了最大步数限制，未能得出结论。"
        status.update(label="任务调度与执行完毕！", state="complete", expanded=False)
        st.markdown(final_answer)
        save_message(user_id, 'assistant', final_answer)