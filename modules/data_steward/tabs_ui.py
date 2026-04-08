import os
import tempfile
import pandas as pd
import streamlit as st
import gc

from modules.data_steward.db_engine import (
    execute_write, execute_safe_query, get_all_tables, 
    get_table_schema, clean_table_name, peek_file_headers, get_db_connection
)
from modules.data_steward.ai_engine import call_ai_architect, call_ai_sql_coder, extract_sql
from core.settings import settings
from core.token_tracker import log_usage
from openai import OpenAI

# ==========================================
# TAB 1: 数据入库引擎 (极速零内存优化)
# ==========================================
def render_etl_tab():
    col_input, col_action = st.columns([1, 1], gap="large")
    data_sources = [] 
    default_table_name = "new_table"
    
    with col_input:
        st.markdown("### 1. 接入数据源")
        input_mode = st.radio("接入方式：", ["📁 网页拖拽上传", "🔗 本地绝对路径直连"])
        
        if "拖拽" in input_mode:
            uploaded_files = st.file_uploader("上传 CSV 或 Excel (可多选)", accept_multiple_files=True)
            if uploaded_files:
                for uf in uploaded_files:
                    tmp_path = os.path.join(tempfile.gettempdir(), uf.name)
                    with open(tmp_path, "wb") as f: f.write(uf.getbuffer())
                    data_sources.append(tmp_path)
                default_table_name = clean_table_name(os.path.splitext(uploaded_files[0].name)[0])
                st.success(f"✅ 成功缓存 {len(uploaded_files)} 个文件。")
        else:
            path_input = st.text_input("📁 输入绝对路径", placeholder="例如：D:\\data\\2025订单汇总")
            if path_input and os.path.exists(clean_path := path_input.strip(' \'"\n\r\t')):
                if os.path.isdir(clean_path):
                    data_sources = [os.path.join(r, f) for r, _, fs in os.walk(clean_path) for f in fs if f.lower().endswith(('.csv', '.xlsx', '.xls'))]
                else: data_sources = [clean_path]
                if data_sources:
                    default_table_name = clean_table_name(os.path.basename(clean_path.rstrip('\\/')))
                    st.success(f"✅ 深度遍历完成！发现 {len(data_sources)} 个表格文件。")

    with col_action:
        st.markdown("### 2. 智能配置与入库")
        if data_sources:
            if st.button("🤖 AI 诊断合并策略"):
                with st.spinner("架构师比对中..."):
                    schema_map = {}
                    for f in data_sources[:50]:
                        cols = peek_file_headers(f)
                        schema_map.setdefault(cols, []).append(os.path.basename(f))
                    summary = [f"分组 {i+1}:\n> 字段: `[{', '.join(str(c) for c in cols)}]`" for i, (cols, _) in enumerate(schema_map.items())]
                    st.info(call_ai_architect(f"新文件结构：\n{chr(10).join(summary)}\n给出一句话入库建议。", "入库诊断"))

            st.markdown("---")
            action = st.radio("入库策略：", ["✨ 创建全新数据表", "➕ 增量追加", "🔄 全量覆盖"])
            target_table = st.text_input("目标表名：", value=default_table_name) if action == "✨ 创建全新数据表" else st.selectbox("选择表：", get_all_tables())
            
            if st.button("🚀 执行极速入库", type="primary") and target_table:
                with st.status(f"🔄 写入底层...", expanded=True) as status:
                    total_rows = 0
                    for idx, source in enumerate(data_sources):
                        st.write(f"装载: `{os.path.basename(source)}`...")
                        try:
                            if source.lower().endswith('.csv'):
                                if action == "✨ 创建全新数据表" and idx == 0: execute_write(f"CREATE TABLE {target_table} AS SELECT * FROM read_csv_auto('{source}')")
                                elif action == "🔄 全量覆盖" and idx == 0:
                                    execute_write(f"DROP TABLE IF EXISTS {target_table}")
                                    execute_write(f"CREATE TABLE {target_table} AS SELECT * FROM read_csv_auto('{source}')")
                                else: execute_write(f"INSERT INTO {target_table} SELECT * FROM read_csv_auto('{source}')")
                                total_rows += execute_safe_query(f"SELECT COUNT(*) FROM read_csv_auto('{source}')").iloc[0,0]
                            else:
                                try: df_new = pd.read_excel(source, engine="calamine")
                                except: df_new = pd.read_excel(source)
                                df_new.columns = [clean_table_name(c) for c in df_new.columns]
                                total_rows += len(df_new)
                                if action == "✨ 创建全新数据表" and idx == 0: execute_write(f"CREATE TABLE {target_table} AS SELECT * FROM df_new")
                                elif action == "🔄 全量覆盖" and idx == 0:
                                    execute_write(f"DROP TABLE IF EXISTS {target_table}")
                                    execute_write(f"CREATE TABLE {target_table} AS SELECT * FROM df_new")
                                else: execute_write(f"INSERT INTO {target_table} SELECT * FROM df_new")
                                del df_new
                                gc.collect()
                        except Exception as e: st.error(f"失败: {e}")
                    status.update(label=f"✅ 入库完成！", state="complete")
                    st.success("操作成功，请前往大盘查看。")

