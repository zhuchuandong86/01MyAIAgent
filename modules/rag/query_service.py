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
os.environ['NO_PROXY'] = 'api.openai.rnd.huawei.com'

def format_docs(docs):
    formatted_texts = []
    for i, doc in enumerate(docs):
        page = doc.metadata.get('page', '1')
        source = os.path.basename(doc.metadata.get('source', '未知'))
        formatted_texts.append(f"【参考来源: {source} | 第{page}页】\n{doc.page_content}")
    return "\n\n".join(formatted_texts)
    
def build_query_chain():
    if not os.path.exists(Config.DB_DIR):
        raise FileNotFoundError(f"找不到数据库 {Config.DB_DIR}，请先运行 batch_ingest.py 入库！")
        
    with open(os.path.join(Config.DB_DIR, "bm25_index.pkl"), "rb") as f:
        bm25_retriever = pickle.load(f)
        
    embeddings = OpenAIEmbeddings(
        model=Config.EMBEDDING_MODEL,
        api_key=Config.INTERNAL_API_KEY,
        base_url=Config.INTERNAL_BASE_URL,
        check_embedding_ctx_length=False 
    )
    vectorstore = FAISS.load_local(Config.DB_DIR, embeddings, allow_dangerous_deserialization=True)
    faiss_retriever = vectorstore.as_retriever(search_kwargs={"k": Config.RETRIEVER_TOP_K})
    
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, faiss_retriever],
        weights=[0.5, 0.5]
    )
    
    final_retriever = build_rerank_retriever(ensemble_retriever)
    
    prompt = ChatPromptTemplate.from_template("""
你是一个专业的智能助理。请严格基于以下提供的参考资料来解答用户的疑问。
参考资料:
{context}

用户问题: {question}
回答:
在回答的末尾，请注明参考的文件名和页码
""")
    
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