# pages/14_🗄️_14数据管家.py
import os
os.environ["BROWSER"] = "chrome"

import streamlit as st
import pandas as pd
import duckdb
import glob
import re
import gc
import tempfile
from core.settings import settings
from core.token_tracker import log_usage
from openai import OpenAI

st.set_page_config(page_title="AI 数据管家 & 仓库", page_icon="🗄️", layout="wide")

# =========================================================
# 1. 初始化 DuckDB 数据库引擎
# =========================================================
DB_DIR = os.path.join("global_data", "data_warehouse")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "company_data.db")

@st.cache_resource
def get_db_connection():
    return duckdb.connect(database=DB_PATH, read_only=False)

conn = get_db_connection()

def get_all_tables():
    return [row[0] for row in conn.execute("SHOW TABLES").fetchall()]

def clean_table_name(name):
    return re.sub(r'\W|^(?=\d)', '_', name)

def peek_file_headers(file_path_or_obj):
    try:
        is_str = isinstance(file_path_or_obj, str)
        file_name = file_path_or_obj if is_str else file_path_or_obj.name
        if file_name.lower().endswith('.csv'): df = pd.read_csv(file_path_or_obj, nrows=0) 
        else: df = pd.read_excel(file_path_or_obj, nrows=0)
        return tuple(df.columns.tolist())
    except Exception:
        return ("无法读取表头_可能已加密或损坏",)

# =========================================================
# 状态机初始化
# =========================================================
if "last_source_hash" not in st.session_state: st.session_state.last_source_hash = ""
if "ai_advice_text" not in st.session_state: st.session_state.ai_advice_text = ""
if "join_analysis_text" not in st.session_state: st.session_state.join_analysis_text = ""
if "data_profile_cache" not in st.session_state: st.session_state.data_profile_cache = ""
if "ai_chat_history" not in st.session_state: st.session_state.ai_chat_history = []

# =========================================================
# 2. 页面布局与导航
# =========================================================
st.title("🗄️ AI 数据管家 (Data Steward)")
st.markdown("基于 **DuckDB** 高性能引擎。支持海量入库、AI 跨表诊断、连续对话 SQL 生成、以及纯自然语言驱动的全量透视台。")

tab1, tab2, tab_join, tab_ai, tab_manual = st.tabs([
    "📥 数据入库引擎", 
    "🗂️ 数据资产大盘", 
    "🧩 跨表关联与拼接", 
    "💬 AI 连续对话分析台", 
    "🖱️ 智能手工全量透视台"
])

