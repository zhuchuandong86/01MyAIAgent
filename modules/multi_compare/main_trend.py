import os

# 【绝对导入】不再依赖原来的相对路径
from modules.multi_compare.api_client import call_api
from modules.multi_compare.main import get_safe_text_for_model
from core.prompts import TREND_EXTRACT, TREND_EDITOR_SYSTEM, TREND_EDITOR_USER

# 【直接读环境变量】彻底抛弃 config.py
MODEL_EDITOR = os.getenv("MODEL_EDITOR", "deepseek-v3-0324")
MODEL_TEXT = os.getenv("MODEL_TEXT", "deepseek-v3-0324")

def _extract_single_year(year_label, text):
    """Map阶段：独立提取单年的核心数据"""
    safe_text = get_safe_text_for_model(text, MODEL_TEXT)
    
    prompt = TREND_EXTRACT.format(year_label=year_label, safe_text=safe_text)

    messages = [{"role": "user", "content": prompt}]
    return call_api(messages, model_name=MODEL_TEXT, stream=False)

def generate_trend_summary(yearly_data_dict, status_ui=None):
    """Reduce阶段：按时间轴进行历史连贯性推演"""
    msg = "\n🤖 [历史趋势大脑] 启动！正在串行梳理历年数据(防并发限流)..."
    print(msg)
    if status_ui: status_ui.write(msg)
    
    extracted_results = {}
    
    # 🌟【修复】：取消并发，改为串行排队 + UI 实时打印防焦虑
    for year, text in yearly_data_dict.items():
        if year == "_STYLE_INSTRUCTION_":
            extracted_results[year] = text
            continue
            
        step_msg = f"⏳ 正在独立清洗【{year}】年的历史数据..."
        print(step_msg)
        if status_ui: status_ui.write(step_msg)
        
        extracted_results[year] = _extract_single_year(year, text)
        
        done_msg = f"✅ 【{year}】年数据清洗完毕！"
        print(done_msg)
        if status_ui: status_ui.write(done_msg)

    final_msg = "✍️ 历年时间轴梳理完毕，资深分析师正在进行战略推演..."
    print(final_msg)
    if status_ui: status_ui.write(final_msg)

    sorted_years = sorted(extracted_results.keys())
    combined_context = ""
    for year in sorted_years:
        if year == "_STYLE_INSTRUCTION_":
            combined_context += f"\n\n{extracted_results[year]}\n"
        else:
            combined_context += f"\n\n{'='*20}\n【{year} 年度提取数据】：\n{extracted_results[year]}\n{'='*20}"

    # 👇 极简的数组构建
    editor_messages = [
        {
            "role": "system", 
            "content": TREND_EDITOR_SYSTEM
        },
        {
            "role": "user", 
            "content": TREND_EDITOR_USER.format(combined_context=combined_context)
        }
    ]
    
    final_summary = call_api(editor_messages, model_name=MODEL_EDITOR, stream=True)
    return final_summary