"""Generate SAP Business One workbook templates for the Insights library."""

import json
import os

OUT = r"D:/Dev/ERPNext/Insights/insights/workbook_templates"
DS = "SAP B1"  # placeholder data source, bound at import time


def dim(col, dtype="String", granularity=None, name=None):
    d = {"dimension_name": name or col, "column_name": col, "data_type": dtype}
    if granularity:
        d["granularity"] = granularity
    return d


def measure(name, col, agg="sum", dtype="Decimal"):
    return {"measure_name": name, "column_name": col, "data_type": dtype, "aggregation": agg}


def flt(col, op, val):
    return {"column": {"type": "column", "column_name": col}, "operator": op, "value": val}


def query(qid, title, table, filters=None, sort_order=0):
    ops = [{"type": "source", "table": {"type": "table", "data_source": DS, "table_name": table}}]
    if filters:
        ops.append({"type": "filter_group", "logical_operator": "And", "filters": filters})
    return {
        "name": qid,
        "title": title,
        "workbook": None,  # set later
        "folder": None,
        "sort_order": sort_order,
        "use_live_connection": 1,
        "is_script_query": 0,
        "is_builder_query": 1,
        "is_native_query": 0,
        "operations": ops,
    }


def base_config(order_by=None, limit=100):
    return {
        "order_by": order_by or [],
        "limit": limit,
        "filters": {"logical_operator": "And", "filters": []},
    }


def order(col, direction="asc"):
    return {"column": {"type": "column", "column_name": col}, "direction": direction}


def chart(cid, title, qid, chart_type, config, sort_order=0):
    return {
        "name": cid,
        "title": title,
        "workbook": None,
        "folder": None,
        "sort_order": sort_order,
        "query": qid,
        "chart_type": chart_type,
        "config": config,
    }


def number_chart(cid, title, qid, columns, options, date_col=None, sort_order=0):
    cfg = {
        "number_columns": columns,
        "number_column_options": options,
        "comparison": bool(date_col),
        "sparkline": bool(date_col),
        **base_config(),
    }
    if date_col:
        cfg["date_column"] = dim(date_col, "Date", "month")
        cfg["order_by"] = [order(date_col)]
    return chart(cid, title, qid, "Number", cfg, sort_order)


def line_chart(cid, title, qid, date_col, series, sort_order=0, split_by=None):
    cfg = {
        "x_axis": {"dimension": dim(date_col, "Date", "month")},
        "y_axis": {"series": [{"measure": m} for m in series], "show_data_labels": False},
        **base_config(order_by=[order(date_col)]),
    }
    if split_by:
        cfg["split_by"] = {"dimension": dim(split_by)}
    return chart(cid, title, qid, "Line", cfg, sort_order)


def waterfall_chart(cid, title, qid, label_col, m, sort_order=0):
    cfg = {
        "x_axis": {"dimension": dim(label_col)},
        "y_axis": {"series": [{"measure": m}]},
        **base_config(order_by=[order(label_col)]),
    }
    return chart(cid, title, qid, "Waterfall", cfg, sort_order)


def row_chart(cid, title, qid, label_col, m, limit=10, sort_order=0):
    cfg = {
        "x_axis": {"dimension": dim(label_col)},
        "y_axis": {"series": [{"measure": m}]},
        **base_config(order_by=[order(m["measure_name"], "desc")], limit=limit),
    }
    return chart(cid, title, qid, "Row", cfg, sort_order)


def bar_chart(cid, title, qid, label_col, m, limit=100, sort_order=0):
    cfg = {
        "x_axis": {"dimension": dim(label_col)},
        "y_axis": {"series": [{"measure": m}]},
        **base_config(order_by=[order(m["measure_name"], "desc")], limit=limit),
    }
    return chart(cid, title, qid, "Bar", cfg, sort_order)


def donut_chart(cid, title, qid, label_col, m, sort_order=0):
    cfg = {
        "label_column": dim(label_col),
        "value_column": m,
        "legend_position": "bottom",
        **base_config(),
    }
    return chart(cid, title, qid, "Donut", cfg, sort_order)


