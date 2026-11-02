-- Data-quality rules, the views the semantic model imports beyond the star schema, and the
-- reconciliation view the tests (and the DAX queries in powerbi/reconcile) are checked against.

CREATE OR ALTER PROCEDURE dq.run_rules @run_id int, @now_utc datetime2(0)
AS
BEGIN
    SET NOCOUNT ON;
    -- A rebuilt date also moves the trailing windows of the six dates after it.
    SELECT DISTINCT DATEADD(day, n.n, a.d) AS d INTO #d
    FROM meta.affected_date a CROSS JOIN (VALUES (0), (1), (2), (3), (4), (5), (6)) n(n)
    WHERE a.run_id = @run_id;
    CREATE TABLE #r (rule_code varchar(40), subject varchar(40), branch_key int, check_date date,
                     checked_rows int, failed_rows int, measured_value decimal(9,4));

    -- Share rules are scored over the trailing seven days ending on each date: a branch makes about 30
    -- stops a day here, so a single day's share swings on one or two stops.
    INSERT #r
    SELECT 'GEOFENCE_MISSING', '', f.branch_key, dd.d, COUNT(*), SUM(1 - f.has_geofence),
           CAST(1.0 * SUM(1 - f.has_geofence) / COUNT(*) AS decimal(9,4))
    FROM #d dd JOIN gold.fact_delivery_stop f ON f.service_date BETWEEN DATEADD(day, -6, dd.d) AND dd.d
    GROUP BY f.branch_key, dd.d
    HAVING SUM(CASE WHEN f.service_date = dd.d THEN 1 ELSE 0 END) > 0;

    INSERT #r
    SELECT 'TMS_BACKFILLED', '', f.branch_key, dd.d, SUM(f.has_geofence), SUM(f.is_backfilled),
           CAST(1.0 * SUM(f.is_backfilled) / SUM(f.has_geofence) AS decimal(9,4))
    FROM #d dd JOIN gold.fact_delivery_stop f ON f.service_date BETWEEN DATEADD(day, -6, dd.d) AND dd.d
    GROUP BY f.branch_key, dd.d
    HAVING SUM(f.has_geofence) > 0 AND SUM(CASE WHEN f.service_date = dd.d THEN 1 ELSE 0 END) > 0;

    INSERT #r
    SELECT 'ARRIVAL_BEFORE_DISPATCH', '', x.branch_key, x.d, SUM(x.n), SUM(x.q), CAST(1.0 * SUM(x.q) / SUM(x.n) AS decimal(9,4))
    FROM (SELECT branch_key, service_date AS d, COUNT(*) AS n, 0 AS q
          FROM gold.fact_delivery_stop WHERE service_date IN (SELECT d FROM #d) GROUP BY branch_key, service_date
          UNION ALL
          SELECT ISNULL(b.branch_key, -1), q.record_date, COUNT(*), COUNT(*)
          FROM dq.quarantine q LEFT JOIN gold.dim_branch b ON b.branch_code = q.branch_code
          WHERE q.rule_code = 'ARRIVAL_BEFORE_DISPATCH' AND q.record_date IN (SELECT d FROM #d)
          GROUP BY ISNULL(b.branch_key, -1), q.record_date) x
    GROUP BY x.branch_key, x.d;

    INSERT #r
    SELECT 'ORDER_WITHOUT_STOP', '', ISNULL(b.branch_key, -1), dd.d, COUNT(*),
           SUM(CASE WHEN s.stop_id IS NULL THEN 1 ELSE 0 END),
           CAST(1.0 * SUM(CASE WHEN s.stop_id IS NULL THEN 1 ELSE 0 END) / COUNT(*) AS decimal(9,4))
    FROM #d dd
    JOIN silver.sales_order o ON o.service_date BETWEEN DATEADD(day, -6, dd.d) AND dd.d
    LEFT JOIN silver.stop s ON s.stop_id = o.tms_stop_id
    LEFT JOIN gold.dim_customer c ON c.customer_number = o.customer_number
                                 AND o.service_date BETWEEN c.valid_from AND c.valid_to
    LEFT JOIN gold.dim_branch b ON b.branch_code = c.branch_code
    WHERE o.order_type = 'delivery'
    GROUP BY ISNULL(b.branch_key, -1), dd.d
    HAVING SUM(CASE WHEN o.service_date = dd.d THEN 1 ELSE 0 END) > 0;

    INSERT #r
    SELECT 'FUEL_OFF_ROUTE', '', branch_key, txn_date, COUNT(*), SUM(1 - is_on_route_day),
           CAST(1.0 * SUM(1 - is_on_route_day) / COUNT(*) AS decimal(9,4))
    FROM gold.fact_fuel WHERE txn_date IN (SELECT d FROM #d)
    GROUP BY branch_key, txn_date;

    -- Freshness: hours between the run's clock and the newest record from each API source.
    INSERT #r
    SELECT 'SOURCE_STALE', x.source, -1, CAST(@now_utc AS date), 1, 0,
           CAST(DATEDIFF(minute, x.newest, @now_utc) / 60.0 AS decimal(9,4))
    FROM (SELECT 'tms_stop' AS source, MAX(updated_utc) AS newest FROM silver.stop
          UNION ALL SELECT 'tms_route_plan', MAX(updated_utc) FROM silver.route_plan
          UNION ALL SELECT 'tel_visit', MAX(updated_utc) FROM silver.visit
          UNION ALL SELECT 'tel_trip', MAX(updated_utc) FROM silver.trip) x
    WHERE x.newest IS NOT NULL;

    UPDATE r SET failed_rows = CASE WHEN r.measured_value > d.threshold THEN 1 ELSE 0 END
    FROM #r r JOIN dq.rule_def d ON d.rule_code = r.rule_code WHERE r.rule_code = 'SOURCE_STALE';

    DELETE t FROM dq.result t
    WHERE EXISTS (SELECT 1 FROM #r r WHERE r.rule_code = t.rule_code AND r.subject = t.subject
                  AND r.branch_key = t.branch_key AND r.check_date = t.check_date);
    INSERT dq.result (rule_code, subject, branch_key, check_date, check_date_key, checked_rows, failed_rows,
                      measured_value, threshold, breached, run_id)
    SELECT r.rule_code, r.subject, r.branch_key, r.check_date,
           YEAR(r.check_date) * 10000 + MONTH(r.check_date) * 100 + DAY(r.check_date),
           r.checked_rows, r.failed_rows, r.measured_value, d.threshold,
           CASE WHEN r.measured_value > d.threshold THEN 1 ELSE 0 END, @run_id
    FROM #r r JOIN dq.rule_def d ON d.rule_code = r.rule_code;

    DELETE FROM dq.run_summary WHERE run_id = @run_id;
    INSERT dq.run_summary (run_id, rule_code, severity, checked_rows, failed_rows, breaches, blocks_refresh)
    SELECT @run_id, d.rule_code, d.severity, ISNULL(SUM(r.checked_rows), 0), ISNULL(SUM(r.failed_rows), 0),
           ISNULL(SUM(CASE WHEN r.measured_value > d.threshold THEN 1 ELSE 0 END), 0),
           CASE WHEN d.severity = 'block' AND SUM(r.checked_rows) > 0
                 AND 1.0 * SUM(r.failed_rows) / SUM(r.checked_rows) > d.block_threshold THEN 1 ELSE 0 END
    FROM dq.rule_def d LEFT JOIN #r r ON r.rule_code = d.rule_code
    GROUP BY d.rule_code, d.severity, d.block_threshold;

    SELECT rule_code, severity, checked_rows, failed_rows, breaches, blocks_refresh
    FROM dq.run_summary WHERE run_id = @run_id ORDER BY rule_code;
END;
GO

CREATE OR ALTER VIEW rpt.dq_result AS
SELECT r.rule_code, d.description, d.severity, r.subject, r.branch_key, r.check_date_key, r.checked_rows,
       r.failed_rows, r.measured_value, r.threshold, CAST(r.breached AS int) AS breached
FROM dq.result r JOIN dq.rule_def d ON d.rule_code = r.rule_code;
GO

CREATE OR ALTER VIEW rpt.pipeline_run AS
SELECT run_id, started_utc, finished_utc, source_clock_utc, status, ISNULL(refresh_status, 'n/a') AS refresh_status
FROM meta.run;
GO

CREATE OR ALTER VIEW sec.user_branch_access AS
SELECT u.user_principal_name, b.branch_key
FROM sec.user_branch u JOIN gold.dim_branch b ON b.branch_code = u.branch_code;
GO

-- One row per branch and month with the headline KPIs, computed straight from the gold tables.
-- Each column has a DAX twin in the semantic model; powerbi/reconcile holds the matching DAX query.
CREATE OR ALTER VIEW rpt.kpi_branch_month AS
WITH s AS (
    SELECT f.branch_key, d.year_month, COUNT(*) AS stops, SUM(f.is_on_time) AS on_time,
           SUM(f.is_on_time_tms) AS on_time_tms, SUM(f.is_in_full) AS in_full, SUM(f.is_otif) AS otif,
           SUM(f.delivered_cases) AS delivered_cases
    FROM gold.fact_delivery_stop f JOIN gold.dim_date d ON d.date_key = f.service_date_key
    GROUP BY f.branch_key, d.year_month),
i AS (
    SELECT f.branch_key, d.year_month, SUM(f.revenue) AS revenue, SUM(f.cost) AS cost,
           SUM(CASE WHEN f.is_credit = 1 THEN f.revenue ELSE 0 END) AS credits
    FROM gold.fact_invoice_line f JOIN gold.dim_date d ON d.date_key = f.posting_date_key
    GROUP BY f.branch_key, d.year_month),
t AS (
    SELECT f.branch_key, d.year_month, SUM(f.driven_miles) AS driven_miles, SUM(f.labor_cost) AS labor_cost
    FROM gold.fact_route_trip f JOIN gold.dim_date d ON d.date_key = f.service_date_key
    GROUP BY f.branch_key, d.year_month),
fu AS (
    SELECT f.branch_key, d.year_month, SUM(f.fuel_cost) AS fuel_cost, SUM(f.gallons) AS gallons
    FROM gold.fact_fuel f JOIN gold.dim_date d ON d.date_key = f.txn_date_key
    GROUP BY f.branch_key, d.year_month)
SELECT b.branch_code, b.branch_name, s.year_month, s.stops,
       CAST(1.0 * s.on_time / s.stops AS decimal(9,4)) AS on_time_pct,
       CAST(1.0 * s.on_time_tms / s.stops AS decimal(9,4)) AS on_time_tms_pct,
       CAST(1.0 * s.in_full / s.stops AS decimal(9,4)) AS in_full_pct,
       CAST(1.0 * s.otif / s.stops AS decimal(9,4)) AS otif_pct,
       s.delivered_cases, i.revenue, i.cost, i.credits,
       CAST((i.revenue - i.cost) / NULLIF(i.revenue, 0) AS decimal(9,4)) AS gross_margin_pct,
       t.driven_miles, t.labor_cost, fu.fuel_cost, fu.gallons,
       ISNULL(t.labor_cost, 0) + ISNULL(fu.fuel_cost, 0) AS fleet_cost,
       CAST((ISNULL(t.labor_cost, 0) + ISNULL(fu.fuel_cost, 0)) / NULLIF(s.delivered_cases, 0) AS decimal(9,4))
           AS cost_per_case
FROM s
JOIN gold.dim_branch b ON b.branch_key = s.branch_key
LEFT JOIN i ON i.branch_key = s.branch_key AND i.year_month = s.year_month
LEFT JOIN t ON t.branch_key = s.branch_key AND t.year_month = s.year_month
LEFT JOIN fu ON fu.branch_key = s.branch_key AND fu.year_month = s.year_month;
GO
