"""
web_tools.py — 网络工具（增加 read_webpage 本地降级兜底）
────────────────────────────────────────────────────────────
变更说明（对比旧版）：

[修复 #5] read_webpage Jina 服务不可用时的降级处理
  - 旧版：Jina 超时或限流时静默失败，模型收到报错后无法继续
  - 新版：Jina 失败后自动降级到本地 requests + BeautifulSoup 解析
  - 双重兜底：requests 不可用时再降级到 urllib（原始实现）
"""

import urllib.request
import urllib.error


def search_web(query: str) -> str:
    """全网搜索引擎。遇到写代码报错、反爬，立刻调用查资料。"""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "无检索结果，请尝试换一个关键词。"
        return "\n---\n".join(
            [f"【{r['title']}】({r['href']}): {r['body']}" for r in results]
        )
    except ImportError:
        return (
            "❌ 缺少 duckduckgo-search 库。\n"
            "请先执行: pip install duckduckgo-search"
        )
    except Exception as e:
        return f"❌ 搜索断开: {str(e)}"


def _fetch_via_jina(url: str, timeout: int = 15) -> str:
    """通过 Jina AI Reader 将网页转为 Markdown。"""
    req = urllib.request.Request(
        f"https://r.jina.ai/{url}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response = urllib.request.urlopen(req, timeout=timeout)
    content = response.read().decode("utf-8")
    return content


def _fetch_via_requests(url: str, timeout: int = 15) -> str:
    """本地降级方案：requests + BeautifulSoup 解析。"""
    import requests
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; ZClaw/1.0)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # 移除 script / style / nav / footer 噪音
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # 提取正文
    text = soup.get_text(separator="\n", strip=True)
    # 合并连续空行
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _fetch_via_urllib(url: str, timeout: int = 15) -> str:
    """最后兜底：纯 urllib，只能获取原始 HTML。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    response = urllib.request.urlopen(req, timeout=timeout)
    return response.read().decode("utf-8", errors="replace")


def read_webpage(url: str) -> str:
    """
    通用网页阅读器。把复杂网页转成可读文本给你阅读。
    降级策略：Jina → requests+BS4 → urllib（原始 HTML）
    """
    MAX_LEN = 8000
    errors  = []

    # ── 优先：Jina AI Reader ──
    try:
        content = _fetch_via_jina(url)
        if content and len(content) > 50:
            if len(content) > MAX_LEN:
                content = content[:MAX_LEN] + "\n\n...[内容过长，已截断]..."
            return content
    except Exception as e:
        errors.append(f"Jina: {e}")

    # ── 降级 1：requests + BeautifulSoup ──
    try:
        content = _fetch_via_requests(url)
        if content and len(content) > 50:
            if len(content) > MAX_LEN:
                content = content[:MAX_LEN] + "\n\n...[内容过长，已截断]..."
            return f"[降级到本地解析]\n\n{content}"
    except ImportError:
        errors.append("requests/bs4: 库未安装")
    except Exception as e:
        errors.append(f"requests: {e}")

    # ── 降级 2：纯 urllib（原始 HTML）──
    try:
        content = _fetch_via_urllib(url)
        if len(content) > MAX_LEN:
            content = content[:MAX_LEN] + "\n\n...[内容过长，已截断]..."
        return f"[降级到原始 HTML，建议安装 requests+beautifulsoup4 获得更好解析]\n\n{content}"
    except Exception as e:
        errors.append(f"urllib: {e}")

    return (
        f"❌ 所有读取方式均失败，URL: {url}\n"
        + "\n".join([f"  - {e}" for e in errors])
    )