# ---------------------------------------------------------
# Tab 1: 数据入库
# ---------------------------------------------------------
with tab1:
    col_input, col_action = st.columns([1, 1], gap="large")
    data_sources = [] 
    default_table_name = "new_table"
    
    with col_input:
        st.markdown("### 1. 接入数据源")
        st.info("💡 小文件直接批量拖拽，大文件/多级子目录请直连文件夹绝对路径。")
        input_mode = st.radio("选择接入方式：", ["📁 网页拖拽上传 (支持多选)", "🔗 本地路径直连 (自动遍历所有子文件夹)"])
        
        if "网页拖拽" in input_mode:
            uploaded_files = st.file_uploader("上传 CSV 或 Excel (可多选)", type=["csv", "xlsx", "xls"], accept_multiple_files=True)
            if uploaded_files:
                data_sources = uploaded_files
                default_table_name = clean_table_name(os.path.splitext(uploaded_files[0].name)[0])
                st.success(f"✅ 成功接收 {len(uploaded_files)} 个文件。")
        else:
            path_input = st.text_input("📁 请输入【文件夹绝对路径】或【单文件路径】", placeholder="例如：D:\\data\\2025订单汇总")
            if path_input:
                clean_path = path_input.strip(' \'"\n\r\t')
                if os.path.isdir(clean_path):
                    files = []
                    for root_dir, _, fnames in os.walk(clean_path):
                        for fname in fnames:
                            if fname.lower().endswith(('.csv', '.xlsx', '.xls')):
                                files.append(os.path.join(root_dir, fname))
                    if files:
                        data_sources = files
                        default_table_name = clean_table_name(os.path.basename(clean_path.rstrip('\\/')))
                        st.success(f"✅ 深度遍历完成！共发现 **{len(files)}** 个表格文件。")
                elif os.path.isfile(clean_path):
                    data_sources = [clean_path]
                    default_table_name = clean_table_name(os.path.splitext(os.path.basename(clean_path))[0])
                    st.success("✅ 成功挂载本地单文件！")

    with col_action:
        st.markdown("### 2. 智能建议与入库配置")
        if data_sources:
            existing_tables = get_all_tables()
            current_hash = ",".join(sorted([f if isinstance(f, str) else f.name for f in data_sources]))
            
            if current_hash != st.session_state.last_source_hash:
                st.session_state.last_source_hash = current_hash
                st.session_state.ai_advice_text = ""
                
            if not st.session_state.ai_advice_text:
                with st.spinner("🤖 AI 架构师正在比对表结构..."):
                    schema_map = {}
                    sample_files = data_sources[:50]
                    for f in sample_files:
                        cols = peek_file_headers(f)
                        if cols not in schema_map: schema_map[cols] = []
                        f_name = f if isinstance(f, str) else f.name
                        schema_map[cols].append(os.path.basename(f_name))

                    summary_lines = [f"**分组 {i+1}** (含 {len(fnames)} 个文件):\n> 字段: `[{', '.join(str(c) for c in cols)}]`" for i, (cols, fnames) in enumerate(schema_map.items())]
                    prompt = f"你是一位数据架构师。这是新文件结构：\n{chr(10).join(summary_lines)}\n请给出合并入库建议，用一句话总结。"
                    try:
                        client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
                        res = client.chat.completions.create(model=settings.MODEL_TEXT, messages=[{"role": "user", "content": prompt}], temperature=0.2)
                        log_usage("数据管家-入库诊断", settings.MODEL_TEXT, res.usage.total_tokens)
                        st.session_state.ai_advice_text = res.choices[0].message.content
                    except Exception: pass
            
            if st.session_state.ai_advice_text: st.info(f"✨ **AI 建议**：\n\n{st.session_state.ai_advice_text}")

            st.markdown("---")
            source_mapping = { (f if isinstance(f, str) else f.name): f for f in data_sources }
            selected_names = st.multiselect("第 1 步：勾选要处理的文件", options=list(source_mapping.keys()), default=list(source_mapping.keys()))
            selected_sources = [source_mapping[n] for n in selected_names]
            
            action = st.radio("第 2 步：入库策略", ["✨ 创建全新数据表", "➕ 增量追加 (追加到历史表)", "🔄 全量覆盖 (替换历史表)"])
            target_table = st.text_input("目标表名：", value=default_table_name) if action == "✨ 创建全新数据表" else st.selectbox("选择历史表：", existing_tables)
            
            if st.button("🚀 开始执行本次入库", type="primary", use_container_width=True) and selected_sources and target_table:
                with st.status(f"🔄 写入 DuckDB 中...", expanded=True) as status:
                    total_rows = 0
                    for idx, source in enumerate(selected_sources):
                        try:
                            s_name = source.name if hasattr(source, 'name') else os.path.basename(source)
                            st.write(f"处理: `{s_name}`...")
                            if s_name.lower().endswith('.csv'): df_new = pd.read_csv(source)
                            else: 
                                try: df_new = pd.read_excel(source, engine="calamine")
                                except: df_new = pd.read_excel(source)
                            
                            df_new.columns = [clean_table_name(c) for c in df_new.columns]
                            current_rows = len(df_new)
                            
                            if action == "✨ 创建全新数据表":
                                if idx == 0: conn.execute(f"CREATE TABLE {target_table} AS SELECT * FROM df_new") 
                                else: conn.execute(f"INSERT INTO {target_table} SELECT * FROM df_new") 
                            elif action == "🔄 全量覆盖 (替换历史表)":
                                if idx == 0:
                                    conn.execute(f"DROP TABLE IF EXISTS {target_table}")
                                    conn.execute(f"CREATE TABLE {target_table} AS SELECT * FROM df_new")
                                else: conn.execute(f"INSERT INTO {target_table} SELECT * FROM df_new")
                            elif action == "➕ 增量追加 (追加到历史表)":
                                conn.execute(f"INSERT INTO {target_table} SELECT * FROM df_new")
                            
                            total_rows += current_rows
                            del df_new
                            gc.collect()
                        except Exception as e: st.error(f"失败: {e}")
                    status.update(label=f"✅ 成功写入 {total_rows} 行！", state="complete")
                    st.success(f"🎉 表 `[{target_table}]` 现已沉淀 **{total_rows}** 行数据！")