def table_chart(cid, title, qid, rows, values, order_by, limit=20, sort_order=0):
    cfg = {
        "rows": rows,
        "columns": [],
        "values": values,
        **base_config(order_by=order_by, limit=limit),
    }
    return chart(cid, title, qid, "Table", cfg, sort_order)


def date_filter(links, x=0, y=0, w=4):
    return {
        "type": "filter",
        "filter_name": "Date Range",
        "filter_type": "Date",
        "icon": "calendar",
        "default_operator": "within",
        "default_value": "Last 12 months",
        "links": links,
        "layout": {"i": "filter-date", "x": x, "y": y, "w": w, "h": 1},
    }


def text_filter(name, icon, links, x=0, y=0, w=4):
    return {
        "type": "filter",
        "filter_name": name,
        "filter_type": "String",
        "icon": icon,
        "links": links,
        "layout": {"i": f"filter-{name.lower().replace(' ', '-')}", "x": x, "y": y, "w": w, "h": 1},
    }


def chart_item(cid, x, y, w, h):
    return {"type": "chart", "chart": cid, "layout": {"i": f"item-{cid}", "x": x, "y": y, "w": w, "h": h}}


MONEY = {"decimal": 0, "shorten_numbers": True}
PLAIN = {"shorten_numbers": False}


def write_template(folder, manifest, wb_name, wb_title, queries, charts, dashboard_items):
    for q in queries:
        q["workbook"] = wb_name
    for c in charts:
        c["workbook"] = wb_name
    workbook = {
        "version": 1.0,
        "type": "Workbook",
        "name": wb_name,
        "doc": {"name": wb_name, "title": wb_title},
        "dependencies": {
            "folders": [],
            "queries": {q["name"]: q for q in queries},
            "charts": {c["name"]: c for c in charts},
            "dashboards": {
                f"td-{folder}": {
                    "name": f"td-{folder}",
                    "title": wb_title,
                    "workbook": wb_name,
                    "items": dashboard_items,
                }
            },
        },
    }
    path = os.path.join(OUT, folder)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    with open(os.path.join(path, "workbook.json"), "w") as f:
        json.dump(workbook, f, indent=1)
        f.write("\n")
    print("wrote", folder)


def sap_manifest(title, description, notes, module):
    return {
        "version": 1,
        "title": title,
        "description": description,
        "notes": notes,
        "module": module,
        "required_apps": [],
        "source_doctypes": [],
        "system": "SAP Business One",
        "data_source_placeholder": DS,
    }


NOT_CANCELED = [flt("CANCELED", "=", "N")]
OPEN_DOC = [flt("CANCELED", "=", "N"), flt("DocStatus", "=", "O")]

