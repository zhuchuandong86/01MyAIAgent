# modules/data_analysis/agent.py
import glob
import tempfile
from contextlib import redirect_stdout
import pandas as pd
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import streamlit as st
from datetime import datetime
import os
import io
import re
import shutil
from typing import TypedDict, List, Dict, Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

import core.paths
from modules.data_analysis.reporter import generate_html_report
from core.schemas import CodeReflection
from core.prompts import (
    DA_PLANNER_SYSTEM, DA_CODER_SYSTEM, DA_REFLECT_SYSTEM, 
    DA_ANALYST_SYSTEM, DA_FOLLOWUP_SYSTEM
)
# memory = MemorySaver()
# ==========================================
# 1. 定义 LangGraph 全局状态字典
# ==========================================
class AgentState(TypedDict):
    dfs: dict
    dataset_summary: str
    user_query: str
    chart_dir: str
    api_key: str
    api_base: str
    
    plan: str
    generated_code: str
    execution_logs: str
    error_msg: str
    
    reflections: list
    attempt: int
    max_retries: int
    
    final_markdown: str

# ==========================================
# 2. 定义图节点 (Nodes) - 完美保留你的 UI 渲染
# ==========================================
def node_planner(state: AgentState) -> dict:
    st.markdown("### 🗺️ Planner Agent 正在宏观审视所有表格，制定分析计划...")
    llm = ChatOpenAI(temperature=0, model="deepseek-v3-0324", api_key=state["api_key"], base_url=state["api_base"])
    prompt = ChatPromptTemplate.from_messages([
        ("system", DA_PLANNER_SYSTEM),
        ("user", "以下是本次加载的所有数据表大纲：\n\n{dataset_summary}\n\n用户需求: {query}")
    ])
    
    analysis_plan = ""
    try:
        plan_placeholder = st.empty()
        count = 0
        for chunk in (prompt | llm).stream({"dataset_summary": state["dataset_summary"], "query": state["user_query"]}):
            analysis_plan += chunk.content
            count += 1
            if count % 8 == 0: plan_placeholder.markdown(f"```text\n{analysis_plan}▌\n```")
        plan_placeholder.markdown(f"```text\n{analysis_plan}\n```")
        st.success("✅ 多表联合分析计划制定完毕！")
    except Exception as e:
        analysis_plan = "通用多表关联分析：趋势、对比、数据融合挖掘"
        st.error(f"❌ Planner 调用失败，使用默认计划：{e}")
        
    return {"plan": analysis_plan}

def node_coder(state: AgentState) -> dict:
    st.markdown(f"### 👨‍💻 程序员 Agent 开始跨表写代码 (第 {state['attempt']+1}/{state['max_retries']} 次)")
    llm = ChatOpenAI(temperature=0, model="deepseek-v3-0324", api_key=state["api_key"], base_url=state["api_base"])
    
    memory_str = "无历史报错，首次尝试。"
    if state["reflections"]:
        memory_str = "\n".join([
            f"【第{m['attempt']}次失败反思】\n  报错: {m['error']}\n  对策: {m['fix_strategy']}"
            for m in state["reflections"]
        ])

    prompt = ChatPromptTemplate.from_messages([
        ("system", DA_CODER_SYSTEM),
        ("user", "分析需求：{query}\n\n【重要】已加载的真实数据集概览：\n{dataset_summary}")
    ])

    raw_code = ""
    try:
        code_placeholder = st.empty()
        count = 0
        for chunk in (prompt | llm).stream({
            "dataset_summary": state["dataset_summary"], "analysis_plan": state["plan"],
            "memory_str": memory_str, "query": state["user_query"]
        }):
            raw_code += chunk.content
            count += 1
            if count % 8 == 0: code_placeholder.markdown(f"```python\n{raw_code}▌\n```")
        code_placeholder.markdown(f"```python\n{raw_code}\n```")
        st.info("⚙️ 代码接收完毕，准备执行...")
    except Exception as e:
        st.error(f"API请求异常: {e}")

    # 清洗代码并注入画图补丁 (完美保留你的逻辑)
    clean_code = raw_code.replace("```python", "").replace("```", "").strip()
    FULLWIDTH_MAP = {"，": ",", "。": ".", "：": ":", "；": ";", "（": "(", "）": ")"}
    for zh, en in FULLWIDTH_MAP.items(): clean_code = clean_code.replace(zh, en)
    
    agg_prefix = (
        "import matplotlib\nimport matplotlib.pyplot as plt\nplt.switch_backend('agg')\n"
        "plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']\n"
        "plt.rcParams['axes.unicode_minus'] = False\n"
        f"__chart_dir__ = r'{state['chart_dir']}'\nimport os as __os__\n"
        "if not hasattr(plt, '_original_savefig'):\n"
        "    plt._original_savefig = plt.savefig\n"
        "    def __patched_savefig__(fname, *a, **kw):\n"
        "        if not __os__.path.isabs(str(fname)):\n"
        "            fname = __os__.path.join(__chart_dir__, __os__.path.basename(str(fname)))\n"
        "        plt._original_savefig(fname, *a, **kw)\n"
        "    plt.savefig = __patched_savefig__\n"
    )
    return {"generated_code": agg_prefix + clean_code}