# ---------------------------------------------------------
# Tab 2: 数据资产大盘 (🌟 核心修复：单次全表扫描极速版)
# ---------------------------------------------------------
with tab2:
    st.markdown("### 🗂️ 当前仓库资产大盘")
    tables = get_all_tables()
    if not tables:
        st.warning("仓库为空。")
    else:
        col_btn, _ = st.columns([1, 2])
        with col_btn:
            if st.button("🤖 AI 扫描全库：生成数据画像与分析建议", use_container_width=True):
                with st.spinner("正在启用极速单次全表扫描探测全库特征 (耗时大幅缩减)..."):
                    profile_str = ""
                    for t in tables:
                        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        schema = conn.execute(f"DESCRIBE {t}").df()
                        cols = schema['column_name'].tolist()
                        
                        profile_str += f"### 表名: `{t}` (总行数: {count})\n"
                        
                        if count > 0 and cols:
                            # 🌟 性能核弹：将几十个字段的统计拼装成 1 条 SQL，1次全表扫描搞定！
                            agg_exprs = ", ".join([f'approx_count_distinct("{c}")' for c in cols])
                            try:
                                res_counts = conn.execute(f"SELECT {agg_exprs} FROM {t}").fetchone()
                                for c_name, u_cnt in zip(cols, res_counts):
                                    # 考虑到 approximate 的算法误差，主键判断放宽到 95% 以上
                                    is_pk = " 🔑**疑似唯一/主键**" if u_cnt >= count * 0.95 and count > 10 else ""
                                    profile_str += f"- `{c_name}`: 约 {u_cnt} 个不重复值{is_pk}\n"
                            except Exception as e:
                                profile_str += f"- (字段探测包含异常类型，略过统计)\n"
                        profile_str += "\n"
                    
                    prompt = f"你是一个高级数据架构师。这是库特征扫描结果：\n{profile_str}\n请给出：1. 异常数据提示。2. 主键确认。3. 有价值的挖掘分析建议。"
                    try:
                        client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
                        res = client.chat.completions.create(model=settings.MODEL_TEXT, messages=[{"role":"user","content":prompt}], temperature=0.3)
                        log_usage("数据管家-全库画像", settings.MODEL_TEXT, res.usage.total_tokens)
                        st.session_state.data_profile_cache = f"{profile_str}\n\n---\n**✨ AI 深度建议：**\n{res.choices[0].message.content}"
                    except Exception as e: st.error(f"分析失败: {e}")

        if st.session_state.data_profile_cache:
            st.info("💡 **AI 数据资产画像报告：**")
            st.markdown(st.session_state.data_profile_cache)
        
        st.markdown("---")
        for t in tables:
            with st.expander(f"🗃️ 数据表：{t} (点击展开前5行预览)"):
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    st.markdown(f"**总行数**：`{count}` 行")
                    preview_df = conn.execute(f"SELECT * FROM {t} LIMIT 5").df()
                    st.dataframe(preview_df, hide_index=True, use_container_width=True)
                    if st.button(f"🗑️ 删除表 [{t}]", key=f"del_{t}"):
                        conn.execute(f"DROP TABLE {t}")
                        st.rerun()
                except Exception as e: st.error(e)