# ---------------------------------------------------------------- sales
write_template(
    "sap-sales",
    sap_manifest(
        "Sales Performance",
        "Revenue, customers and margins at a glance — revenue trend with "
        "month-on-month KPIs, gross profit, top customers and items, and "
        "revenue split by warehouse.",
        "Built from posted AR Invoices (OINV/INV1), cancelled documents "
        "excluded. Gross profit uses SAP B1's per-line gross profit. "
        "Credit notes are not netted off.",
        "Selling",
    ),
    "template-sap-sales",
    "Sales Performance (SAP B1)",
    queries=[
        query("tq-sb1-inv", "AR Invoices", "OINV", NOT_CANCELED, 0),
        query("tq-sb1-inv-lines", "AR Invoice Lines", "INV1", None, 1),
    ],
    charts=[
        number_chart(
            "tc-sb1-sales-kpis", "Sales KPIs", "tq-sb1-inv",
            [
                measure("Revenue", "DocTotal"),
                measure("Invoices", "DocEntry", "count", "Integer"),
                measure("Avg Invoice", "DocTotal", "avg"),
                measure("Customers", "CardCode", "count_distinct", "Integer"),
            ],
            [MONEY, PLAIN, MONEY, PLAIN],
            date_col="DocDate", sort_order=0,
        ),
        line_chart("tc-sb1-revenue-trend", "Revenue Trend", "tq-sb1-inv",
                   "DocDate", [measure("Revenue", "DocTotal")], 1),
        donut_chart("tc-sb1-rev-by-whs", "Revenue by Warehouse", "tq-sb1-inv-lines",
                    "WhsCode", measure("Revenue", "LineTotal"), 2),
        row_chart("tc-sb1-top-customers", "Top 10 Customers", "tq-sb1-inv",
                  "CardName", measure("Revenue", "DocTotal"), 10, 3),
        row_chart("tc-sb1-top-items", "Top 10 Items", "tq-sb1-inv-lines",
                  "Dscription", measure("Revenue", "LineTotal"), 10, 4),
        line_chart("tc-sb1-gp-trend", "Gross Profit Trend", "tq-sb1-inv-lines",
                   "DocDate", [measure("Gross Profit", "GrssProfit")], 5),
    ],
    dashboard_items=[
        date_filter({
            "tc-sb1-sales-kpis": "`tq-sb1-inv`.`DocDate`",
            "tc-sb1-revenue-trend": "`tq-sb1-inv`.`DocDate`",
            "tc-sb1-top-customers": "`tq-sb1-inv`.`DocDate`",
            "tc-sb1-rev-by-whs": "`tq-sb1-inv-lines`.`DocDate`",
            "tc-sb1-top-items": "`tq-sb1-inv-lines`.`DocDate`",
            "tc-sb1-gp-trend": "`tq-sb1-inv-lines`.`DocDate`",
        }),
        chart_item("tc-sb1-sales-kpis", 0, 1, 20, 3),
        chart_item("tc-sb1-revenue-trend", 0, 4, 12, 8),
        chart_item("tc-sb1-rev-by-whs", 12, 4, 8, 8),
        chart_item("tc-sb1-top-customers", 0, 12, 10, 8),
        chart_item("tc-sb1-top-items", 10, 12, 10, 8),
        chart_item("tc-sb1-gp-trend", 0, 20, 20, 8),
    ],
)

# ---------------------------------------------------------------- purchasing
write_template(
    "sap-purchasing",
    sap_manifest(
        "Purchasing Overview",
        "Supplier spend and order pipeline — spend trend with month-on-month "
        "KPIs, top suppliers and items, and the open purchase order backlog.",
        "Built from posted AP Invoices (OPCH/PCH1) and open Purchase Orders "
        "(OPOR), cancelled documents excluded.",
        "Buying",
    ),
    "template-sap-purchasing",
    "Purchasing Overview (SAP B1)",
    queries=[
        query("tq-sb1-bills", "AP Invoices", "OPCH", NOT_CANCELED, 0),
        query("tq-sb1-bill-lines", "AP Invoice Lines", "PCH1", None, 1),
        query("tq-sb1-open-pos", "Open Purchase Orders", "OPOR", OPEN_DOC, 2),
    ],
    charts=[
        number_chart(
            "tc-sb1-purchase-kpis", "Purchasing KPIs", "tq-sb1-bills",
            [
                measure("Spend", "DocTotal"),
                measure("Bills", "DocEntry", "count", "Integer"),
                measure("Avg Bill", "DocTotal", "avg"),
                measure("Suppliers", "CardCode", "count_distinct", "Integer"),
            ],
            [MONEY, PLAIN, MONEY, PLAIN],
            date_col="DocDate", sort_order=0,
        ),
        number_chart(
            "tc-sb1-open-po-kpis", "Open Purchase Orders", "tq-sb1-open-pos",
            [
                measure("Open PO Value", "DocTotal"),
                measure("Open POs", "DocEntry", "count", "Integer"),
            ],
            [MONEY, PLAIN],
            sort_order=1,
        ),
        line_chart("tc-sb1-spend-trend", "Spend Trend", "tq-sb1-bills",
                   "DocDate", [measure("Spend", "DocTotal")], 2),
        row_chart("tc-sb1-top-suppliers", "Top 10 Suppliers", "tq-sb1-bills",
                  "CardName", measure("Spend", "DocTotal"), 10, 3),
        row_chart("tc-sb1-spend-by-item", "Top Purchased Items", "tq-sb1-bill-lines",
                  "Dscription", measure("Spend", "LineTotal"), 10, 4),
        table_chart(
            "tc-sb1-open-po-list", "Open PO Backlog", "tq-sb1-open-pos",
            rows=[dim("CardName", name="Supplier"), dim("DocDate", "Date", name="Order Date")],
            values=[measure("Value", "DocTotal"), measure("Orders", "DocEntry", "count", "Integer")],
            order_by=[order("Value", "desc")], limit=20, sort_order=5,
        ),
    ],
    dashboard_items=[
        date_filter({
            "tc-sb1-purchase-kpis": "`tq-sb1-bills`.`DocDate`",
            "tc-sb1-spend-trend": "`tq-sb1-bills`.`DocDate`",
            "tc-sb1-top-suppliers": "`tq-sb1-bills`.`DocDate`",
            "tc-sb1-spend-by-item": "`tq-sb1-bill-lines`.`DocDate`",
        }),
        chart_item("tc-sb1-purchase-kpis", 0, 1, 20, 3),
        chart_item("tc-sb1-spend-trend", 0, 4, 12, 8),
        chart_item("tc-sb1-open-po-kpis", 12, 4, 8, 8),
        chart_item("tc-sb1-top-suppliers", 0, 12, 10, 8),
        chart_item("tc-sb1-spend-by-item", 10, 12, 10, 8),
        chart_item("tc-sb1-open-po-list", 0, 20, 20, 8),
    ],
)

