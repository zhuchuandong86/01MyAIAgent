import requests
from typing import Sequence, Optional
from langchain_core.documents import Document
from langchain_core.callbacks import Callbacks
from langchain_classic.retrievers.document_compressors.base import BaseDocumentCompressor
from langchain_classic.retrievers import ContextualCompressionRetriever

# 【修复】：使用绝对导入
from modules.rag.config import Config

class InternalAPIReranker(BaseDocumentCompressor):
    def compress_documents(self, documents: Sequence[Document], query: str, callbacks: Optional[Callbacks] = None) -> Sequence[Document]:
        if not documents:
            return []
            
        texts = [doc.page_content for doc in documents]
        
        payload = {
            "model": Config.RERANK_MODEL,
            "query": query,
            "documents": texts, 
            "top_n": int(Config.RERANK_TOP_K)
        }
        
        headers = {"Authorization": f"Bearer {Config.INTERNAL_API_KEY}"}
        url = f"{Config.INTERNAL_BASE_URL}/rerank"
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result_data = response.json()
            
            reranked_results = result_data.get("results", [])
            final_docs = []
            for res in reranked_results:
                idx = res.get("index")
                if idx is not None:
                    doc = documents[idx]
                    doc.metadata["relevance_score"] = res.get("score")
                    final_docs.append(doc)
            return final_docs
        except Exception as e:
            return documents[:Config.RERANK_TOP_K]

def build_rerank_retriever(base_retriever):
    return ContextualCompressionRetriever(base_compressor=InternalAPIReranker(), base_retriever=base_retriever)