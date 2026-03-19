import streamlit as st
import requests
import plotly.io as pio
import json

# ==============================
# 🔗 BACKEND URL
# ==============================
BASE_URL = "http://127.0.0.1:5000"

st.set_page_config(page_title="AI Data Analyzer", layout="wide")

st.title("📊 AI Data Analyzer")

# ==============================
# 📤 FILE UPLOAD
# ==============================
st.header("Upload File")

uploaded_file = st.file_uploader("Upload CSV, Excel, or PDF", type=["csv", "xlsx", "pdf"])

if uploaded_file is not None:
    if st.button("Upload"):
        files = {"file": uploaded_file.getvalue()}

        response = requests.post(
            BASE_URL + "/upload",
            files={"file": (uploaded_file.name, uploaded_file.getvalue())}
        )

        res = response.json()

        if "message" in res:
            st.success(res["message"])
            st.write("Columns:", res.get("columns", []))
        else:
            st.error(res.get("error", "Upload failed"))

# ==============================
# ❓ QUERY
# ==============================
st.header("Ask Questions")

with st.form("query_form"):
    query = st.text_input("Enter your query (e.g. total revenue by product)")
    analyze_clicked = st.form_submit_button("Analyze")

if analyze_clicked:
    if not query:
        st.warning("Enter a query")
    else:
        response = requests.post(
            BASE_URL + "/ask",
            json={"query": query}
        )

        res = response.json()

        if "error" in res:
            st.error(res["error"])
        else:
            # Show insight
            st.subheader("🧠 Insight")
            st.write(res.get("insight", ""))

            # Show charts
            st.subheader("📊 Charts")

            charts = res.get("charts", [])

            if charts:
                for chart in charts:
                    # Robust JSON conversion
                    fig = pio.from_json(json.dumps(chart))
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("No charts generated")