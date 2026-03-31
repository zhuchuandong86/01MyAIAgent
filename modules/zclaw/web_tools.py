import urllib.request

def search_web(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results: return "无检索结果"
            return "\n---\n".join([f"【{r['title']}】({r['href']}): {r['body']}" for r in results])
    except ImportError:
        return "❌ 缺少 duckduckgo-search 库，请先让 Coder 执行 pip install duckduckgo-search"
    except Exception as e: return f"搜索断开: {str(e)}"

def read_webpage(url: str) -> str:
    try:
        req = urllib.request.Request(f"https://r.jina.ai/{url}", headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=15).read().decode('utf-8')
        if len(response) > 8000: return response[:8000] + "\n\n...[截断]..."
        return response
    except Exception as e: return f"❌ 读取失败: {str(e)}"