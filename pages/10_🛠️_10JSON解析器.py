# pages/10_🛠️_JSON解析器.py
import streamlit as st
import json
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.callbacks.manager import get_openai_callback
from core.prompts import JSON_CLEANER_PROMPT
from core.llm_factory import get_llm

st.set_page_config(page_title="JSON 智能解析", page_icon="🛠️", layout="wide")

st.title("🛠️ JSON 智能解析与格式化")
st.markdown("不仅支持标准 JSON 的美化，还能利用 AI 将 **不规则的开发日志、Python 对象字符串（如 ChatCompletion）** 自动清洗并重构为标准的可折叠 JSON 层级。")

# ==========================================
# 界面布局：左侧输入，右侧输出
# ==========================================
col1, col2 = st.columns(2)

with col1:
    raw_input = st.text_area(
        "📥 原始数据输入", 
        height=500, 
        placeholder="请在此粘贴您的 JSON 文本，或者像 ChatCompletion(...) 这样带有类名和单引号的不规则格式文本..."
    )
    
    st.write("") # 留点间距
    c1, c2 = st.columns(2)
    btn_standard = c1.button("⚡ 标准 JSON 格式化 (极速)", use_container_width=True)
    btn_ai = c2.button("🧠 AI 智能清洗与解析", type="primary", use_container_width=True)

with col2:
    st.markdown("### 📤 解析与分层结果")
    
    # -----------------------------------------
    # 模式一：标准极速解析 (纯本地，不耗 Token)
    # -----------------------------------------
    if btn_standard:
        if raw_input.strip():
            try:
                parsed = json.loads(raw_input)
                st.success("✅ 标准 JSON 解析成功！")
                st.json(parsed)
            except Exception as e:
                st.error(f"❌ 解析失败，这似乎不是标准的 JSON 格式：\n\n`{e}`\n\n👉 **强烈建议尝试点击左侧蓝色的【AI 智能清洗与解析】功能！**")
        else:
            st.warning("请输入要解析的内容。")
            
    # -----------------------------------------
    # 模式二：AI 智能重构 (专治各种不服)
    # -----------------------------------------
    if btn_ai:
        if raw_input.strip():
            with st.spinner("🧠 正在调动 AI 理解层级，清洗不规范字符..."):
                try:
                    prompt = ChatPromptTemplate.from_template(JSON_CLEANER_PROMPT)
                    
                    llm = get_llm(model_name=settings.MODEL_TEXT, temperature=0)


                    with get_openai_callback() as cb:
                        result = (prompt | llm).invoke({"text": raw_input}).content.strip()
                        
                        # ⚠️ 核心修复：用巧妙的字符串拼接避开前端 Markdown 渲染器崩溃的 Bug
                        md_marker = "`" * 3
                        if result.startswith(md_marker + "json"):
                            result = result[7:]
                        if result.startswith(md_marker):
                            result = result[3:]
                        if result.endswith(md_marker):
                            result = result[:-3]
                            
                        result = result.strip()
                        
                        parsed_json = json.loads(result)
                        st.success("🎉 AI 清洗重构成功！")
                        st.json(parsed_json, expanded=True)
                        
                        # 计费拦截
                        tokens = cb.total_tokens
                        if tokens == 0:
                            tokens = int((len(raw_input) + len(result)) * 1.2)
                        log_usage("JSON智能清洗", settings.MODEL_TEXT, tokens)
                        
                except Exception as e:
                    st.error(f"❌ AI 解析失败: {e}\n\n可能数据结构过于混乱，AI 返回的原文如下:\n{result}")
        else:
            st.warning("请输入要解析的内容。")