def node_executor(state: AgentState) -> dict:
    code = state["generated_code"]
    dfs = state["dfs"]
    first_df_name = list(dfs.keys())[0] if dfs else None
    
    captured_output = io.StringIO()
    error_msg = ""
    
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as _plt
        
        exec_env = {"dfs": dfs, "df": dfs[first_df_name] if first_df_name else None, "pd": pd, "os": os, "re": re}
        with redirect_stdout(captured_output):
            exec(code, exec_env)
            
        charts_found = glob.glob(os.path.join(state["chart_dir"], "chart_*.png"))
        captured_preview = captured_output.getvalue().strip()
        if captured_preview:
            st.success(f"✅ 代码执行成功！共生成图表: {len(charts_found)} 张")
        else:
            st.warning("⚠️ 代码未输出任何分析数据！")
    except Exception as e:
        error_msg = str(e)
        st.error(f"❌ 执行报错：{error_msg}")
        
    return {
        "execution_logs": captured_output.getvalue(),
        "error_msg": error_msg,
        "attempt": state["attempt"] + 1
    }

def node_reflector(state: AgentState) -> dict:
    llm = ChatOpenAI(temperature=0, model="deepseek-v3-0324", api_key=state["api_key"], base_url=state["api_base"])
    prompt = ChatPromptTemplate.from_messages([
        ("system", DA_REFLECT_SYSTEM),
        ("user", "报错信息: {error}\n\n出错代码片段:\n{code}")
    ])
    
    # 使用上一步的 Pydantic 锁
    structured_llm = llm.with_structured_output(CodeReflection)
    try:
        reflection_obj = structured_llm.invoke(
            prompt.format_messages(error=state["error_msg"], code=state["generated_code"][-2000:])
        )
        reflection = {
            "attempt": state["attempt"], 
            "error": state["error_msg"], 
            "root_cause": reflection_obj.root_cause, 
            "fix_strategy": reflection_obj.fix_strategy, 
            "avoid": reflection_obj.avoid
        }
    except Exception as parse_e:
        reflection = {
            "attempt": state["attempt"], "error": state["error_msg"],
            "root_cause": "解析失败", "fix_strategy": "请检查变量名或使用 try-except 跳过错误", "avoid": "避免复杂链式调用"
        }
    
    return {"reflections": state["reflections"] + [reflection]}

def node_analyst(state: AgentState) -> dict:
    # 如果是因为重试耗尽而进来，直接生成中断报告
    if state["error_msg"] and state["attempt"] >= state["max_retries"]:
        return {"final_markdown": f"<h2>⚠️ 数据分析中断</h2><pre>{state['error_msg']}</pre>"}
        
    st.markdown("### 🧑‍💼 分析师 Agent 正在撰写最终多表融合洞察报告...")
    llm = ChatOpenAI(temperature=0.3, model="deepseek-v3-0324", api_key=state["api_key"], base_url=state["api_base"])
    prompt = ChatPromptTemplate.from_messages([("system", DA_ANALYST_SYSTEM), ("user", "原需求：{query}")])
    
    generated_charts = glob.glob(os.path.join(state["chart_dir"], "chart_*.png"))
    chart_status = f"生成的图表文件有：{[os.path.basename(c) for c in generated_charts]}。"
    
    final_markdown = ""
    try:
        raw_report = ""
        report_placeholder = st.empty()
        count = 0
        for chunk in (prompt | llm).stream({
            "analysis_plan": state["plan"], "data_insights": state["execution_logs"],
            "chart_status": chart_status, "query": state["user_query"]
        }):
            raw_report += chunk.content
            count += 1
            if count % 8 == 0: report_placeholder.markdown(raw_report + "▌")
        report_placeholder.markdown(raw_report)
            
        match = re.search(r'<FINAL_REPORT>\s*(.*?)\s*</FINAL_REPORT>', raw_report, re.DOTALL)
        final_markdown = match.group(1).strip() if match else raw_report.strip()
    except Exception as e:
        final_markdown = f"报告生成失败: {e}"
        
    return {"final_markdown": final_markdown}

def router_after_execution(state: AgentState) -> Literal["reflector", "analyst"]:
    """条件路由：报错且有剩余重试次数 -> 走反思节点；否则 -> 走最终报告节点"""
    if state["error_msg"] and state["attempt"] < state["max_retries"]:
        return "reflector"
    return "analyst"