# ---------------------------------------------------------
# Tab 3: 跨表关联与拼接 
# ---------------------------------------------------------
with tab_join:
    st.markdown("### 🧩 可视化跨表关联与堆叠拼接")
    st.info("💡 操作指南：不仅支持画线合并左右字段，还支持直接将格式相同的两张表上下拼接。")
    
    tables = get_all_tables()
    if len(tables) < 2:
        st.warning("⚠️ 仓库中至少需要 2 张表才能进行操作。")
    else:
        col_out1, col_out2 = st.columns([1.5, 1])
        with col_out1:
            join_type = st.radio("合并模式 (保留逻辑)：", [
                "⬅️ 左连接 (LEFT JOIN) - 保留主表全部数据", 
                "✖️ 内连接 (INNER JOIN) - 仅保留匹配成功的数据 (若完全不匹配则结果为空!)",
                "⭕ 全外连接 (FULL OUTER JOIN) - 保留两表所有数据 (未匹配自动补空)",
                "⬇️ 上下拼接 (UNION ALL BY NAME) - 忽略主键，直接上下堆叠 (异构字段自动补空)"
            ])
            
        is_union = "UNION" in join_type
        
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown("#### 🔵 主表 (左/上表)")
            main_table = st.selectbox("选择表 1：", tables, key="main_tbl")
            main_cols = conn.execute(f"DESCRIBE {main_table}").df()['column_name'].tolist()
            if not is_union:
                main_keys = st.multiselect("🔑 关联主键 (支持多选)：", main_cols, key="main_keys")
            
        with col_t2:
            st.markdown("#### 🟢 附加表 (右/下表)")
            sub_table = st.selectbox("选择表 2：", [t for t in tables if t != main_table], key="sub_tbl")
            if sub_table and not is_union:
                sub_cols = conn.execute(f"DESCRIBE {sub_table}").df()['column_name'].tolist()
                sub_keys = st.multiselect("🔑 关联匹配键 (需与左边顺序一致)：", sub_cols, key="sub_keys")

        if not is_union:
            if st.button("🤖 AI 帮我分析能否关联 (推荐)", use_container_width=True):
                with st.spinner("AI 正在深度比对..."):
                    try:
                        prompt = f"表A `{main_table}` 字段：[{', '.join(main_cols)}]\n表B `{sub_table}` 字段：[{', '.join(sub_cols)}]\n请诊断：能否关联？推荐用哪几个字段？"
                        client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
                        res = client.chat.completions.create(model=settings.MODEL_TEXT, messages=[{"role": "user", "content": prompt}], temperature=0.3)
                        log_usage("数据管家-关联诊断", settings.MODEL_TEXT, res.usage.total_tokens)
                        st.session_state.join_analysis_text = res.choices[0].message.content
                    except Exception as e: st.session_state.join_analysis_text = f"诊断失败：{e}"
            if st.session_state.join_analysis_text: st.success("✨ **AI 诊断报告**：\n\n" + st.session_state.join_analysis_text)

        st.markdown("---")
        new_wide_table = st.text_input("输出的新表名称：", value=f"{main_table}_{'union' if is_union else 'joined'}_{sub_table}")
            
        if st.button("🚀 立即合并表数据", type="primary", use_container_width=True):
            if not is_union and (not main_keys or not sub_keys or len(main_keys) != len(sub_keys)):
                st.error("❌ 请确保左右关联键数量一致且不能为空！")
            else:
                with st.spinner(f"正在全量构建 {new_wide_table} ..."):
                    try:
                        if is_union:
                            sql_join = f"CREATE TABLE {new_wide_table} AS SELECT * FROM {main_table} UNION ALL BY NAME SELECT * FROM {sub_table}"
                        else:
                            j_clause = "LEFT JOIN" if "LEFT" in join_type else ("INNER JOIN" if "INNER" in join_type else "FULL OUTER JOIN")
                            select_clause = f"{main_table}.*"
                            for c in sub_cols:
                                if c not in sub_keys:
                                    select_clause += f", {sub_table}.\"{c}\" AS {sub_table}_{c}" if c in main_cols else f", {sub_table}.\"{c}\""
                            
                            on_conditions = [f"{main_table}.\"{mk}\" = {sub_table}.\"{sk}\"" for mk, sk in zip(main_keys, sub_keys)]
                            on_clause = " AND ".join(on_conditions)

                            sql_join = f"CREATE TABLE {new_wide_table} AS SELECT {select_clause} FROM {main_table} {j_clause} {sub_table} ON {on_clause}"
                            
                        conn.execute(sql_join)
                        st.success(f"🎉 成功生成大宽表 `[{new_wide_table}]`！如果是内连接产生空表，说明没有任何记录能匹配上，建议改用左连接重试。")
                    except Exception as e: st.error(f"合并失败：\n\n{e}")

