# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import ibis


def get_mssql_connection(data_source):
    if not frappe.conf.get("mssql_odbc_driver"):
        frappe.throw(
            "MSSQL ODBC driver path not configured. Please set it in common_site_config.json"
            " under 'mssql_odbc_driver' key."
            " Eg. 'mssql_odbc_driver': '/usr/local/lib/libtdsodbc.so' or 'FreeTDS'"
        )

    password = data_source.get_password(raise_exception=False)
    data_source.port = int(data_source.port or 1433)

    return ibis.mssql.connect(
        host=data_source.host,
        port=data_source.port,
        user=data_source.username,
        password=password,
        database=data_source.database_name,
        driver=frappe.conf.get("mssql_odbc_driver"),
    )


def get_mssql_table_list(data_source) -> list[str]:
    # ibis's list_tables() only returns base tables; include views too
    db = data_source._get_ibis_backend()
    cursor = db.raw_sql(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW') AND TABLE_SCHEMA = 'dbo' "
        "ORDER BY TABLE_NAME"
    )
    try:
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
