# pages/09_🌍_09全网研究员.py
import streamlit as st
import os
import time
from datetime import datetime
from core.settings import settings
from core.token_tracker import log_usage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.callbacks.manager import get_openai_callback

# 页面配置
st.set_page_config(page_title="全网深度研究员", page_icon="🌍", layout="wide")
st.title("🌍 全网深度研究员 (精准时空版)")
st.markdown("突破单次搜索限制，AI 将自主拆解您的研究课题，进行**多维度并发搜索**，最终合成带独立来源引用的深度研报。")

# ==========================================
# 1. 核心提示词定义 (🌟 强制标准 Markdown 强溯源格式)
# ==========================================
PLANNER_PROMPT = """你是一个顶级的互联网情报搜索专家。

请将用户的研究课题，拆解为 1 到 5个最核心、最利于在搜索引擎中查询的底层关键词。
【核心纪律】(极其重要)：
1. 保持精简：搜索词应该像普通人类在谷歌里搜的那样，不要包含大长句。
2. 高级语法：如果用户指定了网站，你**必须**在关键词开头加上 `site:域名`。
3. 语言对齐：涉及海外信息、海外网站，必须翻译成【纯英文】关键词去查，避免中文网站信息不足；但是如果搜索国内的则反过来以中文搜索为主。
4. 动态数量：目标极度明确则 1 个词，课题宏大最多拆解 5 个词。

【强制要求】：只输出关键词，用英文逗号分隔，不要有任何多余的废话。
课题：{topic}"""

SYNTHESIZER_PROMPT = """你是一名首席行业分析师。请根据以下【深度网络情报】，为用户撰写一份极其详尽的深度研报。
【系统当前真实物理时间】：{current_time}

【撰写要求 - 强制遵守】：
1. 采用标准的 Markdown 格式，排版必须专业、有层次感。
2. **严审时间**：请严格对比系统当前时间，甄别情报中的发布时间。无情剔除掉过时的陈旧信息，只提炼最新的有效情报！
3. **拒绝空洞**：必须把情报中的具体数据、公司名、核心人物、关键事件全部写进报告正文。
4. **正文角标溯源（强制超链接）**：在引用的新闻事件或数据旁，必须使用标准 Markdown 语法生成可点击的超链接。格式严格为：`[[来源:网站名]](完整的URL链接)`。注意：中括号和小括号之间绝对不能有空格！
5. **文末附录（强制超链接）**：在研报最后，必须单独开辟 `### 📚 参考资料` 模块，使用标准 Markdown 列表输出。格式严格为：`- [文章原标题](完整的URL链接)`。注意：中括号和小括号之间绝对不能有空格！

【研究课题】: {topic}

【最新网络情报总汇】:
{info}
"""

# ==========================================
# 2. UI 交互与主控制流
# ==========================================
topic = st.text_input("🎯 请输入您想研究的课题 (例如：查一下今天的南非科技新闻)：")

