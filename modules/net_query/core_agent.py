# core_agent.py
import os
import re
import yaml
import json
import duckdb
import csv
import requests  # 新增：用于发送纯 HTTP 请求到内网模型
from typing import List
from datetime import datetime
from langchain_openai import ChatOpenAI
from core.paths import get_db_path, get_config_path

# 引入向量库相关组件（FAISS 在本地运行，不需要外网）
from langchain_community.vectorstores import FAISS        
from langchain_core.documents import Document     
from langchain_core.embeddings import Embeddings  
from core.token_tracker import log_usage
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import NET_QUERY_SYSTEM_PROMPT

# ==========================================
# 1. 核心配置与常量
# ==========================================

from dotenv import load_dotenv
load_dotenv()
INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "未配置API_BASE")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "未配置API_KEY")
INTERNAL_URL=os.getenv("INTERNAL_URL")
os.environ['NO_PROXY'] = INTERNAL_URL


# 【新增】：内网 Embedding 模型的配置
# 如果内网 Embedding 接口和大模型是同一个地址，直接沿用即可；如果不同，请替换！
EMBEDDING_API_BASE = INTERNAL_API_BASE 
EMBEDDING_API_KEY = INTERNAL_API_KEY   
EMBEDDING_MODEL_NAME = "bge-m3"  # 请确认你们内网 Embedding 模型的调用名称

from core.paths import get_db_path, get_upload_path, get_config_path
DB_PATH = get_db_path("telecom_data.duckdb")
LOG_PATH = get_upload_path("query_logs.csv")

# ==========================================
# 2. 自定义内网 Embedding 调用类（100% 免疫网络报错）
# ==========================================
class IntranetEmbeddings(Embeddings):
    """自定义的 Embedding 类，纯 HTTP 请求，绝对不会触发本地下载和 tiktoken 校验"""
    def __init__(self, api_url: str, api_key: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        # 自动补全 OpenAI 标准的 embeddings 路径
        if not self.api_url.endswith("/embeddings"):
            self.api_url += "/embeddings" if self.api_url.endswith("/v1") else "/v1/embeddings"
        self.api_key = api_key
        self.model_name = model_name

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {"input": texts, "model": self.model_name}
        try:
            # 发送数据到内网计算向量
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]
        except Exception as e:
            print(f"❌ 内网 Embedding API 调用失败: {e}")
            # 即使失败也返回一个零向量，确保程序不会崩溃停止 (BGE-M3 通常是 1024 维)
            return [[0.0] * 1024 for _ in texts] 

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

# ==========================================
# 3. 通用安全与日志拦截器
# ==========================================
def sanitize_sql(sql):
    if re.search(r'(?i)\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE)\b', sql):
        raise ValueError("安全拦截：禁止执行此类破坏性 SQL！")
    if not re.search(r'(?i)\b(SUM|COUNT|AVG|MAX|MIN|GROUP BY)\b', sql) and not re.search(r'(?i)\bLIMIT\b', sql):
        sql = sql.strip().rstrip(';') + " LIMIT 1000"
    return sql

def log_query_action(question, sql, status, error_msg=""):
    try:
        file_exists = os.path.isfile(LOG_PATH)
        with open(LOG_PATH, mode='a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            if not file_exists: 
                writer.writerow(["时间", "用户问题", "执行SQL", "状态", "报错信息"])
            writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), question, sql, status, error_msg])
    except Exception as e:
        pass

