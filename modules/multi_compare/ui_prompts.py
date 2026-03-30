# modules/multi_compare/ui_prompts.py

UI_COGNITIVE_SINGLE = """
<COGNITIVE_PROTOCOL>
【顶级投行深度思考与防幻觉协议 (极其重要)】
在输出正式研报前，你必须先在 `<thought_process>你的盘点草稿...</thought_process>` 中理清逻辑：
1. 盘点你到底拥有哪些确实存在的数据。
2. 强制深度推演：绝对禁止简单的数值罗列！用顶级投行分析师的视角，穿透数据看本质。
3. 零幻觉底线：如果某项业务没有数据支撑，强制自己在草稿中划掉它，坚决不在正式报告中胡编乱造！
4. 确认无误后，再在 `<thought_process>` 标签外部输出正式报告。
</COGNITIVE_PROTOCOL>
"""

UI_COGNITIVE_COMPARE = """
<COGNITIVE_PROTOCOL>
【顶级投行错位竞争与非对称对比协议】
在写报告前，先输出 `<thought_process>分析草稿...</thought_process>` 进行逻辑推演！
1. 交叉验证与淘汰：提取各公司数据。若某对比项A有B没有，绝不允许写“推测B相当”这种废话！
2. 升维打击（错位对比）：当口径不对齐时，不要报错，而是上升到战略分歧的高度进行投行视角的分析。
3. 深度推演：绝对禁止简单罗列！必须剖析竞争压迫感及战略意图。
</COGNITIVE_PROTOCOL>
"""

UI_COGNITIVE_TREND = """
<COGNITIVE_PROTOCOL>
【顶级投行生命周期与防幻觉协议】
在写报告前，先在 `<thought_process>草稿...</thought_process>` 中理清历年数据！
1. 甄别断层：严禁捏造由于缺失年份导致“持续增长”的假象，换连续指标分析！
2. 商业周期推演：用投行视角，指出战略拐点、第二曲线的兴衰和结构性隐患，拒绝平铺直叙。
</COGNITIVE_PROTOCOL>
"""

def GET_USER_PRIORITY(req):
    if not req.strip(): return ""
    return f"""
<USER_ABSOLUTE_PRIORITY>
【最高优执行指令】
用户亲自下达了自定义的核心焦点，本要求的优先级绝对高于一切系统大纲和经验模板！你必须将大部分笔墨用于回答和剖析以下问题：
{req}
</USER_ABSOLUTE_PRIORITY>
"""

def GET_STYLE_FUSION(templates_str):
    if not templates_str: return ""
    return f"""
<STYLE_FUSION>
【系统排版、多重经验与投行视角融合指令】
请重点吸收以下**多个**【金牌范例骨架】的排版、语气和结构深度，集百家之长进行输出。
⚠️ 铁律：只学语气和结构，严禁照抄旧数值！
=== 金牌范例骨架 ===
{templates_str}
</STYLE_FUSION>
"""

UI_CHART_MERMAID = """
<CHART_GENERATION>
【强制图表输出指令】
在分析核心数据或趋势时，你**必须**使用 Markdown 的 Mermaid 语法直接在正文中绘制出可视化图表（如 xychart 折线图/柱状图/pie饼图等）。
</CHART_GENERATION>
"""