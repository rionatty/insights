# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import ibis

import insights

HANA_DEFAULT_PORT = 30015

# SAP HANA data types -> ibis dtypes
# DECIMAL is mapped to float64 since the warehouse stores parquet-backed
# DuckDB tables; exact decimal precision is not preserved.
HANA_TYPE_MAP = {
    "TINYINT": "int16",
    "SMALLINT": "int16",
    "INTEGER": "int32",
    "INT": "int32",
    "BIGINT": "int64",
    "DECIMAL": "float64",
    "SMALLDECIMAL": "float64",
    "REAL": "float32",
    "DOUBLE": "float64",
    "FLOAT": "float64",
    "BOOLEAN": "boolean",
    "DATE": "date",
    "TIME": "time",
    "TIMESTAMP": "timestamp",
    "SECONDDATE": "timestamp",
    "LONGDATE": "timestamp",
    "BINARY": "binary",
    "VARBINARY": "binary",
    "BLOB": "binary",
}


def get_hdbcli():
    try:
        from hdbcli import dbapi

        return dbapi
    except ImportError:
        frappe.throw(
            "The SAP HANA driver (hdbcli) is not installed. "
            "Run 'bench pip install hdbcli' and restart the bench."
        )


def get_hana_schema_name(data_source) -> str:
    # HANA object names are case-sensitive; the user's default schema
    # is their (uppercase) username unless a schema is configured
    return data_source.schema or (data_source.username or "").upper()


def get_hana_client(data_source):
    dbapi = get_hdbcli()
    password = data_source.get_password(raise_exception=False)
    conn_args = {
        "address": data_source.host,
        "port": int(data_source.port or HANA_DEFAULT_PORT),
        "user": data_source.username,
        "password": password,
        "encrypt": bool(data_source.use_ssl),
        "sslValidateCertificate": False,
        "connectTimeout": 10000,
    }
    if data_source.database_name:
        # route to a tenant database via the system db port
        conn_args["databaseName"] = data_source.database_name
    schema = get_hana_schema_name(data_source)
    if schema:
        conn_args["currentSchema"] = schema
    return dbapi.connect(**conn_args)


def get_hana_table_list(data_source) -> list[str]:
    from .mssql import get_listing_flags

    include_tables, include_views, _ = get_listing_flags(data_source)
    schema = get_hana_schema_name(data_source)
    conn = get_hana_client(data_source)
    try:
        cursor = conn.cursor()
        names = []
        if include_tables:
            cursor.execute(
                "SELECT TABLE_NAME FROM SYS.TABLES WHERE SCHEMA_NAME = ? ORDER BY TABLE_NAME",
                (schema,),
            )
            names.extend(row[0] for row in cursor.fetchall())
        if include_views:
            cursor.execute(
                "SELECT VIEW_NAME FROM SYS.VIEWS WHERE SCHEMA_NAME = ? ORDER BY VIEW_NAME",
                (schema,),
            )
            names.extend(row[0] for row in cursor.fetchall())
        return names
    finally:
        conn.close()


def get_hana_object_types(data_source, tables: list[str]) -> dict[str, str]:
    schema = get_hana_schema_name(data_source)
    conn = get_hana_client(data_source)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT VIEW_NAME FROM SYS.VIEWS WHERE SCHEMA_NAME = ?", (schema,))
        views = {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()

    return {table: ("View" if table in views else "Table") for table in tables}


def get_hana_ibis_schema(data_source, table_name: str) -> ibis.Schema:
    schema = get_hana_schema_name(data_source)
    conn = get_hana_client(data_source)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COLUMN_NAME, DATA_TYPE_NAME, POSITION FROM SYS.TABLE_COLUMNS "
            "WHERE SCHEMA_NAME = ? AND TABLE_NAME = ? ORDER BY POSITION",
            (schema, table_name),
        )
        columns = cursor.fetchall()
        if not columns:
            cursor.execute(
                "SELECT COLUMN_NAME, DATA_TYPE_NAME, POSITION FROM SYS.VIEW_COLUMNS "
                "WHERE SCHEMA_NAME = ? AND VIEW_NAME = ? ORDER BY POSITION",
                (schema, table_name),
            )
            columns = cursor.fetchall()
    finally:
        conn.close()

    if not columns:
        frappe.throw(f"Table {table_name} not found in schema {schema} of {data_source.title}")

    fields = {}
    for column_name, data_type, _position in columns:
        fields[column_name] = HANA_TYPE_MAP.get(data_type, "string")
    return ibis.schema(fields)


def get_hana_warehouse_connection(data_source):
    """SAP HANA sources are queried through the local DuckDB warehouse;
    tables are imported from HANA into the warehouse on first use."""
    from ..data_warehouse import get_warehouse_schema_name

    schema = get_warehouse_schema_name(data_source.name)
    db = insights.warehouse.get_connection()
    if schema not in db.list_databases():
        db.disconnect()
        insights.warehouse.create_database(schema)
        db = insights.warehouse.get_connection()
    db.raw_sql(f"USE '{schema}'")
    return db