# ---------------------------------------------------------------- inventory
write_template(
    "sap-inventory",
    sap_manifest(
        "Inventory Health",
        "Stock levels, movement and gaps — on-hand by warehouse, in vs out "
        "movement trend, items out of stock and the biggest holdings.",
        "Built from Item Master (OITM), Warehouse Stock (OITW) and the "
        "Inventory Journal (OINM). Quantities are in each item's stock UoM; "
        "mixed-UoM totals are indicative.",
        "Stock",
    ),
    "template-sap-inventory",
    "Inventory Health (SAP B1)",
    queries=[
        query("tq-sb1-items", "Items", "OITM", None, 0),
        query("tq-sb1-whs-stock", "Warehouse Stock", "OITW", None, 1),
        query("tq-sb1-moves", "Stock Movements", "OINM", None, 2),
        query("tq-sb1-oos", "Out of Stock Items", "OITM", [flt("OnHand", "<=", 0)], 3),
    ],
    charts=[
        number_chart(
            "tc-sb1-stock-kpis", "Stock KPIs", "tq-sb1-items",
            [
                measure("Items", "ItemCode", "count", "Integer"),
                measure("Total On-hand Qty", "OnHand"),
            ],
            [PLAIN, PLAIN],
            sort_order=0,
        ),
        number_chart(
            "tc-sb1-oos-kpi", "Out of Stock", "tq-sb1-oos",
            [measure("Items at Zero or Below", "ItemCode", "count", "Integer")],
            [PLAIN],
            sort_order=1,
        ),
        bar_chart("tc-sb1-stock-by-whs", "On-hand by Warehouse", "tq-sb1-whs-stock",
                  "WhsCode", measure("On-hand Qty", "OnHand"), 100, 2),
        line_chart("tc-sb1-move-trend", "Movement Trend (In vs Out)", "tq-sb1-moves",
                   "DocDate",
                   [measure("Qty In", "InQty"), measure("Qty Out", "OutQty")], 3),
        line_chart("tc-sb1-value-moved", "Net Stock Value Change", "tq-sb1-moves",
                   "DocDate", [measure("Value Change", "TransValue")], 4),
        row_chart("tc-sb1-top-holdings", "Largest Holdings (Qty)", "tq-sb1-items",
                  "ItemName", measure("On-hand Qty", "OnHand"), 15, 5),
    ],
    dashboard_items=[
        date_filter({
            "tc-sb1-move-trend": "`tq-sb1-moves`.`DocDate`",
            "tc-sb1-value-moved": "`tq-sb1-moves`.`DocDate`",
        }),
        chart_item("tc-sb1-stock-kpis", 0, 1, 12, 3),
        chart_item("tc-sb1-oos-kpi", 12, 1, 8, 3),
        chart_item("tc-sb1-move-trend", 0, 4, 12, 8),
        chart_item("tc-sb1-stock-by-whs", 12, 4, 8, 8),
        chart_item("tc-sb1-top-holdings", 0, 12, 10, 8),
        chart_item("tc-sb1-value-moved", 10, 12, 10, 8),
    ],
)

