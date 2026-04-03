# modules/zclaw/web_tools.py
import os
import urllib.request
import urllib.parse
import urllib.error
import requests
import urllib3
from bs4 import BeautifulSoup
from core.settings import settings

# 🌟 终极修复：屏蔽 urllib3 抛出的“未校验 HTTPS”红字警告，保持终端干净
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MAX_LEN = 8000

# ==========================================
# 1. 代理配置恢复 (核心：内网保命符)
# ==========================================
PROXY_HOST = os.getenv("PROXY_HOST")  
PROXY_USER = os.getenv("PROXY_USER")  
PROXY_PASS = os.getenv("PROXY_PASS")  

PROXIES_DICT = None
PROXY_URL = None

if PROXY_HOST:
    if PROXY_USER and PROXY_PASS:
        safe_user = urllib.parse.quote(PROXY_USER, safe="")
        safe_pass = urllib.parse.quote(PROXY_PASS, safe="")
        PROXY_URL = f"http://{safe_user}:{safe_pass}@{PROXY_HOST.replace('http://', '')}"
    else:
        PROXY_URL = f"http://{PROXY_HOST.replace('http://', '')}"
    PROXIES_DICT = {"http": PROXY_URL, "https": PROXY_URL}


# ==========================================
# 2. 全网搜索引擎 (Tavily 主力 + Bing 兜底)
# ==========================================
def search_web(query: str) -> str:
    """全网搜索。带有严格错误提示的排错版"""
    tavily_key = getattr(settings, "tavily_key", None)
    
    debug_msg = ""
    
    if not tavily_key:
        debug_msg = "⚠️ [前端提示：Tavily 密钥未生效，未在 settings.py 中读到 TAVILY_API_KEY，已自动降级 Bing]\n\n"
    else:
        # ── 路径一：Tavily API ──
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tavily_key,
                    "query": query,
                    "max_results": 5,
                    "search_depth": "basic",
                },
                proxies=PROXIES_DICT, 
                timeout=15,
                verify=False  # 无视企业网关证书
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            
            if results:
                lines = []
                for r in results:
                    lines.append(
                        f"【{r.get('title', '无标题')}】\n"
                        f"链接: {r.get('url', '')}\n"
                        f"摘要: {r.get('content', '')[:300]}"
                    )
                return "✅ [由 Tavily API 强力驱动]\n---\n" + "\n---\n".join(lines)
        except Exception as e:
            # 把报错信息直接打印到界面上，让我们看看到底卡在哪里！
            debug_msg = f"⚠️ [前端提示：Tavily 请求失败，报错: {str(e)}。已自动降级 Bing]\n\n"

    # ── 路径二：Bing 爬虫 (兜底) ──
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
    
    try:
        resp = requests.get(url, headers=headers, proxies=PROXIES_DICT, timeout=15, verify=False)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for li in soup.find_all("li", class_="b_algo"):
            title_tag = li.find("h2")
            desc_tag = li.find("div", class_="b_caption") or li.find("p")
            if title_tag and desc_tag:
                title = title_tag.get_text(strip=True)
                link = title_tag.find("a")["href"] if title_tag.find("a") else ""
                desc = desc_tag.get_text(strip=True)
                results.append(f"【{title}】({link})\n摘要: {desc}")
                
        if not results:
            return debug_msg + "无检索结果，可能被搜索引擎防爬机制拦截。"
            
        return debug_msg + "\n---\n".join(results[:5])
        
    except Exception as e:
        return debug_msg + f"❌ 所有搜索路径均断开: {str(e)}"

# ==========================================
# 3. 网页阅读器 (Jina + BS4 + Raw 三级降级)
# ==========================================
def _jina(url: str) -> str:
    import ssl
    # 🌟 终极修复：给原生 urllib 创建一个不验证证书的上下文
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    if PROXY_URL:
        proxy_handler = urllib.request.ProxyHandler({'http': PROXY_URL, 'https': PROXY_URL})
        opener = urllib.request.build_opener(proxy_handler, urllib.request.HTTPSHandler(context=ctx))
        urllib.request.install_opener(opener)

    req = urllib.request.Request(
        f"https://r.jina.ai/{url}",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"},
    )
    # 如果上面没配 opener，这里也要传 context=ctx
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return r.read().decode("utf-8")

def _bs4(url: str) -> str:
    # 🌟 终极修复：加入 verify=False
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, proxies=PROXIES_DICT, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    lines = [l for l in soup.get_text("\n", strip=True).splitlines() if l.strip()]
    return "\n".join(lines)

def _urllib_raw(url: str) -> str:
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    if PROXY_URL:
        proxy_handler = urllib.request.ProxyHandler({'http': PROXY_URL, 'https': PROXY_URL})
        opener = urllib.request.build_opener(proxy_handler, urllib.request.HTTPSHandler(context=ctx))
        urllib.request.install_opener(opener)
        
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return r.read().decode("utf-8", errors="replace")

def read_webpage(url: str) -> str:
    """把网页转成可读文本。三级降级：Jina → requests+BS4 → urllib。"""
    errors = []

    for name, fn in [("Jina", _jina), ("requests+BS4", _bs4), ("urllib", _urllib_raw)]:
        try:
            content = fn(url)
            if content and len(content) > 50:
                if len(content) > MAX_LEN:
                    content = content[:MAX_LEN] + "\n…[内容过长，已截断]…"
                prefix = "" if name == "Jina" else f"[{name} 降级读取]\n\n"
                return prefix + content
        except ImportError:
            errors.append(f"{name}: 库未安装")
        except Exception as e:
            errors.append(f"{name}: {e}")

    return "❌ 所有读取方式均失败:\n" + "\n".join(f"  - {e}" for e in errors)

# ==========================================
# 4. Schema 与 分发器
# ==========================================
SCHEMA = [
    {
        "name": "search_web",
        "description": "全网搜索。遇到不知道的知识、最新资讯、报错信息，立刻调用。优先使用 Tavily 高质量检索。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，简洁具体，1-6 词最佳"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_webpage",
        "description": "读取指定 URL 的网页内容，转为纯文本。适合深入阅读长篇文档、博客或新闻全文。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "完整 URL，含 https://"}
            },
            "required": ["url"],
        },
    },
]