# ---------------------------------------------------------
# Tab 4: AI 连续对话分析台
# ---------------------------------------------------------
with tab_ai:
    tables = get_all_tables()
    if not tables:
        st.warning("请先入库数据！")
    else:
        st.markdown("### 💬 AI 连续对话分析台")
        st.info("💡 支持记忆上下文。遇到需要中间表、多步计算的复杂需求，AI 会自动使用 CTE 编写高级 SQL 处理。")
        
        all_schemas_info = ""
        with st.expander("📚 查看 AI 当前掌握的数据库全景字典"):
            for t in tables:
                schema_df = conn.execute(f"DESCRIBE {t}").df()
                cols_str = ", ".join([f"{r['column_name']} ({r['column_type']})" for _, r in schema_df.iterrows()])
                all_schemas_info += f"Table: `{t}` | Columns: {cols_str}\n"
                st.markdown(f"**`{t}`**: `" + "` , `".join(schema_df['column_name'].tolist()) + "`")

        for i, msg in enumerate(st.session_state.ai_chat_history):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("sql"): st.code(msg["sql"], language="sql")
                if msg.get("df") is not None:
                    st.dataframe(msg["df"].head(500), use_container_width=True)
                    st.caption("💡 提示：在表格上按 Ctrl+A 全选，Ctrl+C 即可一键复制。为防卡顿，界面仅渲染前 500 行。")
                if msg.get("export_file"):
                    with open(msg["export_file"], "rb") as f:
                        st.download_button("📥 下载完整全量数据 (CSV文件)", f, file_name=os.path.basename(msg["export_file"]), key=f"dl_history_{i}")

        st.markdown("---")
        user_question = st.text_area("告诉 AI 您的分析需求 (或补充业务常识，如“以后提到的份额都是指A除以B”)：", height=100)
        
        col_btn, col_exp = st.columns([1, 1.5])
        with col_btn:
            ask_btn = st.button("✨ 极速生成并执行", type="primary", use_container_width=True)
        with col_exp:
            export_only = st.checkbox("📦 纯导出模式 (如果结果达百万行，勾选此项可直接生成 CSV 文件，彻底避免网页卡死)")

        if ask_btn and user_question:
            st.session_state.ai_chat_history.append({"role": "user", "content": user_question})
            
            with st.chat_message("assistant"):
                with st.spinner("🧠 AI 正在根据历史语境进行复杂推理并生成全量 SQL..."):
                    system_prompt = f"""You are a top-tier Data Architect and DuckDB SQL Expert.
DATABASE SCHEMA:
{all_schemas_info}

CRITICAL RULES:
1. Support JOINs if multiple tables are mentioned.
2. Understood JARGON/BUSINESS LOGIC context from user's history.
3. For Geospatial Math (e.g. distance), use: acos(sin(radians(lat1))*sin(radians(lat2)) + cos(radians(lat1))*cos(radians(lat2))*cos(radians(lon2)-radians(lon1))) * 6371000
4. For complex multi-step analysis (e.g. generate site-level intermediate tables, then check bands), you MUST aggressively use CTEs (WITH clauses).
5. Output format: First explain your thought process briefly, then provide ONLY the final raw SQL query wrapped in ```sql and ```. Wrap Chinese columns in double quotes.
"""                 
                    messages = [{"role": "system", "content": system_prompt}]
                    for msg in st.session_state.ai_chat_history:
                        messages.append({"role": msg["role"], "content": msg["content"]})

                    try:
                        client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
                        res = client.chat.completions.create(model=settings.MODEL_CODER, messages=messages, temperature=0.2)
                        log_usage("数据管家-连续对话分析", settings.MODEL_CODER, res.usage.total_tokens)
                        
                        response_content = res.choices[0].message.content.strip()
                        sql_match = re.search(r'```sql\n(.*?)\n```', response_content, re.DOTALL)
                        
                        if sql_match:
                            clean_sql = sql_match.group(1).strip()
                            explanation = response_content.replace(sql_match.group(0), "").strip()
                        else:
                            clean_sql = ""
                            explanation = response_content

                        st.markdown(explanation)
                        
                        if clean_sql:
                            st.code(clean_sql, language="sql")
                            
                            if export_only:
                                export_path = os.path.join(tempfile.gettempdir(), f"duckdb_export_{len(st.session_state.ai_chat_history)}.csv")
                                copy_sql = f"COPY ({clean_sql}) TO '{export_path}' (HEADER, DELIMITER ',')"
                                conn.execute(copy_sql)
                                st.success("✅ 全量数据已在后台导出完毕！")
                                with open(export_path, "rb") as f:
                                    st.download_button("📥 立即下载 CSV", f, file_name=f"Result_{len(st.session_state.ai_chat_history)}.csv", key=f"dl_new")
                                
                                st.session_state.ai_chat_history.append({
                                    "role": "assistant", "content": explanation, "sql": clean_sql, "df": None, "export_file": export_path
                                })
                            else:
                                result_df = conn.execute(clean_sql).df()
                                res_len = len(result_df)
                                st.markdown(f"##### 📊 全量计算完成！(共命中 {res_len} 条结果)")
                                
                                if res_len > 500:
                                    st.warning("⚠️ 结果过多，已为您自动截断展示前 500 行。建议点右上角复制，或勾选上方纯导出模式。")
                                    st.dataframe(result_df.head(500), use_container_width=True)
                                else:
                                    st.dataframe(result_df, use_container_width=True)
                                st.caption("💡 提示：在表格上按 Ctrl+A 全选，Ctrl+C 即可一键复制到 Excel。")
                                
                                st.session_state.ai_chat_history.append({
                                    "role": "assistant", "content": explanation, "sql": clean_sql, "df": result_df, "export_file": None
                                })
                        else:
                            st.session_state.ai_chat_history.append({"role": "assistant", "content": explanation})
                            
                    except Exception as e: st.error(f"执行失败：\n\n{e}")