# ---------------------------------------------------------------- receivables & payables
write_template(
    "sap-receivables-payables",
    sap_manifest(
        "Receivables & Payables",
        "Who owes you and whom you owe — open AR and AP with due-date "
        "worklists and the largest customer and supplier balances.",
        "Open documents come from unpaid AR Invoices (OINV) and AP Invoices "
        "(OPCH); balances come from the Business Partner master (OCRD). "
        "Amounts are document totals; partial payments are not deducted.",
        "Accounts",
    ),
    "template-sap-receivables-payables",
    "Receivables & Payables (SAP B1)",
    queries=[
        query("tq-sb1-open-ar", "Open AR Invoices", "OINV", OPEN_DOC, 0),
        query("tq-sb1-open-ap", "Open AP Invoices", "OPCH", OPEN_DOC, 1),
        query("tq-sb1-customers", "Customers", "OCRD", [flt("CardType", "=", "C")], 2),
        query("tq-sb1-suppliers", "Suppliers", "OCRD", [flt("CardType", "=", "S")], 3),
    ],
    charts=[
        number_chart(
            "tc-sb1-ar-kpis", "Receivables", "tq-sb1-open-ar",
            [
                measure("Open AR Value", "DocTotal"),
                measure("Open Invoices", "DocEntry", "count", "Integer"),
            ],
            [MONEY, PLAIN],
            sort_order=0,
        ),
        number_chart(
            "tc-sb1-ap-kpis", "Payables", "tq-sb1-open-ap",
            [
                measure("Open AP Value", "DocTotal"),
                measure("Open Bills", "DocEntry", "count", "Integer"),
            ],
            [MONEY, PLAIN],
            sort_order=1,
        ),
        row_chart("tc-sb1-cust-balances", "Top Customer Balances", "tq-sb1-customers",
                  "CardName", measure("Balance", "Balance"), 15, 2),
        row_chart("tc-sb1-supp-balances", "Top Supplier Balances", "tq-sb1-suppliers",
                  "CardName", measure("Balance", "Balance"), 15, 3),
        table_chart(
            "tc-sb1-ar-due", "AR by Due Date", "tq-sb1-open-ar",
            rows=[dim("CardName", name="Customer"), dim("DocDueDate", "Date", name="Due Date")],
            values=[measure("Amount", "DocTotal")],
            order_by=[order("Due Date")], limit=25, sort_order=4,
        ),
        table_chart(
            "tc-sb1-ap-due", "AP by Due Date", "tq-sb1-open-ap",
            rows=[dim("CardName", name="Supplier"), dim("DocDueDate", "Date", name="Due Date")],
            values=[measure("Amount", "DocTotal")],
            order_by=[order("Due Date")], limit=25, sort_order=5,
        ),
    ],
    dashboard_items=[
        text_filter("Customer", "user", {
            "tc-sb1-ar-kpis": "`tq-sb1-open-ar`.`CardName`",
            "tc-sb1-ar-due": "`tq-sb1-open-ar`.`CardName`",
            "tc-sb1-cust-balances": "`tq-sb1-customers`.`CardName`",
        }),
        text_filter("Supplier", "truck", {
            "tc-sb1-ap-kpis": "`tq-sb1-open-ap`.`CardName`",
            "tc-sb1-ap-due": "`tq-sb1-open-ap`.`CardName`",
            "tc-sb1-supp-balances": "`tq-sb1-suppliers`.`CardName`",
        }, x=4),
        chart_item("tc-sb1-ar-kpis", 0, 1, 10, 3),
        chart_item("tc-sb1-ap-kpis", 10, 1, 10, 3),
        chart_item("tc-sb1-cust-balances", 0, 4, 10, 8),
        chart_item("tc-sb1-supp-balances", 10, 4, 10, 8),
        chart_item("tc-sb1-ar-due", 0, 12, 10, 8),
        chart_item("tc-sb1-ap-due", 10, 12, 10, 8),
    ],
)

