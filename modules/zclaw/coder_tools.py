import os
from openai import OpenAI
import core.paths
from core.settings import settings
from core.token_tracker import log_usage  # 🌟 引入全局记账本

WORKSPACE = os.path.join(core.paths.GLOBAL_DATA_DIR, "zclaw_workspace")
# 独立实例化 Coder 客户端，不影响主循环
coder_client = OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE, timeout=120.0)
c_model = getattr(settings, "MODEL_CODER", settings.MODEL_TEXT)

def delegate_to_coder(filepath: str, task_description: str) -> str:
    sys_prompt = "你是底层算法架构师。只输出独立可运行的 Python 代码，绝对不要任何 Markdown 标记或多余的解释。如果涉及读写，注意编码(utf-8)。"
    try:
        response = coder_client.chat.completions.create(
            model=c_model,
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": f"目标路径: {filepath}\n严苛需求:\n{task_description}"}],
            temperature=0.1
        )
        
        # 🌟 核心补丁：精准捕获 Coder 专员写代码消耗的 Token！
        if hasattr(response, 'usage') and response.usage:
            log_usage("ZClaw-Coder专员", response.model, response.usage.total_tokens)

        code_content = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
        
        safe_path = os.path.abspath(os.path.join(WORKSPACE, filepath))
        if not safe_path.startswith(os.path.abspath(WORKSPACE)): return "❌ 代码注入越权拦截！"
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
            
        with open(safe_path, 'w', encoding='utf-8') as f: f.write(code_content)
        return f"👨‍💻 Coder 已成功构建代码并保存至 {filepath}。请用 execute_bash 运行它检查结果。"
    except Exception as e: return f"Coder 脑力过载: {str(e)}"