# ==========================================
# 4. 核心 Agent 大脑
# ==========================================
class VisualTelecomAnalyst:
    def __init__(self):
        self.llm = ChatOpenAI(
            openai_api_key=INTERNAL_API_KEY,
            openai_api_base=INTERNAL_API_BASE,
            model_name="deepseek-v3-0324",
            temperature=0.0  
        )
        
        # 【新增】：初始化我们的纯净版内网 Embedding 模型
        self.embeddings = IntranetEmbeddings(
            api_url=EMBEDDING_API_BASE,
            api_key=EMBEDDING_API_KEY,
            model_name=EMBEDDING_MODEL_NAME
        )
        
        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(f"找不到数据库 {DB_PATH}，请先运行 build_db.py！")
        self.con = duckdb.connect(DB_PATH, read_only=True)
        
        # ==========================================
        # 修复后的 YAML 读取逻辑
        # ==========================================
        yaml_path = get_config_path("schema.yaml")
             
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
                self.golden_sqls = self.config.get("golden_sqls", [])
            # 【增加强提示】：在终端打印读取结果，防止静默失败
            print(f"✅ 成功从 {os.path.basename(yaml_path)} 读取了 {len(self.golden_sqls)} 条黄金案例！")
        except FileNotFoundError:
            print(f"❌ 严重警告：找不到任何 YAML 配置文件，AI 将失去参考记忆！")
            self.config = {}
            self.golden_sqls = []
        except Exception as e:
            print(f"❌ YAML 文件解析失败: {e}")
            self.config = {}
            self.golden_sqls = []

        # 👇 【将旧的算向量代码替换为以下持久化极速版】：
        self.vector_store = None
        if self.golden_sqls:
            # 定义本地向量库的存储路径 (存放到 global_data/databases/ 下)
            faiss_dir = get_db_path("telecom_golden_sql_faiss")
            
            if os.path.exists(faiss_dir):
                # ⚡ 极速模式：如果硬盘上已经有了，直接 0.01 秒秒读，不调 API！
                print("⚡ [无线问数] 极速命中本地 SQL 向量库缓存...")
                self.vector_store = FAISS.load_local(faiss_dir, self.embeddings, allow_dangerous_deserialization=True)
            else:
                # ⏳ 只有真正第一次运行，或者你删了缓存文件夹，才会去调模型算向量
                print("⏳ [无线问数] 首次启动：正在调用内网模型计算 SQL 向量库...")
                docs = [Document(page_content=item['question'], metadata={"sql": item['sql']}) for item in self.golden_sqls]
                self.vector_store = FAISS.from_documents(docs, self.embeddings)
                # 算完立刻存入硬盘，一劳永逸！
                self.vector_store.save_local(faiss_dir)

    def get_real_schema(self):
        tables = self.con.execute("SHOW TABLES").df()['name'].tolist()
        context = ""
        for t in tables:
            cols = self.con.execute(f"DESCRIBE {t}").df()['column_name'].tolist()
            context += f"表名: {t} | 列名: {', '.join(cols)}\n"
        return context

    def retrieve_golden_sqls(self, user_query, top_k=2):
        """【恢复为高级向量检索】：使用 FAISS 在本地搜索最匹配的 SQL"""
        if not self.vector_store: return "无历史参考案例。"
        
        # 通过向量距离找到语义最相近的问题
        similar_docs = self.vector_store.similarity_search(user_query, k=top_k)
        
        best_examples = ""
        for i, doc in enumerate(similar_docs):
            best_examples += f"[案例 {i+1}]\n问题: {doc.page_content}\nSQL: {doc.metadata['sql']}\n\n"
        return best_examples.strip()

    def get_latest_table(self, prefix="join_all_kpi_table_region"):
        """扫描数据库，找到日期后缀最大的表名"""
        try:
            # 获取所有表名
            tables = self.con.execute("SHOW TABLES").df()['name'].tolist()
            # 筛选出符合前缀的表，并提取最后的数字进行排序
            target_tables = [t for t in tables if t.startswith(prefix)]
            if not target_tables:
                return prefix + "202511"  # 如果没找到，返回一个默认值
            
            # 按名称排序，取最后一个（例如 202511 会排在 202510 后面）
            latest_table = sorted(target_tables)[-1]
            return latest_table
        except Exception:
            return prefix + "202511"

    def run_workflow(self, user_query, history=[]):
        current_schema = self.get_real_schema()
        few_shot_examples = self.retrieve_golden_sqls(user_query)
        latest_kpi_table = self.get_latest_table()
        
        # 包含了之前刚刚为你优化的 多维对比规则 和 并排查询规则
        # 使用 .format() 动态注入变量
        system_prompt = NET_QUERY_SYSTEM_PROMPT.format(
            current_schema=current_schema,
            few_shot_examples=few_shot_examples,
            latest_kpi_table=latest_kpi_table
        )

        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_query}]
        # print(messages)
        # print(self.llm.invoke(messages).content.strip())
        # 👇【将原来直接 return 的代码替换为拦截器】：
        with get_openai_callback() as cb:
            result = self.llm.invoke(messages).content.strip()
            # 计费入库 (利用 langchain 自带的精准统计)
            log_usage("无线网络问数", "deepseek-v3-0324", cb.total_tokens)
            
        return result