# ==========================================
# TAB 2: 数据资产大盘 (一键生成画像建议)
# ==========================================
def render_profile_tab():
    st.markdown("### 🗂️ 当前仓库资产大盘")
    tables = get_all_tables()
    if not tables:
        st.warning("仓库为空。")
        return

    col_btn, _ = st.columns([1, 2])
    with col_btn:
        if st.button("🤖 AI 扫描全库：生成数据画像与分析建议", use_container_width=True):
            with st.spinner("正在通过 SUMMARIZE 引擎极速抽取特征 (防超时模式)..."):
                profile_str = ""
                for t in tables:
                    try:
                        count = execute_safe_query(f"SELECT COUNT(*) FROM {t}").iloc[0,0]
                        summary_df = execute_safe_query(f"SUMMARIZE {t}")
                        profile_str += f"### 表: `{t}` (行数: {count})\n字段分布: "
                        
                        k_cols = []
                        for _, row in summary_df.iterrows():
                            u_cnt = row['approx_unique']
                            if pd.notna(u_cnt):
                                is_pk = "🔑" if u_cnt >= count * 0.95 and count > 10 else ""
                                k_cols.append(f"{row['column_name']}(约{int(u_cnt)}{is_pk})")
                        profile_str += ", ".join(k_cols) + "\n\n"
                    except Exception as e: profile_str += f"表 `{t}` 探测失败: {e}\n\n"
                
                prompt_payload = profile_str[:8000] + "\n...(已截断)" if len(profile_str) > 8000 else profile_str
                
                # 🔴 修正：统一调用封装函数，自动计入 "14_数据管家"
                ai_advice = call_ai_architect(f"扫描结果：\n{prompt_payload}\n给出：1.异常提示 2.主键确认 3.挖掘建议。严格限 800 字内。", "全库画像")
                st.session_state.data_profile_cache = f"{profile_str}\n\n---\n**✨ AI 深度建议：**\n{ai_advice}"

    if st.session_state.get("data_profile_cache"):
        st.info("💡 **AI 画像报告：**")
        st.markdown(st.session_state.data_profile_cache)
    
    st.markdown("---")
    for t in tables:
        with st.expander(f"🗃️ 数据表：{t} (展开查看前 5 行预览)"):
            try:
                count = execute_safe_query(f"SELECT COUNT(*) FROM {t}").iloc[0,0]
                st.markdown(f"**总行数**：`{count}` 行")
                st.dataframe(execute_safe_query(f"SELECT * FROM {t} LIMIT 5"), hide_index=True, use_container_width=True)
                if st.button(f"🗑️ 删除表 [{t}]", key=f"del_{t}"):
                    execute_write(f"DROP TABLE {t}")
                    st.rerun()
            except Exception as e: st.error(e)

