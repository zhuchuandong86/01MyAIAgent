import streamlit as st
import os
import json

# 【必加】：引入全局路径管家
import core.paths
from modules.rag.config import Config
from modules.rag.file_processor import get_file_md5
from modules.rag.batch_ingest import ingest_single_file, delete_single_file, rebuild_index_from_md
from modules.rag.query_service import build_query_chain
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from core.token_tracker import log_usage
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import RAG_SYSTEM_PROMPT

# 🌟 新增：引入工厂与模板
from core.llm_factory import get_llm
from langchain_core.prompts import ChatPromptTemplate

st.set_page_config(page_title="RAG 企业智库", page_icon="🧠", layout="wide")

@st.cache_resource
def get_rag_chain_and_retriever():
    try:
        return build_query_chain()
    except Exception as e:
        return None, None

rag_chain, retriever = get_rag_chain_and_retriever()

def generate_ai_filename(original_name):
    try:
        # 这里为了不干扰原来的逻辑，暂时保留原写法，后续也可换成 get_llm
        llm = ChatOpenAI(model=Config.MODEL_NAME, api_key=Config.INTERNAL_API_KEY, base_url=Config.INTERNAL_BASE_URL, temperature=0.7)
        prompt = f"请根据原文件名 '{original_name}'，生成一个简短且规范的中文标题名（只输出名字本身，不要带扩展名，不要任何解释）。"
        new_name = llm.invoke(prompt).content.strip()
        ext = os.path.splitext(original_name)[-1]
        return new_name + ext
    except:
        return original_name

