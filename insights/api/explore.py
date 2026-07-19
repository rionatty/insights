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