# ==========================================
# TAB 3: 跨表关联与拼接 (4 种模式全开)
# ==========================================
def render_join_tab():
    st.markdown("### 🧩 可视化跨表关联与堆叠拼接")
    tables = get_all_tables()
    if len(tables) < 2:
        st.warning("⚠️ 至少需要 2 张表。")
        return
        
    col_out1, col_out2 = st.columns([1.5, 1])
    with col_out1:
        join_type = st.radio("合并模式：", [
            "⬅️ 左连接 (LEFT JOIN)", "✖️ 内连接 (INNER JOIN)",
            "⭕ 全外连接 (FULL OUTER JOIN)", "⬇️ 上下拼接 (UNION ALL BY NAME)"
        ])
    is_union = "UNION" in join_type
    
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        main_table = st.selectbox("选择表 1：", tables, key="main_tbl")
        main_cols = get_table_schema(main_table)['column_name'].tolist()
        if not is_union: main_keys = st.multiselect("🔑 关联主键：", main_cols, key="main_keys")
        
    with col_t2:
        sub_table = st.selectbox("选择表 2：", [t for t in tables if t != main_table], key="sub_tbl")
        if sub_table and not is_union:
            sub_cols = get_table_schema(sub_table)['column_name'].tolist()
            sub_keys = st.multiselect("🔑 关联匹配键 (需与左边一致)：", sub_cols, key="sub_keys")

    if not is_union and st.button("🤖 AI 帮我分析能否关联"):
        with st.spinner("深度比对中..."):
            # 🔴 修正：统一调用封装函数，自动计入 "14_数据管家"
            st.session_state.join_analysis_text = call_ai_architect(f"表A `{main_table}`:[{','.join(main_cols)}]\n表B `{sub_table}`:[{','.join(sub_cols)}]\n诊断能否关联？推荐字段？", "关联诊断")
    if st.session_state.get("join_analysis_text"): st.success("✨ **AI 诊断**：" + st.session_state.join_analysis_text)

    st.markdown("---")
    new_wide_table = st.text_input("输出的新表名称：", value=f"{main_table}_{'union' if is_union else 'joined'}_{sub_table}")
        
    if st.button("🚀 立即合并表数据", type="primary"):
        if not is_union and (not main_keys or not sub_keys or len(main_keys) != len(sub_keys)):
            st.error("❌ 关联键数量必须一致且不能为空！")
            return
            
        with st.spinner(f"构建 {new_wide_table} ..."):
            try:
                if is_union:
                    sql = f"CREATE TABLE {new_wide_table} AS SELECT * FROM {main_table} UNION ALL BY NAME SELECT * FROM {sub_table}"
                else:
                    j_clause = "LEFT JOIN" if "LEFT" in join_type else ("INNER JOIN" if "INNER" in join_type else "FULL OUTER JOIN")
                    s_cols = f"{main_table}.*"
                    for c in sub_cols:
                        if c not in sub_keys: s_cols += f", {sub_table}.\"{c}\" AS {sub_table}_{c}" if c in main_cols else f", {sub_table}.\"{c}\""
                    on_c = " AND ".join([f"{main_table}.\"{mk}\" = {sub_table}.\"{sk}\"" for mk, sk in zip(main_keys, sub_keys)])
                    sql = f"CREATE TABLE {new_wide_table} AS SELECT {s_cols} FROM {main_table} {j_clause} {sub_table} ON {on_c}"
                execute_write(sql)
                st.success(f"🎉 成功生成大宽表 `[{new_wide_table}]`！")
            except Exception as e: st.error(f"合并失败: {e}")

