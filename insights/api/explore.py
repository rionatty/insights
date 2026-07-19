# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

from insights.decorators import insights_whitelist
from insights.insights.doctype.insights_data_source_v3.ibis_utils import (
    IbisQueryBuilder,
    execute_ibis_query,
    get_columns_from_schema,
)
from insights.insights.doctype.insights_data_source_v3.insights_data_source_v3 import (
    db_connections,
)


@insights_whitelist()
def run_exploration(operations, limit: int = 500):
    """Execute an ad-hoc operations pipeline without a saved query doc —
    powers the drag-and-drop Explore view. Table permissions are enforced
    by the source operation while building the query."""
    operations = frappe.parse_json(operations)
    if not isinstance(operations, list) or not operations:
        frappe.throw("No operations to run")

    limit = min(frappe.utils.cint(limit) or 500, 10_000)

    doc = frappe._dict(
        name=f"exploration-{frappe.session.user}",
        title="Exploration",
        use_live_connection=1,
        operations=frappe.as_json(operations),
    )

    with db_connections():
        query = IbisQueryBuilder(doc).build()
        results, time_taken = execute_ibis_query(
            query,
            page_size=limit,
            cache_expiry=300,
        )

    return {
        "columns": get_columns_from_schema(query.schema()),
        "rows": results.to_dict(orient="records"),
        "time_taken": time_taken,
    }


@insights_whitelist()
def save_exploration(title: str, operations):
    """Persist an exploration as a new workbook with a single builder query,
    so a good ad-hoc analysis graduates into a permanent, chartable one."""
    operations = frappe.parse_json(operations)
    if not isinstance(operations, list) or not operations:
        frappe.throw("Nothing to save")

    title = (title or "").strip() or "Exploration"

    workbook = frappe.new_doc("Insights Workbook")
    workbook.title = title
    workbook.insert()

    query = frappe.new_doc("Insights Query v3")
    query.title = title
    query.workbook = workbook.name
    query.is_builder_query = 1
    query.use_live_connection = 1
    query.operations = frappe.as_json(operations)
    query.insert()

    return {"workbook": workbook.name, "query": query.name}
