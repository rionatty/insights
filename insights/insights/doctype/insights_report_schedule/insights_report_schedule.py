# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, formatdate, getdate, now_datetime
from frappe.utils.pdf import get_pdf

from insights.insights.doctype.insights_data_source_v3.ibis_utils import (
    IbisQueryBuilder,
    execute_ibis_query,
    get_columns_from_schema,
)
from insights.insights.doctype.insights_data_source_v3.insights_data_source_v3 import (
    db_connections,
)


class InsightsReportSchedule(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        dashboard: DF.Link
        day_of_month: DF.Int
        day_of_week: DF.Literal[
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
        ]
        enabled: DF.Check
        frequency: DF.Literal["Daily", "Weekly", "Monthly"]
        last_sent_on: DF.Datetime | None
        recipients: DF.SmallText
        title: DF.Data
    # end: auto-generated types

    @frappe.whitelist()
    def send_now(self):
        frappe.only_for("Insights Admin")
        send_report(self)
        self.db_set("last_sent_on", now_datetime())
        return True


def send_due_reports():
    """Daily scheduler entrypoint: send every enabled schedule that is due."""
    for name in frappe.get_all("Insights Report Schedule", {"enabled": 1}, pluck="name"):
        schedule = frappe.get_doc("Insights Report Schedule", name)
        try:
            if not is_due(schedule):
                continue
            send_report(schedule)
            schedule.db_set("last_sent_on", now_datetime())
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(title=f"Insights report schedule failed: {name}")


def is_due(schedule) -> bool:
    today = getdate()
    if schedule.last_sent_on and getdate(schedule.last_sent_on) >= today:
        return False
    if schedule.frequency == "Daily":
        return True
    if schedule.frequency == "Weekly":
        return today.strftime("%A") == (schedule.day_of_week or "Monday")
    if schedule.frequency == "Monthly":
        return today.day == cint(schedule.day_of_month or 1)
    return False


def send_report(schedule):
    dashboard = frappe.get_doc("Insights Dashboard v3", schedule.dashboard)
    sections = build_dashboard_sections(dashboard)
    html = render_report_html(dashboard.title, sections)
    pdf = get_pdf(html)

    recipients = [
        r.strip()
        for r in (schedule.recipients or "").replace(",", "\n").split("\n")
        if r.strip()
    ]
    if not recipients:
        frappe.throw("No recipients configured")

    frappe.sendmail(
        recipients=recipients,
        subject=f"{dashboard.title} — {formatdate(getdate())}",
        message=(
            f"<p>Please find attached the scheduled report "
            f"<b>{frappe.utils.escape_html(dashboard.title)}</b>.</p>"
        ),
        attachments=[
            {
                "fname": f"{frappe.scrub(dashboard.title)}-{getdate()}.pdf",
                "fcontent": pdf,
            }
        ],
    )


def build_dashboard_sections(dashboard) -> list[dict]:
    """One section per dashboard chart: the chart's data rebuilt server-side by
    appending its configured dimensions/measures to its query's pipeline.
    Dashboard-level filters are not applied — the report shows unfiltered data."""
    items = frappe.parse_json(dashboard.items or "[]")
    chart_names = [i.get("chart") for i in items if i.get("type") == "chart" and i.get("chart")]

    sections = []
    with db_connections():
        for chart_name in chart_names:
            if not frappe.db.exists("Insights Chart v3", chart_name):
                continue
            chart = frappe.get_doc("Insights Chart v3", chart_name)
            try:
                sections.append(build_chart_section(chart))
            except Exception:
                frappe.log_error(title=f"Report chart failed: {chart.title} ({chart.name})")
                sections.append({"title": chart.title, "error": True})
    return sections


def build_chart_section(chart) -> dict:
    config = frappe.parse_json(chart.config or "{}")
    dimensions, measures = extract_dimensions_measures(chart.chart_type, config)

    query = frappe.get_doc("Insights Query v3", chart.query)
    operations = frappe.parse_json(query.operations or "[]")

    if dimensions or measures:
        operations.append({"type": "summarize", "measures": measures, "dimensions": dimensions})
        if measures and dimensions:
            operations.append(
                {
                    "type": "order_by",
                    "column": {"type": "column", "column_name": measures[0].get("measure_name")},
                    "direction": "desc",
                }
            )

    doc = frappe._dict(
        name=f"report-{chart.name}",
        title=chart.title,
        use_live_connection=query.use_live_connection,
        operations=frappe.as_json(operations),
    )
    is_kpi = bool(measures and not dimensions)
    ibis_query = IbisQueryBuilder(doc).build()
    results, _ = execute_ibis_query(ibis_query, page_size=1 if is_kpi else 10, cache=False)

    return {
        "title": chart.title,
        "chart_type": chart.chart_type,
        "columns": get_columns_from_schema(ibis_query.schema()),
        "rows": results.to_dict(orient="records"),
        "is_kpi": is_kpi,
    }


def extract_dimensions_measures(chart_type: str, config: dict) -> tuple[list, list]:
    config = frappe._dict(config or {})
    dimensions, measures = [], []

    def add_dimension(d):
        if d and d.get("column_name"):
            dimensions.append(d)

    def add_measure(m):
        if m and m.get("column_name"):
            measures.append(m)

    if chart_type == "Number":
        for m in config.get("number_columns") or []:
            add_measure(m)
    elif chart_type in ("Bar", "Line", "Row", "Waterfall", "Pareto"):
        add_dimension((config.get("x_axis") or {}).get("dimension"))
        add_dimension((config.get("split_by") or {}).get("dimension"))
        for s in (config.get("y_axis") or {}).get("series") or []:
            add_measure(s.get("measure"))
    elif chart_type in ("Donut", "Funnel"):
        add_dimension(config.get("label_column"))
        add_measure(config.get("value_column"))
    elif chart_type == "Table":
        for d in (config.get("rows") or []) + (config.get("columns") or []):
            add_dimension(d)
        for v in config.get("values") or []:
            add_measure(v)

    # Map/Bubble/Sankey and anything unrecognised: raw query preview
    return dimensions, measures


def _format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return frappe.utils.escape_html(str(value))


def render_report_html(title: str, sections: list[dict]) -> str:
    parts = [
        """<style>
        body { font-family: Helvetica, Arial, sans-serif; color: #1f272e; margin: 24px; }
        h1 { font-size: 22px; margin-bottom: 2px; }
        .date { color: #74808b; font-size: 12px; margin-bottom: 24px; }
        .section { margin-bottom: 28px; page-break-inside: avoid; }
        h2 { font-size: 14px; margin-bottom: 8px; border-bottom: 1px solid #e2e6e9;
             padding-bottom: 4px; }
        table { border-collapse: collapse; width: 100%; font-size: 11px; }
        th { text-align: left; background: #f3f4f6; padding: 5px 8px;
             border: 1px solid #e2e6e9; }
        td { padding: 5px 8px; border: 1px solid #e2e6e9; }
        td.num { text-align: right; }
        .kpis { display: block; }
        .kpi { display: inline-block; margin-right: 32px; margin-bottom: 8px; }
        .kpi .label { font-size: 11px; color: #74808b; }
        .kpi .value { font-size: 20px; font-weight: bold; }
        .error { color: #b52a2a; font-size: 11px; }
        .footer { color: #74808b; font-size: 10px; margin-top: 32px;
                  border-top: 1px solid #e2e6e9; padding-top: 8px; }
        </style>"""
    ]
    parts.append(f"<h1>{frappe.utils.escape_html(title)}</h1>")
    parts.append(f"<div class='date'>{formatdate(getdate())}</div>")

    for section in sections:
        parts.append("<div class='section'>")
        parts.append(f"<h2>{frappe.utils.escape_html(section['title'])}</h2>")
        if section.get("error"):
            parts.append("<div class='error'>This chart could not be rendered.</div>")
            parts.append("</div>")
            continue

        columns = section["columns"]
        rows = section["rows"]
        if section.get("is_kpi") and rows:
            parts.append("<div class='kpis'>")
            for col in columns:
                value = _format_value(rows[0].get(col["name"]))
                parts.append(
                    f"<div class='kpi'><div class='label'>{frappe.utils.escape_html(col['name'])}</div>"
                    f"<div class='value'>{value}</div></div>"
                )
            parts.append("</div>")
        else:
            numeric = {c["name"] for c in columns if c["type"] in ("Integer", "Decimal")}
            parts.append("<table><thead><tr>")
            for col in columns:
                parts.append(f"<th>{frappe.utils.escape_html(col['name'])}</th>")
            parts.append("</tr></thead><tbody>")
            for row in rows:
                parts.append("<tr>")
                for col in columns:
                    css = " class='num'" if col["name"] in numeric else ""
                    parts.append(f"<td{css}>{_format_value(row.get(col['name']))}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")
        parts.append("</div>")

    parts.append(
        "<div class='footer'>Generated by Insights — top 10 rows per chart, "
        "dashboard filters not applied.</div>"
    )
    return "".join(parts)