# ---------------------------------------------------------------- tax & vat
write_template(
    "sap-tax",
    sap_manifest(
        "Tax & VAT Compliance",
        "Output vs input VAT month by month — taxable sales and purchases, "
        "credit note adjustments and the customers generating the most VAT. "
        "Built for URA/EFRIS reconciliation.",
        "Built from document VAT totals on AR Invoices (OINV), AP Invoices "
        "(OPCH) and AR Credit Notes (ORIN), cancelled documents excluded. "
        "Reconcile against your tax authority filings before submission.",
        "Accounts",
    ),
    "template-sap-tax",
    "Tax & VAT Compliance (SAP B1)",
    queries=[
        query("tq-sb1-out-vat", "AR Invoices (VAT)", "OINV", NOT_CANCELED, 0),
        query("tq-sb1-in-vat", "AP Invoices (VAT)", "OPCH", NOT_CANCELED, 1),
        query("tq-sb1-cn-vat", "AR Credit Notes (VAT)", "ORIN", NOT_CANCELED, 2),
    ],
    charts=[
        number_chart(
            "tc-sb1-outvat-kpis", "Output VAT", "tq-sb1-out-vat",
            [
                measure("Output VAT", "VatSum"),
                measure("Taxable Sales", "DocTotal"),
            ],
            [MONEY, MONEY],
            date_col="DocDate", sort_order=0,
        ),
        number_chart(
            "tc-sb1-invat-kpis", "Input VAT", "tq-sb1-in-vat",
            [
                measure("Input VAT", "VatSum"),
                measure("Purchases", "DocTotal"),
            ],
            [MONEY, MONEY],
            date_col="DocDate", sort_order=1,
        ),
        number_chart(
            "tc-sb1-cnvat-kpis", "Credit Note Adjustments", "tq-sb1-cn-vat",
            [
                measure("VAT on Credit Notes", "VatSum"),
                measure("Credit Notes", "DocEntry", "count", "Integer"),
            ],
            [MONEY, PLAIN],
            sort_order=2,
        ),
        line_chart("tc-sb1-outvat-trend", "Output VAT by Month", "tq-sb1-out-vat",
                   "DocDate", [measure("Output VAT", "VatSum")], 3),
        line_chart("tc-sb1-invat-trend", "Input VAT by Month", "tq-sb1-in-vat",
                   "DocDate", [measure("Input VAT", "VatSum")], 4),
        row_chart("tc-sb1-vat-by-customer", "Top Customers by Output VAT", "tq-sb1-out-vat",
                  "CardName", measure("Output VAT", "VatSum"), 10, 5),
    ],
    dashboard_items=[
        date_filter({
            "tc-sb1-outvat-kpis": "`tq-sb1-out-vat`.`DocDate`",
            "tc-sb1-invat-kpis": "`tq-sb1-in-vat`.`DocDate`",
            "tc-sb1-outvat-trend": "`tq-sb1-out-vat`.`DocDate`",
            "tc-sb1-invat-trend": "`tq-sb1-in-vat`.`DocDate`",
            "tc-sb1-vat-by-customer": "`tq-sb1-out-vat`.`DocDate`",
            "tc-sb1-cnvat-kpis": "`tq-sb1-cn-vat`.`DocDate`",
        }),
        chart_item("tc-sb1-outvat-kpis", 0, 1, 10, 3),
        chart_item("tc-sb1-invat-kpis", 10, 1, 10, 3),
        chart_item("tc-sb1-outvat-trend", 0, 4, 10, 8),
        chart_item("tc-sb1-invat-trend", 10, 4, 10, 8),
        chart_item("tc-sb1-cnvat-kpis", 0, 12, 8, 3),
        chart_item("tc-sb1-vat-by-customer", 8, 12, 12, 8),
    ],
)

