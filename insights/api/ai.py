# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe

from insights.decorators import insights_whitelist
from insights.insights.doctype.insights_data_source_v3.ibis_utils import (
    execute_ibis_query,
    get_columns_from_schema,
)
from insights.insights.doctype.insights_data_source_v3.insights_data_source_v3 import (
    db_connections,
)

# statements that must never reach the database, checked as whole words
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|exec|execute|merge)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You are a SQL analyst. Write a single {dialect} SELECT statement that answers the user's question.

Rules:
- Output ONLY the SQL inside a ```sql code fence, nothing else.
- A single SELECT (or WITH ... SELECT) statement. Never modify data.
- Limit results to at most 100 rows unless the question implies fewer.
- Use only these tables and columns:

{schema}"""


def get_ollama_config() -> tuple[str, str]:
    url = (frappe.conf.get("ollama_url") or "http://localhost:11434").rstrip("/")
    model = frappe.conf.get("ollama_model") or "qwen2.5-coder:7b"
    return url, model


def ask_claude(question: str, dialect: str, schema: str) -> str:
    """Generate SQL with Claude via the Anthropic API. Used when
    'anthropic_api_key' is set in site config."""
    try:
        import anthropic
    except ImportError:
        frappe.throw(
            "The 'anthropic' package is not installed. "
            "Run 'bench pip install anthropic' and restart the bench."
        )

    client = anthropic.Anthropic(api_key=frappe.conf.get("anthropic_api_key"))
    model = frappe.conf.get("anthropic_model") or "claude-opus-4-8"

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            # cache the schema-bearing prompt: repeated questions against the
            # same data source reuse it at ~0.1x input cost
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT.format(dialect=dialect, schema=schema),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": question.strip()}],
        )
    except anthropic.AuthenticationError:
        frappe.throw("The Anthropic API key was rejected — check 'anthropic_api_key' in site config.")
    except anthropic.RateLimitError:
        frappe.throw("Anthropic rate limit reached — try again in a moment.")
    except anthropic.APIStatusError as e:
        frappe.throw(f"Claude API error: {e.message}")
    except anthropic.APIConnectionError:
        frappe.throw("Could not reach the Claude API — check the server's internet access.")

    if response.stop_reason == "refusal":
        frappe.throw("Claude declined to answer this question.")

    return "".join(block.text for block in response.content if block.type == "text")


def ask_ollama(question: str, dialect: str, schema: str) -> str:
    """Generate SQL with a self-hosted Ollama model. The default when no
    Anthropic API key is configured."""
    import requests

    url, model = get_ollama_config()
    try:
        response = requests.post(
            f"{url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT.format(dialect=dialect, schema=schema),
                    },
                    {"role": "user", "content": question.strip()},
                ],
                "temperature": 0.1,
                "stream": False,
            },
            timeout=180,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        frappe.throw(
            f"Could not reach the AI model at {url}. "
            "Set 'ollama_url' and 'ollama_model' in site config and make sure Ollama is running, "
            "or set 'anthropic_api_key' to use Claude instead."
        )

    return response.json()["choices"][0]["message"]["content"]


def build_schema_context(data_source: str, max_tables: int = 10) -> str:
    """Compact schema description for the prompt. Views first — the curated
    semantic layer — then tables; cached because reading remote schemas is
    slow. Stored procedures are excluded (not directly queryable)."""

    def _build():
        ds = frappe.get_doc("Insights Data Source v3", data_source)
        tables = frappe.get_all(
            "Insights Table v3",
            filters={"data_source": data_source},
            fields=["table", "object_type"],
            order_by="object_type desc, table asc",  # View > Table alphabetically
            limit=500,
        )
        tables = [t for t in tables if not t.table.startswith("sp:")]
        # views first, then tables, capped to keep the prompt small
        tables = sorted(tables, key=lambda t: 0 if t.object_type == "View" else 1)
        tables = tables[:max_tables]

        lines = []
        with db_connections():
            for t in tables:
                try:
                    schema = ds.get_ibis_table(t.table).schema()
                    columns = ", ".join(f"{name} {dtype}" for name, dtype in schema.items())
                    lines.append(f"- {t.table}({columns})")
                except Exception:
                    continue
        return "\n".join(lines)

    cache_key = f"insights_ai_schema:{data_source}"
    cached = frappe.cache.get_value(cache_key)
    if cached:
        return cached
    context = _build()
    frappe.cache.set_value(cache_key, context, expires_in_sec=600)
    return context


def extract_sql(content: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.+?)```", content, re.DOTALL | re.IGNORECASE)
    sql = (fenced.group(1) if fenced else content).strip().rstrip(";").strip()
    return sql


def validate_sql(sql: str) -> None:
    if not re.match(r"^\s*(select|with)\b", sql, re.IGNORECASE):
        frappe.throw("The generated query is not a SELECT statement; refusing to run it.")
    if ";" in sql:
        frappe.throw("Multiple statements are not allowed.")
    if FORBIDDEN_SQL.search(sql):
        frappe.throw("The generated query contains a forbidden statement; refusing to run it.")


@insights_whitelist()
def ask(data_source: str, question: str):
    """Answer a plain-English question with AI-generated SQL, executed
    read-only against the data source. Uses Claude (Anthropic API) when
    'anthropic_api_key' is set in site config, otherwise a self-hosted
    Ollama model."""
    if not question or not question.strip():
        frappe.throw("Ask a question first")
    if not frappe.db.exists("Insights Data Source v3", data_source):
        frappe.throw("Data source not found")

    ds = frappe.get_doc("Insights Data Source v3", data_source)
    dialect = ds.get_sqlglot_dialect() or "ansi"
    schema = build_schema_context(data_source)
    if not schema:
        frappe.throw("Could not read any table schemas for this data source")

    if frappe.conf.get("anthropic_api_key"):
        content = ask_claude(question, dialect, schema)
    else:
        content = ask_ollama(question, dialect, schema)

    sql = extract_sql(content)
    validate_sql(sql)

    with db_connections():
        backend = ds._get_ibis_backend()
        query = backend.sql(sql)
        results, time_taken = execute_ibis_query(query, page_size=200, cache=False)

    return {
        "sql": sql,
        "columns": get_columns_from_schema(query.schema()),
        "rows": results.to_dict(orient="records"),
        "time_taken": time_taken,
    }
