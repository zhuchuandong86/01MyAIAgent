# pages/12_💬_双核对话大厅.py
import streamlit as st
import sqlite3
import os
from datetime import datetime
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_community.callbacks.manager import get_openai_callback
import core.paths

st.set_page_config(page_title="双核对话大厅", page_icon="💬", layout="wide")

# ==========================================
# 1. 数据库设置 (长短期平行记忆隔离引擎)
# ==========================================
DB_PATH = core.paths.get_db_path("chat_memory.db")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS dual_chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                track TEXT,     -- 取值为 'USER', 'A', 'B'
                role TEXT,      -- 取值为 'user', 'assistant'
                content TEXT,
                timestamp DATETIME
            )
        ''')
init_db()

def get_history(user_id, track, limit=10):
    """
    获取指定用户、指定脑区(左/右)的对话记忆。
    确保 A 模型不会读取到 B 模型的历史回复，防止人格分裂。
    """
    with sqlite3.connect(DB_PATH) as conn:
        query = '''
            SELECT role, content FROM dual_chat_history 
            WHERE user_id = ? AND (track = 'USER' OR track = ?)
            ORDER BY id ASC
        '''
        df = conn.execute(query, (user_id, track)).fetchall()
        # limit 代表携带的轮数 (一轮包含 user+assistant 2条)，所以乘 2
        return df[-(limit * 2):] if limit else df

def save_message(user_id, track, role, content):
    """持久化保存至长期记忆库"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO dual_chat_history (user_id, track, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, track, role, content, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )

def clear_memory(user_id):
    """清除指定用户的长期记忆"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM dual_chat_history WHERE user_id = ?", (user_id,))

# ==========================================
# 2. 侧边栏与身份识别
# ==========================================
with st.sidebar:
    st.header("👤 身份与记忆隔离")
    st.info("💡 输入的 ID，继承历史对话。")
    # 模拟 IP 或用户隔离，让用户自己指定身份标识
    user_id = st.text_input("您的专属身份 ID (User ID)", value="Guest_01")
    
    st.header("⚙️ 双核引擎配置")
    model_a = st.text_input("🔵 左脑模型 (Model A)", value=settings.MODEL_TEXT or "deepseek-v3-0324")
    model_b = st.text_input("🔴 右脑模型 (Model B)", value=settings.MODEL_RED or "qwen2.5-72b-instruct")
    
    memory_limit = st.slider("🧠 短期记忆携带轮数", min_value=0, max_value=50, value=10, help="传给大模型的上下文轮数。设为0则每次都是全新对话。")
    
    if st.button("🧹 清空该 ID 的所有记忆", use_container_width=True):
        clear_memory(user_id)
        st.toast("✅ 记忆已彻底清除！")
        st.rerun()

st.title("💬 双核记忆对话大厅 (A/B Test)")
st.markdown("设定专属背景，输入问题，**双模型同时作答**，且各自拥有平行的上下文记忆线！基于您的 User ID 实现长短期记忆隔离。")

# ==========================================
# 3. 顶部：背景设定 (System Prompt)
# ==========================================
with st.expander("🎭 设定全局背景 / System Prompt (留空则为标准对话)", expanded=True):
    sys_prompt = st.text_area(
        "告诉模型它扮演什么角色或遵循什么规则：", 
        placeholder="例如：你是一个精通 Python 的架构师；或者你是一个严厉的高中老师，只能用文言文回答...", 
        height=80
    )

st.divider()

# ==========================================
# 4. 主干：对话历史渲染
# ==========================================
# 读取该用户所有的历史对话用于前端页面展示
with sqlite3.connect(DB_PATH) as conn:
    all_msgs = conn.execute(
        "SELECT track, role, content FROM dual_chat_history WHERE user_id = ? ORDER BY id ASC", 
        (user_id,)
    ).fetchall()

# 将线性数据重构为“回合(Turn)”制：包含一个用户提问，和A/B两个回答
turns = []
current_turn = None
for track, role, content in all_msgs:
    if role == 'user':
        if current_turn:
            turns.append(current_turn)
        current_turn = {'user': content, 'A': '', 'B': ''}
    else:
        if current_turn is not None:
            current_turn[track] = content
if current_turn:
    turns.append(current_turn)

# 渲染历史 UI
for turn in turns:
    with st.chat_message("user"):
        st.write(turn['user'])
    
    col_hist_a, col_hist_b = st.columns(2)
    with col_hist_a:
        if turn.get('A'):
            with st.chat_message("assistant", avatar="🔵"):
                st.write(turn['A'])
    with col_hist_b:
        if turn.get('B'):
            with st.chat_message("assistant", avatar="🔴"):
                st.write(turn['B'])

# ==========================================
# 5. 用户输入与大模型并发调用
# ==========================================
if prompt := st.chat_input(f"以 {user_id} 的身份发言..."):
    # 1. 保存用户的提问到持久化数据库
    save_message(user_id, 'USER', 'user', prompt)
    
    # 2. 在界面上直接渲染刚刚输入的问题
    with st.chat_message("user"):
        st.write(prompt)
        
    # 3. 准备获取该用户平行宇宙的上下文记忆
    history_a = get_history(user_id, 'A', limit=memory_limit) 
    history_b = get_history(user_id, 'B', limit=memory_limit)
    
    def build_langchain_messages(hist, sys_p, current_prompt):
        msgs = []
        if sys_p.strip():
            msgs.append(SystemMessage(content=sys_p))
        for r, c in hist:
            if r == 'user':
                msgs.append(HumanMessage(content=c))
            else:
                msgs.append(AIMessage(content=c))
        msgs.append(HumanMessage(content=current_prompt))
        return msgs

    messages_a = build_langchain_messages(history_a, sys_prompt, prompt)
    messages_b = build_langchain_messages(history_b, sys_prompt, prompt)

    col_a, col_b = st.columns(2)
    
    # 4. 封装流式对话与计费记录器
    def run_chat_stream(model_name, container, messages, track_name, avatar_emoji):
        with container:
            with st.chat_message("assistant", avatar=avatar_emoji):
                st.caption(f"`{model_name}`")
                placeholder = st.empty()
                
                llm = ChatOpenAI(
                    model=model_name,
                    api_key=settings.API_KEY,
                    base_url=settings.API_BASE,
                    temperature=0.7,
                    model_kwargs={"stream_options": {"include_usage": True}}
                )
                
                full_text = ""
                with get_openai_callback() as cb:
                    try:
                        for chunk in llm.stream(messages):
                            full_text += chunk.content
                            placeholder.markdown(full_text + " ▌")
                        placeholder.markdown(full_text)
                        
                        # 记录回答至长期记忆
                        save_message(user_id, track_name, 'assistant', full_text)
                        
                        # 计费拦截写入
                        tokens = cb.total_tokens
                        if tokens == 0:
                            tokens = int(len(str(messages)) + len(full_text) * 1.2)
                        log_usage("双核记忆对话", model_name, tokens)
                        
                    except Exception as e:
                        placeholder.error(f"❌ 请求失败: {e}")
                        save_message(user_id, track_name, 'assistant', f"[生成失败: {e}]")

    # 依次唤起左脑和右脑开始流式输出
    with st.spinner(f"正在等待 {model_a} 回复..."):
        run_chat_stream(model_a, col_a, messages_a, 'A', "🔵")
    
    with st.spinner(f"正在等待 {model_b} 回复..."):
        run_chat_stream(model_b, col_b, messages_b, 'B', "🔴")
        
    # 流式播放完毕后刷新一次界面，使历史对话块被完全固化
    st.rerun()