# ---------------------------------------------------------------- finance
write_template(
    "sap-finance",
    sap_manifest(
        "Financial Statements",
        "The general ledger turned into statements — P&L waterfall and trend "
        "by account class, monthly cash in vs out, top expense accounts and "
        "balance sheet positions.",
        "Requires the CVT_FIN_* views (run scripts/sap_b1_finance_views.sql "
        "from the Insights repo against the company database first). Built "
        "from Journal Entries (JDT1/OACT) and Payments (ORCT/OVPM). Amounts "
        "follow the sign convention: revenue positive, costs negative.",
        "Accounts",
    ),
    "template-sap-finance",
    "Financial Statements (SAP B1)",
    queries=[
        query("tq-fin-pnl", "P&L Monthly", "CVT_FIN_PNL_MONTHLY", None, 0),
        query("tq-fin-cash", "Cash Monthly", "CVT_FIN_CASH_MONTHLY", None, 1),
        query("tq-fin-balances", "Account Balances", "CVT_FIN_BALANCES", None, 2),
        query("tq-fin-expenses", "Expense Accounts", "CVT_FIN_PNL_MONTHLY",
              [flt("ClassCode", "=", 6)], 3),
    ],
    charts=[
        number_chart(
            "tc-fin-kpis", "Result", "tq-fin-pnl",
            [measure("Net Result", "Amount")],
            [MONEY],
            date_col="MonthStart", sort_order=0,
        ),
        number_chart(
            "tc-fin-cash-kpis", "Cash", "tq-fin-cash",
            [
                measure("Cash In", "CashIn"),
                measure("Cash Out", "CashOut"),
                measure("Net Cash", "NetCash"),
            ],
            [MONEY, MONEY, MONEY],
            date_col="MonthStart", sort_order=1,
        ),
        waterfall_chart("tc-fin-pnl-waterfall", "P&L by Account Class", "tq-fin-pnl",
                        "AccountClass", measure("Amount", "Amount"), 2),
        line_chart("tc-fin-pnl-trend", "P&L Trend by Class", "tq-fin-pnl",
                   "MonthStart", [measure("Amount", "Amount")], 3,
                   split_by="AccountClass"),
        line_chart("tc-fin-cash-trend", "Cash In vs Out", "tq-fin-cash",
                   "MonthStart",
                   [measure("Cash In", "CashIn"), measure("Cash Out", "CashOut")], 4),
        row_chart("tc-fin-top-expenses", "Top Expense Accounts", "tq-fin-expenses",
                  "AcctName", measure("Spend", "NetDebit"), 15, 5),
        bar_chart("tc-fin-balances", "Balance Sheet Positions", "tq-fin-balances",
                  "AccountClass", measure("Balance", "Balance"), 100, 6),
    ],
    dashboard_items=[
        date_filter({
            "tc-fin-kpis": "`tq-fin-pnl`.`MonthStart`",
            "tc-fin-cash-kpis": "`tq-fin-cash`.`MonthStart`",
            "tc-fin-pnl-waterfall": "`tq-fin-pnl`.`MonthStart`",
            "tc-fin-pnl-trend": "`tq-fin-pnl`.`MonthStart`",
            "tc-fin-cash-trend": "`tq-fin-cash`.`MonthStart`",
            "tc-fin-top-expenses": "`tq-fin-expenses`.`MonthStart`",
        }),
        chart_item("tc-fin-kpis", 0, 1, 8, 3),
        chart_item("tc-fin-cash-kpis", 8, 1, 12, 3),
        chart_item("tc-fin-pnl-waterfall", 0, 4, 10, 8),
        chart_item("tc-fin-pnl-trend", 10, 4, 10, 8),
        chart_item("tc-fin-cash-trend", 0, 12, 10, 8),
        chart_item("tc-fin-top-expenses", 10, 12, 10, 8),
        chart_item("tc-fin-balances", 0, 20, 20, 8),
    ],
)

print("done")