# ==========================================
# 3. 核心主入口：构建与运行 Graph
# ==========================================
def run_agent_pipeline(dfs: dict, user_query: str, api_key: str, api_base: str):
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_out = os.path.join(str(core.paths.GLOBAL_DATA_DIR), f"数据分析报告_{current_time}.html")

    # --- 1. 数据预处理 (完全保留你的精细化清洗逻辑) ---
    cleaned_dfs = {}
    dataset_info_list = []
    for table_name, df in dfs.items():
        df.dropna(how='all', inplace=True)
        df.dropna(axis=1, how='all', inplace=True)
        df = df.loc[:, ~df.columns.astype(str).str.contains('^Unnamed')]
        df.columns = df.columns.astype(str).str.strip().str.replace('\n', '').str.replace('\r', '').str.replace('　', '')
        if df.empty or len(df.columns) == 0: continue 
            
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].replace(['-', '--', '无', 'N/A', 'NA', 'null', ''], pd.NA)
                temp_col = df[col].astype(str).str.replace(r'[¥$,\s]', '', regex=True)
                converted = pd.to_numeric(temp_col, errors='coerce')
                if converted.notna().mean() > 0.5:
                    df[col] = converted
                    
        cleaned_dfs[table_name] = df
        cols_str = ", ".join(df.columns)
        sample_str = df.head(3).fillna("空值(NaN)").to_string()
        dataset_info_list.append(f"📦【表名】: {table_name}\n【字段】: {cols_str}\n【数据样本】:\n{sample_str}\n")
        
    if not cleaned_dfs:
        error_html = "<h2 style='color:red;'>❌ 数据处理失败</h2><p>所有上传的表格均无有效数据。</p>"
        with open(report_out, "w", encoding="utf-8") as f: f.write(error_html)
        return error_html, report_out, {}
        
    dataset_summary = "\n".join(dataset_info_list)
    if not user_query or not user_query.strip():
        user_query = "请对环境中加载的所有数据表进行全面扫描。尝试寻找可以关联（merge）的维度进行深入挖掘，并分别输出核心图表。"
        st.info("💡 用户未输入需求，系统将开启多表默认探索模式。")

    chart_dir = tempfile.mkdtemp(prefix="agent_charts_")

    # --- 2. 组装 LangGraph 状态机 ---
    workflow = StateGraph(AgentState)
    workflow.add_node("planner", node_planner)
    workflow.add_node("coder", node_coder)
    workflow.add_node("executor", node_executor)
    workflow.add_node("reflector", node_reflector)
    workflow.add_node("analyst", node_analyst)
    
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "coder")
    workflow.add_edge("coder", "executor")
    workflow.add_conditional_edges("executor", router_after_execution, {"reflector": "reflector", "analyst": "analyst"})
    workflow.add_edge("reflector", "coder") # 闭环重试
    workflow.add_edge("analyst", END)
    
    # 1. 注入记忆体，并设置【断点拦截】：在执行沙盒节点（executor）之前，强行暂停图的流转！
    app = workflow.compile()

    # --- 3. 运行图状态机 ---
    initial_state = {
        "dfs": cleaned_dfs, "dataset_summary": dataset_summary, "user_query": user_query,
        "chart_dir": chart_dir, "api_key": api_key, "api_base": api_base,
        "plan": "", "generated_code": "", "execution_logs": "", "error_msg": "",
        "reflections": [], "attempt": 0, "max_retries": 3, "final_markdown": ""
    }
    
    # 3. 设置当前会话的记忆 ID
    thread_config = {"configurable": {"thread_id": "demo_user_task_001"}}
    
    # 4. 把 原材料(initial_state) 和 记忆卡(config) 一起塞进机器启动！
    final_state = app.invoke(initial_state)

    # --- 4. 提取结果，保存报告 (完全保留原返回格式) ---
    final_markdown = final_state["final_markdown"]
    
    if final_state["error_msg"] and final_state["attempt"] >= final_state["max_retries"]:
        with open(report_out, "w", encoding="utf-8") as f: f.write(final_markdown)
        return final_markdown, report_out, {} 
        
    for src in glob.glob(os.path.join(chart_dir, "chart_*.png")):
        shutil.copy2(src, os.path.basename(src))

    html_string = generate_html_report(final_markdown, report_out)
    return html_string, report_out, {"plan": final_state["plan"], "data": final_state["execution_logs"]}

# 追问模块 (无需改动)
def run_followup_chat(user_query: str, chat_history: list, context_data: dict, api_key: str, api_base: str):
    llm_chat = ChatOpenAI(temperature=0.4, model="deepseek-v3-0324", api_key=api_key, base_url=api_base)
    messages = [("system", DA_FOLLOWUP_SYSTEM.format(data=context_data.get("data", "无数据")))]
    for msg in chat_history: messages.append((msg["role"], msg["content"]))
    messages.append(("user", user_query))
    prompt = ChatPromptTemplate.from_messages(messages)
    return (prompt | llm_chat).stream({})