if st.button("🚀 启动全网深度侦查", type="primary"):
    if not topic.strip():
        st.warning("⚠️ 请输入研究课题！")
        st.stop()

    llm = ChatOpenAI(
        model=settings.MODEL_TEXT or "deepseek-v3-0324", 
        api_key=settings.API_KEY, 
        base_url=settings.API_BASE, 
        temperature=0.2
    )

    report_container = st.empty()
    current_time_str = datetime.now().strftime("%Y年%m月%d日")
    
    with st.status("🕵️‍♂️ 深度研究员正在工作中...", expanded=True) as status:
        with get_openai_callback() as cb:
            
            # --- 步骤 1：拆解子问题 ---
            status.write(f"🧠 正在拆解检索策略...")
            try:
                prompt_plan = ChatPromptTemplate.from_template(PLANNER_PROMPT)
                queries_str = (prompt_plan | llm | StrOutputParser()).invoke({"topic": topic})
                queries = [q.strip() for q in queries_str.split(',') if q.strip()][:5] 
                status.write(f"🔍 敲定极客搜索指令: `{queries}`")
            except Exception as e:
                status.update(label="❌ 课题拆解失败", state="error")
                st.error(f"大模型调用异常: {e}")
                st.stop()

            # --- 步骤 2：真实网络搜索 ---
            status.write("🌐 正在连接互联网获取最新情报...")
            try:
                from langchain_community.tools import DuckDuckGoSearchResults
                from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
                
                time_filter = None
                topic_lower = topic.lower()
                
                if any(kw in topic_lower for kw in ["今天", "今日", "today", "24小时"]):
                    time_filter = "d"  
                    status.write("⏰ 开启【极速时效】：底层引擎已锁定过去 24 小时内的新闻！")
                elif any(kw in topic_lower for kw in ["本周", "最新", "latest", "now", "当前"]):
                    time_filter = "w"  
                    status.write("⏰ 开启【强时效】：底层引擎已锁定过去 7 天内的新闻！")
                elif any(kw in topic_lower for kw in ["本月", "这个月", "最近", "this month"]):
                    time_filter = "m"  
                    status.write("⏰ 开启【中时效】：底层引擎已锁定过去 1 个月内的新闻！")
                    
                wrapper = DuckDuckGoSearchAPIWrapper(time=time_filter, max_results=6)
                
            except ImportError:
                st.error("缺少依赖库，请在终端运行: `pip install duckduckgo-search`")
                st.stop()
            
            aggregated_info = ""
            for q in queries:
                try:
                    status.write(f"📡 深度检索: `{q}` ...")
                    raw_results = wrapper.results(q[:80], max_results=6)
                    
                    if raw_results:
                        aggregated_info += f"=== 【检索指令: {q}】的情报 ===\n"
                        for res in raw_results:
                            aggregated_info += f"- 标题: {res.get('title')}\n"
                            aggregated_info += f"  链接: {res.get('link')}\n"
                            aggregated_info += f"  摘要: {res.get('snippet')}\n\n"
                        status.write(f"✅ 获取到 `{q}` 的丰富情报")
                    else:
                        status.write(f"⚠️ `{q}` 未检索到有效内容。")
                except Exception as e:
                    error_msg = str(e)
                    if "Timeout" in error_msg or "Proxy" in error_msg or "SSL" in error_msg:
                        status.write(f"⚠️ 搜索 `{q}` 失败：被企业内网防火墙拦截。")
                    else:
                        status.write(f"⚠️ 搜索 `{q}` 异常：{error_msg}")
            
            if not aggregated_info.strip():
                status.update(label="❌ 研究中止：未能获取到任何公网信息", state="error")
                st.warning("系统由于所处网络环境限制，未能连接到外网搜索引擎。")
                st.stop()
                
            status.write(f"📥 情报总汇完毕，总长 {len(aggregated_info)} 字符。")

            # --- 步骤 3：提炼研报 ---
            status.write("📝 正在提炼海量数据，撰写带溯源的深度研报...")
            prompt_report = ChatPromptTemplate.from_template(SYNTHESIZER_PROMPT)
            
            status.update(label="✅ 网络情报采集完毕，正在输出最终报告！", state="complete", expanded=False)
            
            report = ""
            st.markdown("### 📑 全网深度研究报告")
            
            try:
                for chunk in (prompt_report | llm | StrOutputParser()).stream({
                    "topic": topic, 
                    "info": aggregated_info,
                    "current_time": current_time_str
                }):
                    report += chunk
                    report_container.markdown(report + " ▌")
                # 正常渲染，Streamlit会自动将标准 Markdown 外链转化为新标签页打开
                report_container.markdown(report)
                
                log_usage("全网研究员(精准溯源版)", settings.MODEL_TEXT, cb.total_tokens)
                
            except Exception as e:
                report_container.error(f"❌ 报告撰写中断: {e}")
                st.stop()

    st.download_button(
        label="⬇️ 一键下载研报 (Markdown)", 
        data=report, 
        file_name=f"深度研报_{topic[:10]}.md",
        type="primary"
    )