def get_ingested_files():
    if os.path.exists(Config.DB_DIR) and os.path.exists(os.path.join(Config.DB_DIR, "index.faiss")):
        try:
            embeddings = OpenAIEmbeddings(
                model=Config.EMBEDDING_MODEL, api_key=Config.INTERNAL_API_KEY, 
                base_url=Config.INTERNAL_BASE_URL, check_embedding_ctx_length=False 
            )
            vectorstore = FAISS.load_local(Config.DB_DIR, embeddings, allow_dangerous_deserialization=True)
            sources = {}
            for doc in vectorstore.docstore._dict.values():
                src = doc.metadata.get("source")
                if src and src not in sources.values():
                    md5_key = get_file_md5(src) if os.path.exists(src) else src
                    sources[md5_key] = src
            return sources
        except Exception as e:
            pass
            
    if os.path.exists(Config.PROCESSED_RECORD_FILE):
        with open(Config.PROCESSED_RECORD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def reload_knowledge_base():
    if "rag_chain_obj" in st.session_state:
        del st.session_state["rag_chain_obj"]

# ==========================================
# 侧边栏：文件管理与入库 (完全保留你的原版代码)
# ==========================================
with st.sidebar:
    st.title("📚 知识库中心")
    # st.subheader("📂 已存文档")
    ingested_data = get_ingested_files()
    
    if ingested_data:
        for md5_key, path in ingested_data.items():
            col1, col2 = st.columns([4, 1])
            col1.markdown(f"📄 **{os.path.basename(path)}**")
            if col2.button("❌", key=f"del_{md5_key}"):
                with st.spinner("删除记录中（保留 MD 备份）..."):
                    delete_single_file(md5_key)
                    reload_knowledge_base()
                st.success("删除成功！重新入库请手动上传备份的 MD 文件。")
                st.rerun()
    else:
        st.info("暂无数据")
    
    st.divider()
    st.subheader("📤 上传并入库")
    
    uploaded_file = st.file_uploader("选择文档", type=['pdf', 'docx', 'doc', 'png', 'jpg', 'txt', 'md'])
    
    if uploaded_file:
        temp_dir = str(core.paths.UPLOAD_DIR)
        smart_filename = uploaded_file.name
        temp_path = os.path.join(temp_dir, smart_filename)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        is_exist = any(smart_filename in p for p in ingested_data.values())
        
        if is_exist:
            st.warning(f"文件 `{smart_filename}` 已存在。")
            if st.button("🔥 覆盖导入"):
                with st.spinner("重构索引中..."):
                    status = ingest_single_file(temp_path, force_overwrite=True)
                    if status == "SUCCESS":
                        reload_knowledge_base()
                        st.success("覆盖完成！")
                        st.rerun() 
                    else:
                        st.error("解析失败。")
        else:
            if st.button(f"✅ 确认入库 ({smart_filename})"):
                with st.spinner("解析并算向量中... (若已在其它模块解析过，将极速秒读)"):
                    status = ingest_single_file(temp_path)
                    if status == "SUCCESS":
                        reload_knowledge_base()
                        st.success("入库成功！")
                        st.rerun() 
                    else:
                        st.error("入库失败。")

# ==========================================
# 主界面：强溯源对话终端
# ==========================================
st.title("🤖 智能对话终端 (RAG 强溯源版)")

if "rag_messages" not in st.session_state:
    st.session_state.rag_messages = []

if "rag_chain_obj" not in st.session_state:
    try:
        st.session_state.rag_chain_obj, st.session_state.rag_retriever_obj = build_query_chain()
    except:
        st.info("💡 请先在左侧入库文档以激活搜索。")

# 渲染历史消息与溯源角标对齐
for msg in st.session_state.rag_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg and msg["sources"]:
            with st.expander("🔍 原始引用片段"):
                for idx, doc in enumerate(msg["sources"]):
                    page_info = f" - 第{doc.metadata.get('page')}页" if 'page' in doc.metadata else ""
                    st.caption(f"**[{idx+1}] 来源：{os.path.basename(doc.metadata.get('source', '未知'))}{page_info}**")
                    st.info(doc.page_content)

if prompt := st.chat_input("关于您的文档，想问点什么？"):
    st.session_state.rag_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        if "rag_retriever_obj" in st.session_state and st.session_state.rag_retriever_obj is not None:  
            with st.spinner("全库极速检索中..."):
                # 1. 仅调用 retriever 召回文档
                source_docs = st.session_state.rag_retriever_obj.invoke(prompt)
                
            if not source_docs:
                st.info("未能在知识库中匹配到相关内容。")
                st.stop()
                
            # 2. 构建带 [1][2] 角标的严格上下文
            context_str = ""
            for i, doc in enumerate(source_docs):
                doc_name = os.path.basename(doc.metadata.get('source', '未知'))
                page_info = f" - 第{doc.metadata.get('page')}页" if 'page' in doc.metadata else ""
                context_str += f"[{i+1}] 来源文档: {doc_name}{page_info}\n内容片段: {doc.page_content}\n\n"

            # 3. 设置极严苛的防幻觉 Prompt
            # system_prompt = """你是一个严谨的企业级知识库问答助手。
            # 请严格基于以下【检索到的知识片段】回答用户的问题。
            
            # 【核心规则】
            # 1. 必须且只能使用给定的知识片段中的信息回答。严禁自己编造或凭空扩展！
            # 2. **强制溯源标注**：在回答的每一个关键数据或结论后，必须使用方括号标注对应的信息来源编号，例如 [1], [2]。
            
            # 【检索到的知识片段】
            # {context}"""
            
            chat_template = ChatPromptTemplate.from_messages([
                ("system", RAG_SYSTEM_PROMPT),
                ("user", "{query}")
            ])
            
            # 🌟 4. 使用第一步写好的 LLM 工厂获取大模型
            llm = get_llm(model_name=Config.MODEL_NAME, temperature=0.1)
            
            placeholder = st.empty()
            full_response = ""
            
            with get_openai_callback() as cb:
                try:
                    # 5. 流式输出带有 [1][2] 的严谨答案
                    for chunk in (chat_template | llm).stream({"context": context_str, "query": prompt}):
                        full_response += chunk.content
                        placeholder.markdown(full_response + " ▌")
                    placeholder.markdown(full_response)
                    
                    # 计费拦截
                    log_usage("企业RAG智库(强溯源)", Config.MODEL_NAME, cb.total_tokens)
                    
                except Exception as e:
                    placeholder.error(f"❌ 生成失败: {e}")
                    
            # 6. 立刻在当前气泡下方渲染溯源卡片，供用户对照
            with st.expander("🔍 展开查看原文 (点击核对真伪)"):
                for idx, doc in enumerate(source_docs):
                    page_info = f" - 第{doc.metadata.get('page')}页" if 'page' in doc.metadata else ""
                    st.caption(f"**[{idx+1}] 来源：{os.path.basename(doc.metadata.get('source', '未知'))}{page_info}**")
                    st.info(doc.page_content)
            
            st.session_state.rag_messages.append({
                "role": "assistant", 
                "content": full_response, 
                "sources": source_docs
            })
        else:
            st.error("知识库未就绪。请先在左侧上传文件。")
