"""
memory_tools.py — Phase 1: 结构化记忆引擎
────────────────────────────────────────────────────────────
替代原先的纯文本 append，升级为：
  - JSONL 结构化存储（带标签、使用计数、成功标记）
  - 写入前自动去重（词汇重叠 > 70% 则跳过）
  - 按需关键词检索（只把相关记忆注入 prompt，不再全量塞入）
  - 定期剪枝（清除长期未被引用的低价值记忆）
  - 向后兼容：同步维护 experience_log.md 供人工查阅
"""

import os
import json
import time
from datetime import datetime, timedelta
import core.paths

WORKSPACE   = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")
MEMORY_DB   = os.path.join(WORKSPACE, "memory.jsonl")          # 机读结构化库
MEMORY_FILE = os.path.join(WORKSPACE, "experience_log.md")     # 人读 Markdown（兼容旧版）


# ──────────────────────────────────────────────────────────
# 内部 IO 工具
# ──────────────────────────────────────────────────────────

def _load_memories() -> list[dict]:
    if not os.path.exists(MEMORY_DB):
        return []
    memories = []
    with open(MEMORY_DB, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    memories.append(json.loads(line))
                except json.JSONDecodeError:
                    pass   # 跳过损坏行，不崩溃
    return memories


def _save_memories(memories: list[dict]) -> None:
    with open(MEMORY_DB, "w", encoding="utf-8") as f:
        for m in memories:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")


def _word_overlap(a: str, b: str) -> float:
    """计算两个字符串的词汇重叠率（Jaccard 相似度）"""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


# ──────────────────────────────────────────────────────────
# 公开工具函数（会被注册进 TOOL_DISPATCHER）
# ──────────────────────────────────────────────────────────

def append_memory(lesson: str, tags: str = "", success: bool = True) -> str:
    """
    结构化写入一条经验记忆。
    - lesson : 经验正文
    - tags   : 逗号分隔的标签，如 "爬虫,反爬,requests"
    - success: 是否为成功经验（失败教训传 False）
    """
    os.makedirs(WORKSPACE, exist_ok=True)
    memories = _load_memories()
    lesson_stripped = lesson.strip()

    # ── 去重检测 ──
    for m in memories:
        # 完全相同直接跳过
        if m["lesson"].strip() == lesson_stripped:
            return f"✅ 完全相同的记忆已存在，跳过重复写入。"
        # 高度相似（> 70% Jaccard）也跳过
        if len(lesson_stripped.split()) > 5 and _word_overlap(m["lesson"], lesson_stripped) > 0.70:
            return (
                f"✅ 发现高度相似记忆（重叠率 "
                f"{_word_overlap(m['lesson'], lesson_stripped):.0%}），已跳过，避免记忆污染。\n"
                f"  └─ 已有记忆: {m['lesson'][:80]}"
            )

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    entry = {
        "id":         int(time.time() * 1000),
        "lesson":     lesson_stripped,
        "tags":       tag_list,
        "success":    success,
        "use_count":  0,
        "last_used":  None,
        "created_at": datetime.now().isoformat(),
    }

    memories.append(entry)
    _save_memories(memories)

    # 向后兼容：同步写入 Markdown
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        prefix = "✅" if success else "❌教训"
        f.write(f"- [{prefix}] {lesson_stripped}\n")

    return (
        f"✅ 经验已刻入结构化记忆库 "
        f"[标签: {tag_list or '无'}]\n  └─ {lesson_stripped[:100]}"
    )


def search_memory(query: str, top_k: int = 8) -> str:
    """
    按需检索与 query 最相关的记忆条目（词汇重叠 + 使用频次加权）。
    仅返回 top_k 条，供 System Prompt 按需注入，避免全量堆积。
    """
    memories = _load_memories()
    if not memories:
        return "（记忆库为空，尚无历史经验）"

    query_words = set(query.lower().split())
    scored: list[tuple[float, dict]] = []

    for m in memories:
        lesson_words = set(m["lesson"].lower().split())
        tag_words    = set(" ".join(m.get("tags", [])).lower().split())
        all_words    = lesson_words | tag_words

        overlap    = len(query_words & all_words)
        use_bonus  = min(m.get("use_count", 0) * 0.15, 3.0)   # 使用次数奖励，最多 +3
        score      = overlap + use_bonus

        if score > 0:
            scored.append((score, m))

    if not scored:
        return "（未找到与当前任务相关的历史经验）"

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [m for _, m in scored[:top_k]]

    # 更新引用计数
    top_ids = {m["id"] for m in top}
    for m in memories:
        if m["id"] in top_ids:
            m["use_count"] = m.get("use_count", 0) + 1
            m["last_used"] = datetime.now().isoformat()
    _save_memories(memories)

    lines = []
    for m in top:
        tag_str = f"[{', '.join(m['tags'])}] " if m.get("tags") else ""
        flag    = "✅" if m.get("success", True) else "❌教训"
        lines.append(f"- {flag} {tag_str}{m['lesson']}")

    return "\n".join(lines)


def evaluate_and_prune_memory(days_threshold: int = 90, min_use_count: int = 1) -> str:
    """
    Phase 4 记忆剪枝：清除超过 days_threshold 天未被引用且
    use_count < min_use_count 的低价值记忆，防止记忆库无限膨胀。
    """
    memories = _load_memories()
    if not memories:
        return "记忆库为空，无需剪枝。"

    cutoff = datetime.now() - timedelta(days=days_threshold)
    kept, pruned = [], []

    for m in memories:
        try:
            created   = datetime.fromisoformat(m.get("created_at", datetime.now().isoformat()))
            last_used = datetime.fromisoformat(m["last_used"]) if m.get("last_used") else created
        except ValueError:
            kept.append(m)
            continue

        use_count = m.get("use_count", 0)

        if last_used < cutoff and use_count < min_use_count:
            pruned.append(m)
        else:
            kept.append(m)

    _save_memories(kept)

    # 同步重建 Markdown
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write("# 全局经验法则与底层认知\n\n")
        for m in kept:
            f.write(f"- {m['lesson']}\n")

    return (
        f"✅ 记忆剪枝完成：保留 {len(kept)} 条，"
        f"清除 {len(pruned)} 条（超过 {days_threshold} 天未引用且使用次数 < {min_use_count}）。"
    )
