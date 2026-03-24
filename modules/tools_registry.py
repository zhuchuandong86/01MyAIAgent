# modules/tools_registry.py
import os
from datetime import datetime
from langchain.tools import tool
from duckduckgo_search import DDGS

# ==========================================
# 通用外部技能 (OpenClaw 风格)
# ==========================================

@tool
def get_current_time(timezone: str) -> str:
    """
    当用户询问现在的时间、日期、或者今天是星期几时，调用此工具。
    输入：timezone (必须填入时区字符串，例如 'Asia/Shanghai')。
    返回：当前准确的系统时间。
    """
    now = datetime.now()
    return f"当前时间是: {now.strftime('%Y-%m-%d %H:%M:%S')}，星期{now.isoweekday()} (参考时区: {timezone})"

@tool
def search_web(query: str) -> str:
    """
    当大模型的知识库里没有最新信息，或者用户要求联网查询时，调用此工具。
    输入：搜索关键词。
    返回：来自互联网的搜索结果摘要。
    """
    proxy_url = "http://z00535604:Zhu202640%@proxy.huawei.com:8080"
    os.environ['HTTP_PROXY'] = proxy_url
    os.environ['HTTPS_PROXY'] = proxy_url
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return "没有找到相关的网络结果。"
        
        formatted_results = "\n".join([f"- {res['title']}: {res['body']}" for res in results])
        return formatted_results
    except Exception as e:
        return f"搜索失败: {str(e)}"

@tool
def save_memo_to_file(content: str, filename: str = "memo.txt") -> str:
    """
    当用户要求“记下来”、“保存笔记”、“写入文件”时，调用此工具。
    输入：content (要保存的具体内容), filename (文件名，默认为 memo.txt)。
    返回：保存成功或失败的状态。
    """
    try:
        # 为了安全，固定保存在当前目录
        filepath = os.path.join(os.getcwd(), filename)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n{content}\n")
        return f"备忘录已成功追加保存到本地文件: {filepath}"
    except Exception as e:
        return f"保存文件失败: {str(e)}"

# 将所有可用的工具打包成一个列表，后续喂给大模型
EXTERNAL_TOOLS = [get_current_time, search_web, save_memo_to_file]