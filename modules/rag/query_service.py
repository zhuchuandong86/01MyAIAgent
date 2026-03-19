# modules/rag/query_service.py
import os
import pickle
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_classic.retrievers import EnsembleRetriever

# 【修复】：使用绝对导入
from modules.rag.config import Config 
from modules.rag.reranker import build_rerank_retriever 
# 👇【新增】：导入中台统管的 RAG 提示词
from core.prompts import RAG_SYSTEM_PROMPT

os.environ['NO_PROXY'] = 'api.openai.rnd.huawei.com'

def format_docs(docs):
    formatted_texts = []
    for i, doc in enumerate(docs):
        page = doc.metadata.get('page', '1')
        source = os.path.basename(doc.metadata.get('source', '未知'))
        # 👇【修改1】：加入 [1] [2] 序号，这是强溯源防幻觉的核心锚点！
        formatted_texts.append(f"[{i+1}] 【来源: {source} | 第{page}页】\n{doc.page_content}")
    return "\n\n".join(formatted_texts)
    
def build_query_chain():
    if not os.path.exists(Config.DB_DIR):
        raise FileNotFoundError(f"找不到数据库 {Config.DB_DIR}，请先运行 batch_ingest.py 入库！")
        
    with open(os.path.join(Config.DB_DIR, "bm25_index.pkl"), "rb") as f:
        bm25_retriever = pickle.load(f)
        # 👇【修改2.1】：撒大网，强行放大 BM25 召回量至 15
        bm25_retriever.k = Config.RETRIEVER_TOP_K   
        
    embeddings = OpenAIEmbeddings(
        model=Config.EMBEDDING_MODEL,
        api_key=Config.INTERNAL_API_KEY,
        base_url=Config.INTERNAL_BASE_URL,
        check_embedding_ctx_length=False 
    )
    vectorstore = FAISS.load_local(Config.DB_DIR, embeddings, allow_dangerous_deserialization=True)
    # 👇【修改2.2】：撒大网，强行放大 FAISS 向量召回量至 15，防止数据被挤掉
    faiss_retriever = vectorstore.as_retriever(search_kwargs={"k": Config.RETRIEVER_TOP_K})
    
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, faiss_retriever],
        weights=[0.5, 0.5]
    )
    
    # Reranker 会自动把上面 30 个粗排结果重新打分，压成最精准的 3~5 个
    final_retriever = build_rerank_retriever(ensemble_retriever)
    
    # 👇【修改3】：不再写死，引入 core.prompts 中的全局金牌提示词，并且切分系统与用户角色
    prompt = ChatPromptTemplate.from_messages([
        ("system", RAG_SYSTEM_PROMPT),
        ("user", "{question}")
    ])
    
    llm = ChatOpenAI(
        model=Config.MODEL_NAME,
        api_key=Config.INTERNAL_API_KEY,
        base_url=Config.INTERNAL_BASE_URL,
        temperature=0.1 
    )
    
    rag_chain = (
        {"context": final_retriever | format_docs, "question": RunnablePassthrough()}
        | prompt          
        | llm              
        | StrOutputParser() 
    )
    
    return rag_chain, final_retriever