# ==========================================
# TAB 4: AI 连续对话分析 (审核 + 上下布局 + OOM防御)
# ==========================================
def render_ai_chat_tab():
    tables = get_all_tables()
    if not tables:
        st.warning("请先入库数据！")
        return
        
    st.markdown("### 💬 AI 连续对话分析台")
    st.info("💡 复杂计算(如先建中间表再分析)时，AI会自动使用 CTE (WITH语法)。所有生成的 SQL 需确认后执行。")
    
    analysis_mode_ai = st.radio("🔍 分析范围：", ["📄 单表", "🕸️ 全库"], horizontal=True)
    if analysis_mode_ai == "📄 单表":
        sel_tbl = st.selectbox("👉 选择表：", tables)
        with st.expander(f"👀 查看 `{sel_tbl}` 的前 10 行预览", expanded=False):
            st.dataframe(execute_safe_query(f"SELECT * FROM {sel_tbl} LIMIT 10"), hide_index=True)
        cols_str = ", ".join([f"{r['column_name']}({r['column_type']})" for _, r in get_table_schema(sel_tbl).iterrows()])
        sys_schema = f"Table: `{sel_tbl}`\nColumns: {cols_str}"
        sys_rules = f"CRITICAL: MUST ONLY query from `{sel_tbl}`. DO NOT use JOIN."
    else:
        sys_schema = "\n".join([f"Table: `{t}` | Columns: {', '.join(get_table_schema(t)['column_name'].tolist())}" for t in tables])
        sys_rules = "You can use JOINs across multiple tables."

    for i, msg in enumerate(st.session_state.ai_chat_history):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sql"): st.code(msg["sql"], language="sql")
            if msg.get("data_dict"):
                st.dataframe(pd.DataFrame(msg["data_dict"]), use_container_width=True)
                st.caption("💡 提示：在表格上按 Ctrl+A 全选，Ctrl+C 即可一键复制。为防卡顿，界面仅渲染前 500 行。")
            if msg.get("export_file"):
                with open(msg["export_file"], "rb") as f:
                    st.download_button("📥 下载完整数据 (CSV)", f, file_name=os.path.basename(msg["export_file"]), key=f"dl_{i}")

    st.markdown("---")
    user_q = st.text_area("🗣️ 对话需求 (如：把小区按经纬度聚类算出中间表)：", height=100)
    export_only = st.checkbox("📦 纯导出模式 (执行时跳过浏览器渲染，直接生成完整 CSV 文件下载，大文件必备)")

    if st.button("🧠 1. 让 AI 编写方案", type="primary", use_container_width=True):
        st.session_state.ai_chat_history.append({"role": "user", "content": user_q})
        with st.spinner("推演逻辑..."):
            sys_p = f"""You are a Data Architect. SCHEMA:\n{sys_schema}\nRULES:\n1.{sys_rules}
2. Geospatial: acos(sin(radians(lat1))*sin(radians(lat2)) + cos(radians(lat1))*cos(radians(lat2))*cos(radians(lon2)-radians(lon1))) * 6371000
3. STRONGLY prefer CTEs (WITH clause) for complex multi-step analysis (e.g., intermediate site tables).
4. Output SQL wrapped in ```sql."""
            
            # 🔴 修正：统一调用封装函数
            ai_resp = call_ai_sql_coder(sys_p, [{"role": m["role"], "content": m["content"]} for m in st.session_state.ai_chat_history], "对话分析")
            clean_sql, exp = extract_sql(ai_resp)
            st.session_state.pending_sql = clean_sql
            st.session_state.pending_exp = exp
            st.rerun()

    if st.session_state.get("pending_sql"):
        st.success("✅ AI 编写完毕，请审查：")
        st.markdown(st.session_state.pending_exp)
        edited_sql = st.text_area("💻 审查 / 修改 SQL：", value=st.session_state.pending_sql, height=200)
        
        if st.button("🚀 2. 确认并全量执行", type="primary", use_container_width=True):
            with st.spinner("底层执行中..."):
                try:
                    if export_only:
                        exp_path = os.path.join(tempfile.gettempdir(), f"export_{len(st.session_state.ai_chat_history)}.csv")
                        get_db_connection().execute(f"COPY ({edited_sql}) TO '{exp_path}' (HEADER, DELIMITER ',')")
                        st.session_state.ai_chat_history.append({
                            "role": "assistant", "content": "✅ 全量文件已在后台导出。请点击下载。", "sql": edited_sql, "export_file": exp_path
                        })
                    else:
                        res_df = execute_safe_query(edited_sql)
                        st.session_state.ai_chat_history.append({
                            "role": "assistant", "content": f"✅ 执行成功。共命中 {len(res_df)} 行。", "sql": edited_sql, 
                            "data_dict": res_df.head(500).to_dict('records') 
                        })
                    st.session_state.pending_sql = "" 
                    st.rerun()
                except Exception as e: st.error(f"SQL 报错：\n{e}")

