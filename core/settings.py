# core/settings.py
import os
import core.paths
from dotenv import load_dotenv

# 加载全局环境变量
load_dotenv(core.paths.ENV_FILE)

class Settings:
    # 全局 API 密钥与地址
    API_KEY = os.getenv("INTERNAL_API_KEY")
    API_BASE = os.getenv("INTERNAL_API_BASE")
    INTERNAL_URL=os.getenv("INTERNAL_URL")
    
    # 语言模型配置 (带默认值兜底)
    MODEL_TEXT = os.getenv("MODEL_TEXT", "deepseek-v3-0324")
    MODEL_VISION = os.getenv("MODEL_VISION", "deepseek-v3-0324")
    MODEL_BLUE = os.getenv("MODEL_BLUE", "deepseek-v3-0324")
    MODEL_RED = os.getenv("MODEL_RED", "deepseek-v3-0324")
    MODEL_EDITOR = os.getenv("MODEL_EDITOR", "deepseek-v3-0324")
    MODEL_CODER=os.getenv("MODEL_CODER","qwen3-coder-480b-a35b-instruct")
    proxy_url=os.getenv("proxy_url")
    
    # 向量与重排模型配置
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3") 
    RERANK_MODEL = os.getenv("RERANK_MODEL", "bge-reranker-v2-m3")

# 实例化一个单例供全站使用
settings = Settings()