# ---------------------------------------------------------
# Tab 5: 智能手工透视台 
# ---------------------------------------------------------
with tab_manual:
    tables = get_all_tables()
    if not tables:
        st.warning("请先入库数据！")
    else:
        st.markdown("### 🖱️ 智能辅助透视工作台")
        st.info("💡 操作指南：拖拽选择【行/列/值】，然后在下方【智能条件】中直接输入自然语言，AI 会自动为您构建复杂的过滤逻辑。")

        selected_table = st.selectbox("选择要透视的表：", tables, key="man_tbl")
        
        with st.expander("👀 查看表最新 10 行预览", expanded=False):
            try:
                preview_df = conn.execute(f"SELECT * FROM {selected_table} LIMIT 10").df()
                st.dataframe(preview_df, hide_index=True)
            except: pass
            
        schema_df = conn.execute(f"DESCRIBE {selected_table}").df()
        table_cols = schema_df['column_name'].tolist()

        col_r, col_c, col_v = st.columns(3)
        with col_r:
            pivot_rows = st.multiselect("👉 【行】区域：", table_cols)
        with col_c:
            pivot_cols = st.multiselect("👉 【列】区域：", table_cols)
        with col_v:
            pivot_vals = st.multiselect("👉 【值】区域：", table_cols, help="不选默认计算全表行数。选多个将同时产出多个指标。")
            pivot_agg = st.selectbox("📐 聚合计算：", ["COUNT", "COUNT DISTINCT", "SUM", "AVG", "MAX", "MIN"])

        st.markdown("---")
        st.markdown("##### 🧠 智能筛选与复杂计算条件")
        nl_condition = st.text_area(
            "在此输入您的筛选意图 (支持人话)：", 
            placeholder="例如：厂家只选华为和中兴；或者：经纬度距离(116.4, 39.9)小于500米；或者：挂高在30到50之间...",
            help="AI 将根据您的输入，自动生成 SQL 级别的过滤条件。"
        )

        if st.button("🚀 开始全量跑批", type="primary", use_container_width=True):
            with st.spinner("⏳ AI 正在理解意图并执行全量透视..."):
                try:
                    where_clause = ""
                    if nl_condition.strip():
                        client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)
                        prompt = f"""Convert user intent to DuckDB SQL WHERE clause (exclude 'WHERE' keyword).
Table: {selected_table}
Columns: {table_cols}
User Intent: "{nl_condition}"

TASK: Convert the User Intent into a valid SQL WHERE clause.
SPECIAL RULES:
1. Use double quotes for column names (e.g. "厂家").
2. If the user mentions location/distance, use: 
   `acos(sin(radians("纬度"))*sin(radians(target_lat)) + cos(radians("纬度"))*cos(radians(target_lat))*cos(radians(target_lon)-radians("经度"))) * 6371000 < distance`
3. Return ONLY the raw SQL snippet. No explanations.
"""
                        res = client.chat.completions.create(model=settings.MODEL_CODER, messages=[{"role":"user","content":prompt}], temperature=0.1)
                        log_usage("数据管家-条件翻译", settings.MODEL_CODER, res.usage.total_tokens)
                        where_clause = res.choices[0].message.content.strip().replace("```sql", "").replace("```", "").strip()
                        st.info(f"🤖 AI 生成的过滤逻辑：`{where_clause}`")

                    val_exprs = []
                    for v in pivot_vals:
                        if "DISTINCT" in pivot_agg: val_exprs.append(f"COUNT(DISTINCT \"{v}\") AS \"{v}_去重数\"")
                        else: val_exprs.append(f"{pivot_agg.split(' ')[0]}(\"{v}\") AS \"{v}_{pivot_agg.split(' ')[0]}\"")
                    if not val_exprs: val_exprs = ["COUNT(*) AS \"记录数\""]
                    val_expr_sql = ", ".join(val_exprs)

                    source_sql = f'"{selected_table}"'
                    if where_clause:
                        source_sql = f"(SELECT * FROM {source_sql} WHERE {where_clause})"

                    if not pivot_rows and not pivot_cols:
                        final_sql = f"SELECT {val_expr_sql} FROM {source_sql}"
                    elif pivot_cols:
                        p_cols = ", ".join([f'"{c}"' for c in pivot_cols])
                        r_group = f"GROUP BY {', '.join([f'\"{c}\"' for c in pivot_rows])}" if pivot_rows else ""
                        final_sql = f"PIVOT {source_sql} ON {p_cols} USING {val_expr_sql} {r_group}"
                    else:
                        r_cols = ", ".join([f'"{c}"' for c in pivot_rows])
                        final_sql = f"SELECT {r_cols}, {val_expr_sql} FROM {source_table} GROUP BY {r_cols} ORDER BY {r_cols}"

                    result_df = conn.execute(final_sql).df()
                    res_len = len(result_df)
                    st.markdown(f"##### 📊 全量计算完成！(共命中 {res_len} 条结果)")
                    
                    if res_len > 500:
                        st.warning("⚠️ 结果过多，已截断展示前 500 行。")
                        st.dataframe(result_df.head(500), use_container_width=True)
                    else:
                        st.dataframe(result_df, use_container_width=True)

                except Exception as e:
                    st.error(f"透视失败！AI 生成的逻辑可能有误，请尝试换种说法。报错：{e}")