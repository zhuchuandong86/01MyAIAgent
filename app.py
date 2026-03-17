# AI_Platform/app.py
import streamlit as st
import os

from dotenv import load_dotenv
load_dotenv()
INTERNAL_URL=os.getenv("INTERNAL_URL")
os.environ['NO_PROXY'] = INTERNAL_URL

st.set_page_config(page_title="内网 AI 工作台", layout="wide")
st.title("欢迎来到 AI 工作台总览")
st.write("请在左侧选择应用。")