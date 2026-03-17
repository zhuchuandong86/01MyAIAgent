import os
from concurrent.futures import ThreadPoolExecutor

# 【绝对导入】不再依赖原来的相对路径
from modules.multi_compare.api_client import call_api
from modules.multi_compare.main import get_safe_text_for_model
from core.prompts import TREND_EXTRACT, TREND_EDITOR_SYSTEM, TREND_EDITOR_USER

# 【直接读环境变量】彻底抛弃 config.py
MODEL_EDITOR = os.getenv("MODEL_EDITOR", "deepseek-v3-0324")
MODEL_TEXT = os.getenv("MODEL_TEXT", "deepseek-v3-0324")

def _extract_single_year(year_label, text):
    """Map阶段：独立提取单年的核心数据"""
    print(f"[{year_label}] 历史数据正在清洗中...")
    safe_text = get_safe_text_for_model(text, MODEL_TEXT)
    
    prompt = TREND_EXTRACT.format(year_label=year_label, safe_text=safe_text)

    messages = [{"role": "user", "content": prompt}]
    return call_api(messages, model_name=MODEL_TEXT, stream=False)

def generate_trend_summary(yearly_data_dict):
    """Reduce阶段：按时间轴进行历史连贯性推演"""
    print("\n🤖 [历史趋势大脑] 启动！正在梳理时间轴...")
    
    extracted_results = {}
    with ThreadPoolExecutor(max_workers=min(len(yearly_data_dict), 5)) as executor:
        future_to_year = {
            executor.submit(_extract_single_year, year, text): year 
            for year, text in yearly_data_dict.items()
        }
        for future in future_to_year:
            year_label = future_to_year[future]
            extracted_results[year_label] = future.result()

    sorted_years = sorted(extracted_results.keys())
    combined_context = ""
    for year in sorted_years:
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