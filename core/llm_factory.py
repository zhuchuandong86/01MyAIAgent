# core/llm_factory.py
from langchain_openai import ChatOpenAI
from core.settings import settings

def get_llm(model_name: str = None, temperature: float = 0.1, streaming: bool = True) -> ChatOpenAI:
    """
    全局大模型实例化工厂 (LLM Factory)
    
    :param model_name: 模型名称，默认回退到 settings.MODEL_TEXT
    :param temperature: 温度参数，默认 0.1 保证输出的严谨性
    :param streaming: 是否强制开启流式输出与 Token 计费打点，默认 True
    :return: 实例化好的 ChatOpenAI 对象
    """
    # 自动选择模型，优先使用传入的模型，否则使用全局默认配置
    target_model = model_name or settings.MODEL_TEXT or "deepseek-v3-0324"
    
    # 统一封装底层参数
    model_kwargs = {}
    if streaming:
        # 强制内网网关在流式输出时返回 Token 使用量
        model_kwargs["stream_options"] = {"include_usage": True}

    # 实例化并返回
    return ChatOpenAI(
        model=target_model,
        api_key=settings.API_KEY,
        base_url=settings.API_BASE,
        temperature=temperature,
        model_kwargs=model_kwargs
    )