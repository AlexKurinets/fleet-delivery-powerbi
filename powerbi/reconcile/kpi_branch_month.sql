-- The warehouse side of the reconciliation. Same grain and columns as kpi_branch_month.dax.
SELECT branch_code, year_month, stops, on_time_pct, on_time_tms_pct, in_full_pct, otif_pct, revenue,
       gross_margin_pct, fleet_cost, cost_per_case
FROM rpt.kpi_branch_month
ORDER BY branch_code, year_month;
