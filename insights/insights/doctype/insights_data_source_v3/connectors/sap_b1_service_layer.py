# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re
import warnings
import xml.etree.ElementTree as ET

import frappe
import ibis
import pandas as pd

B1SL_DEFAULT_PORT = 50000
B1SL_SAMPLE_SIZE = 20

ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$")


class B1ServiceLayerClient:
    """Client for the SAP Business One Service Layer (OData) API."""

    def __init__(self, data_source):
        import requests

        host = (data_source.host or "").rstrip("/")
        if not host.startswith("http"):
            host = f"https://{host}"
        port = int(data_source.port or B1SL_DEFAULT_PORT)
        self.base_url = f"{host}:{port}/b1s/v1"
        self.company_db = data_source.database_name
        self.username = data_source.username
        self.password = data_source.get_password(raise_exception=False)
        # use_ssl doubles as "verify SSL certificate"; Service Layer
        # installs commonly use self-signed certificates
        self.verify_ssl = bool(data_source.use_ssl)

        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        self._logged_in = False

    def login(self):
        response = self._request(
            "POST",
            f"{self.base_url}/Login",
            json={
                "CompanyDB": self.company_db,
                "UserName": self.username,
                "Password": self.password,
            },
        )
        if response.status_code != 200:
            frappe.throw(f"Service Layer login failed ({response.status_code}): {response.text[:500]}")
        self._logged_in = True

    def _request(self, method, url, **kwargs):
        if not self.verify_ssl:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return self.session.request(method, url, timeout=120, **kwargs)
        return self.session.request(method, url, timeout=120, **kwargs)

    def get(self, path, params=None, headers=None):
        if not self._logged_in:
            self.login()
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        response = self._request("GET", url, params=params, headers=headers)
        if response.status_code == 401:
            # session expired; login and retry once
            self.login()
            response = self._request("GET", url, params=params, headers=headers)
        response.raise_for_status()
        return response

    def test_connection(self):
        self.login()
        return True

    def list_entities(self) -> list[str]:
        response = self.get("$metadata")
        root = ET.fromstring(response.text)
        entities = [
            element.get("Name")
            for element in root.iter()
            if element.tag.endswith("EntitySet") and element.get("Name")
        ]
        return sorted(set(entities))

    def fetch_pages(self, entity, page_size=500, row_limit=None, filters=None, order_by=None):
        """Yield pages of scalar-only row dicts, following OData nextLinks."""
        params = {}
        if filters:
            params["$filter"] = filters
        if order_by:
            params["$orderby"] = order_by

        headers = {"Prefer": f"odata.maxpagesize={page_size}"}
        url = entity
        fetched = 0

        while url:
            response = self.get(url, params=params, headers=headers)
            params = None  # nextLink already carries the query string
            payload = response.json()
            rows = payload.get("value", [])
            if not rows:
                break

            rows = [scalars_only(row) for row in rows]
            if row_limit and fetched + len(rows) > row_limit:
                rows = rows[: row_limit - fetched]

            fetched += len(rows)
            yield rows

            if row_limit and fetched >= row_limit:
                break
            url = payload.get("odata.nextLink") or payload.get("@odata.nextLink")


def scalars_only(row: dict) -> dict:
    """Drop nested collections (e.g. DocumentLines) and odata metadata keys."""
    return {
        key: value
        for key, value in row.items()
        if not isinstance(value, (dict, list)) and not key.startswith("odata")
    }


def normalize_b1sl_dataframe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for column in df.columns:
        if df[column].dtype != object:
            continue
        values = df[column].dropna()
        if len(values) and all(isinstance(v, str) and ISO_DATE_PATTERN.match(v) for v in values):
            df[column] = pd.to_datetime(df[column], errors="coerce", format="mixed")
    return df


def get_b1sl_table_list(data_source) -> list[str]:
    return B1ServiceLayerClient(data_source).list_entities()


def get_b1sl_sample(data_source, entity: str) -> pd.DataFrame:
    client = B1ServiceLayerClient(data_source)
    for rows in client.fetch_pages(entity, page_size=B1SL_SAMPLE_SIZE, row_limit=B1SL_SAMPLE_SIZE):
        return normalize_b1sl_dataframe(rows)
    frappe.throw(
        f"Entity {entity} returned no rows; cannot infer its schema. "
        "Import at least one record in SAP B1 first."
    )


def get_b1sl_ibis_schema(data_source, entity: str) -> ibis.Schema:
    return ibis.memtable(get_b1sl_sample(data_source, entity)).schema()


def build_b1sl_filter(cursor_column: str, bookmark: str) -> str:
    bookmark = str(bookmark)
    if re.fullmatch(r"\d+(\.\d+)?", bookmark):
        return f"{cursor_column} gt {bookmark}"
    if ISO_DATE_PATTERN.match(bookmark):
        bookmark = bookmark.replace(" ", "T")
    return f"{cursor_column} gt '{bookmark}'"
