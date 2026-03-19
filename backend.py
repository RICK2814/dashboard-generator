from flask import Flask, request, jsonify
import os
import sqlite3
import pandas as pd
import pdfplumber
import json
from groq import Groq
from dotenv import load_dotenv

# ==============================
# LOAD ENVIRONMENT
# ==============================
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
if not GROQ_API_KEY:
    print("WARNING: GROQ_API_KEY is not set. API calls will fail.")
groq_client = Groq(api_key=GROQ_API_KEY)

UPLOAD_FOLDER = "uploads"
DB_NAME = "data.db"
TABLE_NAME = "data"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==============================
# APP INIT
# ==============================
app = Flask(__name__)

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
def load_file(file):

    filename = file.filename.lower()

    if filename.endswith(".csv"):
        df = pd.read_csv(file)

    elif filename.endswith(".xlsx"):
        df = pd.read_excel(file)

    elif filename.endswith(".pdf"):
        df = extract_pdf(file)

    else:
        raise Exception("Unsupported file type")

    if df.empty:
        raise Exception("File is empty")

    df.columns = [
        c.strip().replace(" ", "_").lower()
        for c in df.columns
    ]

    return df


# ==============================
# DATABASE
# ==============================
def save_to_db(df):
    with sqlite3.connect(DB_NAME) as conn:
        df.to_sql(TABLE_NAME, conn,
                  if_exists="replace",
                  index=False)


def run_query(sql):

    if not sql.upper().strip().startswith("SELECT"):
        raise Exception("Only SELECT allowed")

    with sqlite3.connect(DB_NAME) as conn:
        return pd.read_sql(sql, conn)


def get_schema():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({TABLE_NAME})")
        columns = cursor.fetchall()
        return ", ".join([f"{col[1]} ({col[2]})" for col in columns])


# ==============================
# GROQ HELPERS
# ==============================
def get_sql_query(user_query, schema):
    prompt_template = f"""
You are an expert SQL assistant. I have a SQLite database with a single table named `{TABLE_NAME}`.
The table has the following columns and types: {schema}

Based on the user's natural language query, output ONLY a valid SQLite SELECT query.
Do NOT wrap the output in markdown chunks like ```sql or anything else. Just the raw SQL text.

User Query: {user_query}
"""
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

def get_insights_and_charts(user_query, df_result):
    # Truncate large result sets to avoid exceeding Groq's context window
    if len(df_result) > 100:
        df_context = df_result.head(100)
        note = f"\n[WARNING: Data truncated from {len(df_result)} to 100 rows for prompt context]"
    else:
        df_context = df_result
        note = ""
        
    data_csv = df_context.to_csv(index=False) + note
    
    prompt_template = f"""
You are an expert Data Analyst and Data Visualization specialist.
The user asked: "{user_query}"
I ran an SQL query on the database and got the following data back:
{data_csv}

Please provide your response strictly as a JSON object with the following structure:
{{
  "insight": "A detailed but concise written insight. If the user's query was completely unrelated to the data (e.g. asking about salaries when the data is about sales), politely explain that you can only analyze the provided dataset, but offer an insight into this dataset instead.",
  "charts": [
    {{
      // Plotly JSON object (as a dictionary). Generate a relevant chart (e.g. bar, pie, scatter) mapping the columns from the data provided. Use the Plotly schema (data/layout structure).
      // EXTREMELY IMPORTANT: "type": "line" is INVALID in Plotly. If you want a line chart, you MUST use "type": "scatter" and "mode": "lines".
      // Valid types include: bar, pie, scatter, histogram, etc.
      "data": [ ... ],
      "layout": {{ ... }}
    }}
  ] // ALWAYS provide at least one chart if there is data.
}}

IMPORTANT: Return ONLY valid JSON, no markdown formatting like ```json or anything else.
"""
    chat_completion = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt_template}],
        model="llama-3.3-70b-versatile",
    )
    result_text = chat_completion.choices[0].message.content.strip()
    
    if result_text.startswith("```json"):
        result_text = result_text[7:]
    if result_text.startswith("```"):
        result_text = result_text[3:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]

    try:
        data = json.loads(result_text.strip())
        # Post-processing to fix 'line' to 'scatter' + 'mode': 'lines'
        if "charts" in data:
            for chart in data["charts"]:
                if "data" in chart:
                    for trace in chart["data"]:
                        if trace.get("type") == "line":
                            trace["type"] = "scatter"
                            if "mode" not in trace:
                                trace["mode"] = "lines"
        return data
    except Exception as e:
        print("JSON parse error:", e)
        # Fallback if AI output is slightly malformed
        return {"insight": "Error parsing AI response", "charts": []}


# ==============================
# ROUTES
# ==============================
@app.route("/")
def home():
    return jsonify({"status": "Backend running 🚀"})


@app.route("/upload", methods=["POST"])
def upload():

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        file = request.files["file"]
        df = load_file(file)
        save_to_db(df)

        return jsonify({
            "message": "Upload successful",
            "columns": list(df.columns)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ask", methods=["POST"])
def ask():

    data = request.get_json()

    if not data or "query" not in data:
        return jsonify({"error": "Query missing"}), 400

    try:
        user_query = data["query"]
        
        # 1. Get Schema
        schema = get_schema()
        
        # 2. Get SQL
        sql_query = get_sql_query(user_query, schema)
        print("Generated SQL:", sql_query)
        
        # 3. Run SQL with fallback
        try:
            df_result = run_query(sql_query)
        except Exception as sql_e:
            print(f"SQL failed ({sql_e}), falling back to default query.")
            df_result = run_query(f"SELECT * FROM {TABLE_NAME} LIMIT 50")
        
        # 4. Generate Insight and Charts via Gemini
        analysis = get_insights_and_charts(user_query, df_result)
        
        return jsonify({
            "insight": analysis.get("insight", "No insight generated."),
            "charts": analysis.get("charts", [])
        })

    except Exception as e:
        print("Error during ask:", e)
        return jsonify({"error": str(e)}), 500


# ==============================
# RUN SERVER
# ==============================
if __name__ == "__main__":
    print("✅ Starting Flask Backend...")
    app.run(
        host="127.0.0.1",   # FIXED
        port=5000,
        debug=True
    )