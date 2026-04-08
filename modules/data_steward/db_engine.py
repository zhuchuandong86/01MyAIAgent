import duckdb
import threading
import os
import re
import pandas as pd
import streamlit as st

DB_DIR = os.path.join("global_data", "data_warehouse")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "company_data.db")

# 🔴 P0 级并发防御：全局读写锁，防止多页面多线程操作将 DuckDB 锁死
db_lock = threading.Lock()

@st.cache_resource
def get_db_connection():
    return duckdb.connect(database=DB_PATH, read_only=False)

def execute_write(sql):
    """用于入库、建表等写操作，严格加锁"""
    conn = get_db_connection()
    with db_lock:
        conn.execute(sql)

def execute_safe_query(sql):
    """用于 AI 或用户的查询操作，包含 P0 级高危 SQL 注入拦截"""
    forbidden_keywords = r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE)\b'
    if re.search(forbidden_keywords, sql, re.IGNORECASE):
        raise ValueError("🚨 安全拦截触发：检测到修改数据库的高危指令，已自动阻断！")
    
    conn = get_db_connection()
    with db_lock:
        return conn.execute(sql).df()

def get_all_tables():
    conn = get_db_connection()
    with db_lock:
        return [row[0] for row in conn.execute("SHOW TABLES").fetchall()]

def get_table_schema(table_name):
    conn = get_db_connection()
    with db_lock:
        return conn.execute(f"DESCRIBE {table_name}").df()

def clean_table_name(name):
    return re.sub(r'\W|^(?=\d)', '_', name)

def peek_file_headers(file_path):
    try:
        if file_path.lower().endswith('.csv'): 
            df = pd.read_csv(file_path, nrows=0) 
        else: 
            df = pd.read_excel(file_path, nrows=0)
        return tuple(df.columns.tolist())
    except: 
        return ("无法读取表头_可能已损坏",)