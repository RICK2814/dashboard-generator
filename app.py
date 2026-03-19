import streamlit as st
import pandas as pd
import plotly
import plotly.io as pio
import plotly.express as px
import plotly.graph_objects as go
import json
import sqlite3
import os
from groq import Groq
from dotenv import load_dotenv
import pdfplumber
import io

# ==============================
# LOAD ENVIRONMENT
# ==============================
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
if not GROQ_API_KEY:
    st.warning("⚠️ GROQ_API_KEY not set. AI features will not work.")
groq_client = Groq(api_key=GROQ_API_KEY)

# ==============================
# CONFIG
# ==============================
DB_NAME = "data.db"
TABLE_NAME = "data"

st.set_page_config(page_title="AI Data Analyzer", layout="wide")
st.title("📊 AI Data Analyzer")

# ==============================
# PDF EXTRACTION
# ==============================
def extract_pdf(file):
    rows = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table:
                rows.extend(table[1:])
    if not rows:
        raise Exception("No table found in PDF")
    df = pd.DataFrame(rows)
    df.columns = [f"col_{i}" for i in range(len(df.columns))]
    return df

# ==============================
# FILE LOADER
# ==============================
def load_file(uploaded_file):
    filename = uploaded_file.name.lower()
    file_content = uploaded_file.getvalue()

    if filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_content))
    elif filename.endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(file_content))
    elif filename.endswith(".pdf"):
        # Save to temp file for pdfplumber
        with open("temp.pdf", "wb") as f:
            f.write(file_content)
        df = extract_pdf("temp.pdf")
        os.remove("temp.pdf")
    else:
        raise Exception("Unsupported file type")

    if df.empty:
        raise Exception("File is empty")

    df.columns = [c.strip().replace(" ", "_").lower() for c in df.columns]
    return df

# ==============================
# DATABASE FUNCTIONS
# ==============================
def save_to_db(df):
    with sqlite3.connect(DB_NAME) as conn:
        df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)

def run_query(sql):
    if not sql.upper().strip().startswith("SELECT"):
        raise Exception("Only SELECT queries allowed")
    with sqlite3.connect(DB_NAME) as conn:
        return pd.read_sql(sql, conn)

def get_schema():
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({TABLE_NAME})")
            columns = cursor.fetchall()
            return ", ".join([f"{col[1]} ({col[2]})" for col in columns])
    except:
        return "No data loaded yet"

# ==============================
# AI FUNCTIONS
# ==============================
def get_sql_query(user_query, schema):
    prompt_template = f"""
You are an expert SQL assistant. I have a SQLite database with a single table named `{TABLE_NAME}`.
The table has the following columns and types: {schema}

Based on the user's natural language query, output ONLY a valid SQLite SELECT query.
Do NOT wrap the output in markdown chunks. Just the raw SQL text.

User Query: {user_query}
"""
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt_template}],
            model="llama-3.3-70b-versatile",
        )
        sql = chat_completion.choices[0].message.content.strip()
        if sql.startswith("```sql"):
            sql = sql[6:]
        if sql.startswith("```"):
            sql = sql[3:]
        if sql.endswith("```"):
            sql = sql[:-3]
        return sql.strip()
    except Exception as e:
        st.error(f"AI query generation failed: {str(e)}")
        return None

def get_insights_and_charts(user_query, df_result):
    if len(df_result) > 100:
        df_context = df_result.head(100)
        note = f"\n[Data truncated from {len(df_result)} to 100 rows for analysis]"
    else:
        df_context = df_result
        note = ""

    data_csv = df_context.to_csv(index=False) + note

    prompt_template = f"""
You are an expert Data Analyst and Data Visualization specialist.
The user asked: "{user_query}"
Here is the query result data:
{data_csv}

Please provide:
1. Key insights from this data
2. A recommended chart type and why
3. Chart configuration in JSON format

Format your response as JSON with keys: "insights", "chart_type", "chart_config"
"""

    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt_template}],
            model="llama-3.3-70b-versatile",
        )
        response = chat_completion.choices[0].message.content.strip()

        # Try to parse JSON response
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        result = json.loads(response.strip())
        return result
    except Exception as e:
        st.error(f"AI analysis failed: {str(e)}")
        return None

# ==============================
# STREAMLIT UI
# ==============================

# File Upload Section
st.header("📤 Upload Data File")
uploaded_file = st.file_uploader("Upload CSV, Excel, or PDF", type=["csv", "xlsx", "pdf"])

if uploaded_file is not None:
    if st.button("Process File"):
        try:
            df = load_file(uploaded_file)
            save_to_db(df)
            st.success(f"✅ File processed successfully! Loaded {len(df)} rows, {len(df.columns)} columns.")
            st.write("**Columns:**", ", ".join(df.columns.tolist()))
            st.dataframe(df.head())
        except Exception as e:
            st.error(f"❌ Error processing file: {str(e)}")

# Query Section
st.header("❓ Ask Questions About Your Data")

schema = get_schema()
if schema != "No data loaded yet":
    st.info(f"**Database Schema:** {schema}")

with st.form("query_form"):
    query = st.text_input("Enter your question (e.g., 'total revenue by product', 'sales trend over time')")
    submitted = st.form_submit_button("Analyze")

if submitted and query:
    if schema == "No data loaded yet":
        st.warning("Please upload a data file first.")
    else:
        with st.spinner("Generating SQL query..."):
            sql = get_sql_query(query, schema)

        if sql:
            st.code(sql, language="sql")

            try:
                with st.spinner("Running query..."):
                    result_df = run_query(sql)

                st.success(f"Query executed successfully! Found {len(result_df)} results.")

                if not result_df.empty:
                    st.dataframe(result_df)

                    # AI Analysis
                    with st.spinner("Generating insights and visualizations..."):
                        analysis = get_insights_and_charts(query, result_df)

                    if analysis:
                        st.subheader("🤖 AI Insights")
                        st.write(analysis.get("insights", "No insights available"))

                        # Create chart based on AI recommendation
                        chart_type = analysis.get("chart_type", "bar").lower()
                        chart_config = analysis.get("chart_config", {})

                        try:
                            if "bar" in chart_type:
                                if len(result_df.columns) >= 2:
                                    fig = px.bar(result_df, x=result_df.columns[0], y=result_df.columns[1],
                                               title=f"{query}")
                                    st.plotly_chart(fig)
                            elif "line" in chart_type:
                                if len(result_df.columns) >= 2:
                                    fig = px.line(result_df, x=result_df.columns[0], y=result_df.columns[1],
                                                title=f"{query}")
                                    st.plotly_chart(fig)
                            elif "pie" in chart_type:
                                if len(result_df.columns) >= 2:
                                    fig = px.pie(result_df, names=result_df.columns[0], values=result_df.columns[1],
                                               title=f"{query}")
                                    st.plotly_chart(fig)
                            else:
                                # Default bar chart
                                if len(result_df.columns) >= 2:
                                    fig = px.bar(result_df, x=result_df.columns[0], y=result_df.columns[1],
                                               title=f"{query}")
                                    st.plotly_chart(fig)
                        except Exception as e:
                            st.warning(f"Could not create chart: {str(e)}")
                else:
                    st.info("Query returned no results.")

            except Exception as e:
                st.error(f"❌ Query execution failed: {str(e)}")