# ==========================================
# TAB 5: 手工透视 (NL2SQL 自然语言过滤 + 多值)
# ==========================================
def render_manual_pivot_tab():
    tables = get_all_tables()
    if not tables:
        st.warning("请先入库数据！")
        return
        
    st.markdown("### 🖱️ 智能手工全量透视表")
    mode = st.radio("🔍 透视范围：", ["📄 单表透视", "🕸️ 跨表透视 (字段混选，AI动态关联)"], horizontal=True)
    
    if mode == "📄 单表透视":
        sel_tbl = st.selectbox("👉 表：", tables)
        with st.expander(f"👀 查看 `{sel_tbl}` 的前 10 行预览", expanded=False): 
            st.dataframe(execute_safe_query(f"SELECT * FROM {sel_tbl} LIMIT 10"), hide_index=True)
        table_cols = get_table_schema(sel_tbl)['column_name'].tolist()
    else:
        st.info("💡 跨表模式：选择后 AI 会推演 JOIN 逻辑。")
        all_schemas_info = ""
        table_cols = []
        with st.expander("📚 展开字典"):
            for t in tables:
                cols = get_table_schema(t)['column_name'].tolist()
                all_schemas_info += f"Table: `{t}` | Cols: {', '.join(cols)}\n"
                for c in cols: table_cols.append(f"[{t}] {c}")
                st.markdown(f"**`{t}`**: `" + "` , `".join(cols) + "`")

    col_r, col_c, col_v = st.columns(3)
    with col_r: pivot_rows = st.multiselect("👉 【行】(必填)：", table_cols)
    with col_c: pivot_cols = st.multiselect("👉 【列】(可选)：", table_cols)
    with col_v:
        pivot_vals = st.multiselect("👉 【值】(多选)：", table_cols)
        pivot_agg = st.selectbox("📐 聚合：", ["COUNT", "COUNT DISTINCT", "SUM", "AVG", "MAX", "MIN"])

    nl_condition = st.text_area("🗣️ 过滤条件 (直接说大白话)：", placeholder="例如：厂家只要华为和中兴；距离某坐标点小于500米...")

    if st.button("🚀 立即全量透视", type="primary", use_container_width=True):
        if not pivot_rows:
            st.error("❌ 至少选一个【行】")
            return
            
        with st.spinner("AI 意图解析与底层运算中..."):
            try:
                where_clause = ""
                if nl_condition.strip() and mode == "📄 单表透视":
                    sys_p = f"Table: {sel_tbl}\nCols: {table_cols}\nTask: Convert User Intent to SQL WHERE clause. No markdown. Use acos/sin/cos for distance * 6371000."
                    # 🔴 修正：统一调用封装函数
                    where_clause = call_ai_sql_coder(sys_p, [{"role":"user","content":nl_condition}], "透视条件翻译")
                    st.info(f"🤖 AI 生成过滤逻辑：`{where_clause}`")

                if mode == "📄 单表透视":
                    val_exprs = [f"COUNT(DISTINCT \"{v}\") AS \"{v}_去重\"" if "DISTINCT" in pivot_agg else f"{pivot_agg.split(' ')[0]}(\"{v}\") AS \"{v}_聚合\"" for v in pivot_vals] or ["COUNT(*) AS \"记录数\""]
                    v_sql = ", ".join(val_exprs)
                    s_sql = f'"{sel_tbl}"'
                    if where_clause: s_sql = f"(SELECT * FROM {s_sql} WHERE {where_clause})"
                    
                    if pivot_cols:
                        p_cols = ", ".join([f'"{c}"' for c in pivot_cols])
                        r_grp = f"GROUP BY {', '.join([f'\"{c}\"' for c in pivot_rows])}"
                        final_sql = f"PIVOT {s_sql} ON {p_cols} USING {v_sql} {r_grp}"
                    else:
                        r_cols = ", ".join([f'"{c}"' for c in pivot_rows])
                        final_sql = f"SELECT {r_cols}, {v_sql} FROM {s_sql} GROUP BY {r_cols} ORDER BY {r_cols}"
                else:
                    sys_p = f"SCHEMA:\n{all_schemas_info}\nRows:{pivot_rows}, Cols:{pivot_cols}, Vals:{pivot_vals}, Agg:{pivot_agg}, NL Filter:{nl_condition}\nTask: Write DuckDB SQL. USE PIVOT if cols requested. Output raw SQL in ```sql."
                    # 🔴 修正：统一调用封装函数
                    ai_resp = call_ai_sql_coder(sys_p, [{"role":"user","content":"Generate SQL"}], "跨表透视生成")
                    final_sql, _ = extract_sql(ai_resp)
                    st.info(f"🤖 底层执行 SQL：\n```sql\n{final_sql}\n```")

                res_df = execute_safe_query(final_sql)
                st.markdown(f"##### 📊 全量完成 (命中 {len(res_df)} 条) - 可在表格上 Ctrl+A 复制")
                if len(res_df) > 500:
                    st.warning("⚠️ 结果截断前 500 行展示。")
                    st.dataframe(res_df.head(500), use_container_width=True)
                else:
                    st.dataframe(res_df, use_container_width=True)
            except Exception as e: st.error(f"透视执行或语法生成失败：{e}")