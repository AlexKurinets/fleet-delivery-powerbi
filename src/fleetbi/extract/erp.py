"""Rowversion-watermarked copy of the ERP tables into landing (the gateway copy activity in production).

The upper bound is MIN_ACTIVE_ROWVERSION() taken before the copy, so a row written by a transaction
that is still open when the copy starts is picked up by the next run instead of being skipped.
"""

from __future__ import annotations

import logging

from .. import db
from ..config import Settings
from .api import get_watermark, set_watermark

log = logging.getLogger(__name__)

TABLES = {
    "branch": ["branch_code", "branch_name", "region", "time_zone"],
    "category": ["category_code", "category_name", "temp_zone"],
    "truck": ["truck_code", "branch_code", "model_year", "reefer_type"],
    "driver": ["driver_code", "driver_name", "branch_code", "hourly_rate"],
    "customer": ["customer_number", "customer_name", "segment", "branch_code"],
    "customer_branch_history": ["customer_number", "effective_from", "branch_code", "segment"],
    "sales_order": ["order_number", "customer_number", "service_date", "tms_stop_id", "order_type"],
    "invoice_line": ["invoice_number", "line_no", "order_number", "customer_number", "posting_date", "category_code",
                     "cases", "revenue", "cost", "original_invoice_number"],
}


def extract_erp(conn, s: Settings, run_id: int) -> dict[str, int]:
    erp = db.connect(s, s.erp_db)
    hi = int(db.scalar(erp, "SELECT CAST(MIN_ACTIVE_ROWVERSION() AS bigint)"))
    erp.close()
    landed = {}
    for table, cols in TABLES.items():
        source = f"erp_{table}"
        lo = int(get_watermark(conn, source) or 0)
        col_list = ", ".join(cols)
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO landing.erp_{table} ({col_list}, rv, run_id) "
                f"SELECT {col_list}, CAST(rv AS bigint), %s FROM [{s.erp_db}].dbo.{table} "
                f"WHERE rv >= CAST(CAST(%s AS bigint) AS binary(8)) AND rv < CAST(CAST(%s AS bigint) AS binary(8))",
                (run_id, lo, hi))
            n = cur.rowcount
        set_watermark(conn, source, str(hi))
        db.execute(conn, "INSERT meta.source_load (run_id, source, rows_landed, watermark_from, watermark_to) "
                         "VALUES (%s, %s, %s, %s, %s)", (run_id, source, n, str(lo), str(hi)))
        landed[source] = n
    log.info("ERP rows landed: %s", landed)
    return landed
