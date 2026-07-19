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
- Exactly ONE SELECT (or WITH ... SELECT) statement — never two. When the
  question has multiple parts, answer all parts in one result set: GROUP BY
  the relevant dimensions, or UNION ALL labeled subqueries.
- Never modify data.
- Today is {today}. When a month is named without a year, use the most
  recent occurrence of that month.
- Limit results to at most 100 rows unless the question implies fewer.
- Prefer the CVT_* views when they cover the question.
- Use only these tables and columns:

{schema}"""

ANALYSIS_PROMPT = """You are a financial analyst writing for a business owner.
Analyze the data the user provides and reply with a concise narrative:

- Key trends and totals (state the actual numbers from the data)
- Notable variances, outliers or concentrations
- Ratios or comparisons where the data supports them
- Two or three actionable observations

Rules: use short markdown bullet points; plain language, no jargon; never
invent numbers that are not derivable from the provided data; if the data is
insufficient for a claim, say so instead of guessing."""


def get_ollama_config() -> tuple[str, str]:
    url = (frappe.conf.get("ollama_url") or "http://localhost:11434").rstrip("/")
    model = frappe.conf.get("ollama_model") or "qwen2.5-coder:7b"
    return url, model


def ask_claude(question: str, system: str) -> str:
    """Run a prompt through Claude via the Anthropic API. Used when
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
            # cache the system prompt: repeated calls against the same data
            # source reuse it at ~0.1x input cost
            system=[
                {
                    "type": "text",
                    "text": system,
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


def ask_ollama(question: str, system: str, model: str | None = None) -> str:
    """Run a prompt through a self-hosted Ollama model. The default when no
    Anthropic API key is configured."""
    import requests

    url, default_model = get_ollama_config()
    model = model or default_model
    try:
        response = requests.post(
            f"{url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
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


# the SAP B1 tables that answer 95% of business questions: sales, credit
# notes, deliveries, purchases, master data, inventory, GL and payments.
# Without this tier, an alphabetical sort fills the table budget with
# obscure tables (AAC1, ACR1, ...) before any document table appears.
CORE_B1_TABLES = {
    "OINV", "INV1", "ORIN", "RIN1", "ODLN", "DLN1", "ORDR", "RDR1",
    "OPCH", "PCH1", "OPOR", "POR1",
    "OCRD", "OITM", "OITB", "OITW", "OINM", "OSLP",
    "JDT1", "OACT", "ORCT", "OVPM", "OPRC", "OPRJ",
}

# compact semantics the model can't infer from column names alone; appended
# to the schema context when the core document tables are present
B1_SCHEMA_HINTS = """
SAP B1 notes:
- Sales: OINV (invoice header: DocDate, CardName, DocTotal, CANCELED) + INV1 (lines: ItemCode, Dscription, Quantity, LineTotal). Best sellers = SUM over INV1 joined to OINV. Always filter OINV.CANCELED = 'N'.
- Credit notes ORIN/RIN1 reduce sales. Purchases: OPCH/PCH1. GL journal: JDT1 joined to OACT.
- OINM is the warehouse stock journal, NOT sales revenue."""


def _table_priority(t) -> tuple:
    """Curated semantic-layer views first (CVT_*, V_*), then other custom
    views, then the core B1 document tables, then remaining tables. SAP B1's
    built-in B1_* system views last — they crowd out the useful schema and
    mislead the model."""
    name = (t.table or "").upper()
    if name.startswith(("CVT_", "V_")):
        rank = 0
    elif t.object_type == "View" and not name.startswith("B1_"):
        rank = 1
    elif name in CORE_B1_TABLES:
        rank = 2
    elif t.object_type != "View":
        rank = 3
    else:
        rank = 4
    return (rank, name)


def build_schema_context(data_source: str, max_tables: int = 20, max_columns: int = 40) -> str:
    """Compact schema description for the prompt, prioritized so the curated
    semantic layer wins the table budget; cached because reading remote
    schemas is slow. Stored procedures are excluded (not directly queryable)."""

    def _build():
        ds = frappe.get_doc("Insights Data Source v3", data_source)
        tables = frappe.get_all(
            "Insights Table v3",
            filters={"data_source": data_source},
            fields=["table", "object_type"],
            limit=500,
        )
        tables = [t for t in tables if not t.table.startswith("sp:")]
        tables = sorted(tables, key=_table_priority)
        tables = tables[:max_tables]

        lines = []
        with db_connections():
            for t in tables:
                try:
                    schema = ds.get_ibis_table(t.table).schema()
                    items = list(schema.items())
                    # cap the column list: B1 base tables have hundreds of
                    # columns, which balloons the prompt and makes CPU
                    # inference painfully slow
                    columns = ", ".join(f"{name} {dtype}" for name, dtype in items[:max_columns])
                    if len(items) > max_columns:
                        columns += f", ... plus {len(items) - max_columns} more columns"
                    lines.append(f"- {t.table}({columns})")
                except Exception:
                    continue

        context = "\n".join(lines)
        included = {t.table.upper() for t in tables}
        if included & {"OINV", "INV1", "JDT1", "OINM"}:
            context += "\n" + B1_SCHEMA_HINTS
        return context

    # bump the version suffix whenever the semantic layer changes shape so
    # deployed sites pick up the new columns without waiting out the TTL
    cache_key = f"insights_ai_schema_v4:{data_source}"
    cached = frappe.cache.get_value(cache_key)
    if cached:
        return cached
    context = _build()
    # schemas rarely change; a long TTL keeps repeat asks fast. Update Tables
    # or bench clear-cache refreshes it when the catalog changes.
    frappe.cache.set_value(cache_key, context, expires_in_sec=6 * 60 * 60)
    return context


def extract_sql(content: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.+?)```", content, re.DOTALL | re.IGNORECASE)
    sql = (fenced.group(1) if fenced else content).strip().rstrip(";").strip()
    return sql


def normalize_sql(sql: str, dialect: str | None) -> str:
    """Small models emit MySQL-flavored SQL (LIMIT, backticks) no matter
    which dialect the prompt asks for; transpile to the target dialect as a
    best effort (e.g. LIMIT 10 -> SELECT TOP 10 on SQL Server). Falls back
    to the original SQL when nothing parses."""
    if not dialect:
        return sql
    import sqlglot

    for read in (dialect, "mysql", None):
        try:
            statements = sqlglot.transpile(sql, read=read, write=dialect)
        except Exception:
            continue
        # keep multiple statements joined so validate_sql rejects them with
        # its clear message instead of silently running just the first
        return ";\n".join(statements) if statements else sql
    return sql


def validate_sql(sql: str) -> str | None:
    """Return a user-facing error message when the SQL must not run, else None."""
    statements = [s for s in sql.split(";") if s.strip()]
    if len(statements) > 1:
        return (
            f"The AI answered with {len(statements)} separate queries, but only one can run. "
            "Rephrase as a single question, or ask each part separately."
        )
    if not re.match(r"^\s*(select|with)\b", sql, re.IGNORECASE):
        return "The generated query is not a SELECT statement; refusing to run it."
    if FORBIDDEN_SQL.search(sql):
        return "The generated query contains a forbidden statement; refusing to run it."
    return None


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

    system = SYSTEM_PROMPT.format(
        dialect=dialect, schema=schema, today=frappe.utils.nowdate()
    )
    if frappe.conf.get("anthropic_api_key"):
        content = ask_claude(question, system)
    else:
        content = ask_ollama(question, system)

    sql = normalize_sql(extract_sql(content), dialect)
    # return the SQL alongside any failure so the user can see what the
    # model wrote instead of a bare error toast
    error = validate_sql(sql)
    if error:
        return {"sql": sql, "error": error}

    with db_connections():
        backend = ds._get_ibis_backend()
        try:
            query = backend.sql(sql)
            results, time_taken = execute_ibis_query(query, page_size=200, cache=False)
        except Exception as e:
            return {"sql": sql, "error": f"The generated SQL failed to run: {e}"}

    return {
        "sql": sql,
        "columns": get_columns_from_schema(query.schema()),
        "rows": results.to_dict(orient="records"),
        "time_taken": time_taken,
    }


def _format_rows_for_prompt(columns, rows, limit: int = 100) -> str:
    names = [c.get("name") for c in columns if c.get("name")]
    lines = [" | ".join(names)]
    for row in rows[:limit]:
        lines.append(" | ".join(str(row.get(name, "")) for name in names))
    return "\n".join(lines)


@insights_whitelist()
def analyze(columns, rows, question: str | None = None):
    """Write a financial-analyst narrative over a result set. Uses Claude
    when 'anthropic_api_key' is set; otherwise Ollama — preferring the
    'ollama_analysis_model' site config (a general instruct model writes
    better prose than a coder model) and falling back to 'ollama_model'."""
    columns = frappe.parse_json(columns)
    rows = frappe.parse_json(rows)
    if not columns or not rows:
        frappe.throw("No data to analyze")

    context = (question or "").strip()
    user_content = (
        (f"Context: {context}\n\n" if context else "")
        + "Data:\n"
        + _format_rows_for_prompt(columns, rows)
    )

    if frappe.conf.get("anthropic_api_key"):
        analysis = ask_claude(user_content, ANALYSIS_PROMPT)
    else:
        model = frappe.conf.get("ollama_analysis_model") or None
        analysis = ask_ollama(user_content, ANALYSIS_PROMPT, model=model)

    return {"analysis": analysis.strip()}
