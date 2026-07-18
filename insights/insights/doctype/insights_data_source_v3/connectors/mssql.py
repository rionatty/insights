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


# stored procedures are listed with this prefix so the rest of the app
# can tell them apart from tables/views; they cannot be queried live and
# are imported into the warehouse by executing them
PROCEDURE_PREFIX = "sp:"

MSSQL_TYPE_MAP = {
    "tinyint": "int16",
    "smallint": "int16",
    "int": "int32",
    "bigint": "int64",
    "bit": "boolean",
    "decimal": "float64",
    "numeric": "float64",
    "money": "float64",
    "smallmoney": "float64",
    "float": "float64",
    "real": "float32",
    "date": "date",
    "time": "time",
    "datetime": "timestamp",
    "datetime2": "timestamp",
    "smalldatetime": "timestamp",
    "datetimeoffset": "timestamp",
    "binary": "binary",
    "varbinary": "binary",
    "image": "binary",
}


def get_listing_flags(data_source) -> tuple[bool, bool, bool]:
    """Return (tables, views, stored_procedures) listing flags.

    Sources created before these fields existed have none of them set;
    default those to tables + views for backwards compatibility.
    """
    tables = bool(data_source.get("include_tables"))
    views = bool(data_source.get("include_views"))
    procedures = bool(data_source.get("include_stored_procedures"))
    if not (tables or views or procedures):
        return True, True, False
    return tables, views, procedures


def get_mssql_table_list(data_source) -> list[str]:
    include_tables, include_views, include_procedures = get_listing_flags(data_source)

    # ibis's list_tables() only returns base tables; query the catalog
    # directly so views and stored procedures can be included
    table_types = []
    if include_tables:
        table_types.append("'BASE TABLE'")
    if include_views:
        table_types.append("'VIEW'")

    db = data_source._get_ibis_backend()
    names = []

    if table_types:
        cursor = db.raw_sql(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_TYPE IN ({', '.join(table_types)}) AND TABLE_SCHEMA = 'dbo' "
            "ORDER BY TABLE_NAME"
        )
        try:
            names.extend(row[0] for row in cursor.fetchall())
        finally:
            cursor.close()

    if include_procedures:
        cursor = db.raw_sql(
            "SELECT ROUTINE_NAME FROM INFORMATION_SCHEMA.ROUTINES "
            "WHERE ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_SCHEMA = 'dbo' "
            "ORDER BY ROUTINE_NAME"
        )
        try:
            names.extend(f"{PROCEDURE_PREFIX}{row[0]}" for row in cursor.fetchall())
        finally:
            cursor.close()

    return names


def is_stored_procedure(table_name: str) -> bool:
    return table_name.startswith(PROCEDURE_PREFIX)


def get_procedure_exec_sql(table_name: str) -> str:
    procedure = table_name.removeprefix(PROCEDURE_PREFIX).replace("]", "]]")
    return f"EXEC dbo.[{procedure}]"


def get_mssql_procedure_schema(data_source, table_name: str) -> "ibis.Schema":
    exec_sql = get_procedure_exec_sql(table_name).replace("'", "''")
    db = data_source._get_ibis_backend()
    cursor = db.raw_sql(f"EXEC sp_describe_first_result_set @tsql = N'{exec_sql}'")
    try:
        columns = [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]
    finally:
        cursor.close()

    if not columns:
        frappe.throw(
            f"Could not determine the result columns of {table_name}. "
            "Only stored procedures without required parameters that return "
            "a result set are supported."
        )

    fields = {}
    for column in columns:
        if column.get("is_hidden"):
            continue
        base_type = (column.get("system_type_name") or "").split("(")[0].lower()
        fields[column["name"]] = MSSQL_TYPE_MAP.get(base_type, "string")
    return ibis.schema(fields)
