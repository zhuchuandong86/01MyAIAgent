# AI_Platform/app.py
import streamlit as st
import os
import ssl

import warnings
warnings.filterwarnings("ignore", category=ResourceWarning)

from dotenv import load_dotenv
load_dotenv()
INTERNAL_URL=os.getenv("INTERNAL_URL")
os.environ['NO_PROXY'] = INTERNAL_URL
ssl._create_default_https_context = ssl._create_unverified_context


st.set_page_config(page_title="内网 AI 工作台", layout="wide")
st.title("欢迎来到内网 AI 工作台总览")
st.write("采用公司内网，数据不出公司，不存在信息安全问题，请放心使用；")
st.write("请在左侧选择应用。")

