-- Gold: the star schema the semantic model imports. Dimensions use stable integer surrogate keys
-- (new members get MAX + ROW_NUMBER, no IDENTITY); -1 is the unknown member in every dimension.
-- Facts are rebuilt for the dates in meta.affected_date for this run.

CREATE OR ALTER PROCEDURE gold.load_dims @run_id int
AS
BEGIN
    SET NOCOUNT ON;

    IF NOT EXISTS (SELECT 1 FROM gold.dim_date)
    BEGIN
        WITH n AS (SELECT TOP (DATEDIFF(day, '2024-01-01', '2027-12-31') + 1)
                          ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS i
                   FROM sys.all_objects a CROSS JOIN sys.all_objects b),
             d AS (SELECT DATEADD(day, i, CAST('2024-01-01' AS date)) AS dt FROM n)
        INSERT gold.dim_date (date_key, [date], [year], quarter_label, month_number, month_name, month_start, year_month,
                              iso_week, weekday_number, weekday_name, is_operating_day)
        SELECT YEAR(dt) * 10000 + MONTH(dt) * 100 + DAY(dt), dt, YEAR(dt),
               CONCAT(YEAR(dt), ' Q', DATEPART(quarter, dt)), MONTH(dt), DATENAME(month, dt),
               DATEFROMPARTS(YEAR(dt), MONTH(dt), 1), CONCAT(YEAR(dt), '-', RIGHT('0' + CAST(MONTH(dt) AS varchar(2)), 2)),
               DATEPART(iso_week, dt), (DATEPART(weekday, dt) + @@DATEFIRST + 5) % 7 + 1, DATENAME(weekday, dt),
               CASE WHEN (DATEPART(weekday, dt) + @@DATEFIRST + 5) % 7 + 1 = 7 THEN 0 ELSE 1 END
        FROM d;
    END;

    -- Branch
    IF NOT EXISTS (SELECT 1 FROM gold.dim_branch WHERE branch_key = -1)
        INSERT gold.dim_branch VALUES (-1, '?', N'Unknown', 'Unknown', 'UTC');
    UPDATE d SET branch_name = s.branch_name, region = s.region, time_zone = s.time_zone
    FROM gold.dim_branch d JOIN silver.branch s ON s.branch_code = d.branch_code;
    INSERT gold.dim_branch (branch_key, branch_code, branch_name, region, time_zone)
    SELECT (SELECT ISNULL(MAX(branch_key), 0) FROM gold.dim_branch WHERE branch_key > 0)
           + ROW_NUMBER() OVER (ORDER BY s.branch_code), s.branch_code, s.branch_name, s.region, s.time_zone
    FROM silver.branch s WHERE NOT EXISTS (SELECT 1 FROM gold.dim_branch d WHERE d.branch_code = s.branch_code);

    -- Product category
    IF NOT EXISTS (SELECT 1 FROM gold.dim_category WHERE category_key = -1)
        INSERT gold.dim_category VALUES (-1, '?', N'Unknown', 'Unknown');
    UPDATE d SET category_name = s.category_name, temp_zone = s.temp_zone
    FROM gold.dim_category d JOIN silver.category s ON s.category_code = d.category_code;
    INSERT gold.dim_category (category_key, category_code, category_name, temp_zone)
    SELECT (SELECT ISNULL(MAX(category_key), 0) FROM gold.dim_category WHERE category_key > 0)
           + ROW_NUMBER() OVER (ORDER BY s.category_code), s.category_code, s.category_name, s.temp_zone
    FROM silver.category s WHERE NOT EXISTS (SELECT 1 FROM gold.dim_category d WHERE d.category_code = s.category_code);

    -- Truck
    IF NOT EXISTS (SELECT 1 FROM gold.dim_truck WHERE truck_key = -1)
        INSERT gold.dim_truck VALUES (-1, '?', N'Unknown', NULL, 'Unknown');
    UPDATE d SET home_branch = ISNULL(b.branch_name, N'Unknown'), model_year = s.model_year, reefer_type = s.reefer_type
    FROM gold.dim_truck d JOIN silver.truck s ON s.truck_code = d.truck_code
    LEFT JOIN silver.branch b ON b.branch_code = s.branch_code;
    INSERT gold.dim_truck (truck_key, truck_code, home_branch, model_year, reefer_type)
    SELECT (SELECT ISNULL(MAX(truck_key), 0) FROM gold.dim_truck WHERE truck_key > 0)
           + ROW_NUMBER() OVER (ORDER BY s.truck_code), s.truck_code, ISNULL(b.branch_name, N'Unknown'), s.model_year,
           s.reefer_type
    FROM silver.truck s LEFT JOIN silver.branch b ON b.branch_code = s.branch_code
    WHERE NOT EXISTS (SELECT 1 FROM gold.dim_truck d WHERE d.truck_code = s.truck_code);

    -- Driver
    IF NOT EXISTS (SELECT 1 FROM gold.dim_driver WHERE driver_key = -1)
        INSERT gold.dim_driver VALUES (-1, '?', N'Unknown', N'Unknown');
    UPDATE d SET driver_name = s.driver_name, home_branch = ISNULL(b.branch_name, N'Unknown')
    FROM gold.dim_driver d JOIN silver.driver s ON s.driver_code = d.driver_code
    LEFT JOIN silver.branch b ON b.branch_code = s.branch_code;
    INSERT gold.dim_driver (driver_key, driver_code, driver_name, home_branch)
    SELECT (SELECT ISNULL(MAX(driver_key), 0) FROM gold.dim_driver WHERE driver_key > 0)
           + ROW_NUMBER() OVER (ORDER BY s.driver_code), s.driver_code, s.driver_name, ISNULL(b.branch_name, N'Unknown')
    FROM silver.driver s LEFT JOIN silver.branch b ON b.branch_code = s.branch_code
    WHERE NOT EXISTS (SELECT 1 FROM gold.dim_driver d WHERE d.driver_code = s.driver_code);

    -- Route: the latest name and branch seen on a route plan.
    IF NOT EXISTS (SELECT 1 FROM gold.dim_route WHERE route_key = -1)
        INSERT gold.dim_route VALUES (-1, '?', N'No route', N'Unknown');
    WITH r AS (SELECT route_code, route_name, branch_code,
                      ROW_NUMBER() OVER (PARTITION BY route_code ORDER BY route_date DESC) AS rn
               FROM silver.route_plan)
    SELECT r.route_code, r.route_name, ISNULL(b.branch_name, N'Unknown') AS route_branch INTO #route
    FROM r LEFT JOIN silver.branch b ON b.branch_code = r.branch_code WHERE r.rn = 1;
    UPDATE d SET route_name = s.route_name, route_branch = s.route_branch
    FROM gold.dim_route d JOIN #route s ON s.route_code = d.route_code;
    INSERT gold.dim_route (route_key, route_code, route_name, route_branch)
    SELECT (SELECT ISNULL(MAX(route_key), 0) FROM gold.dim_route WHERE route_key > 0)
           + ROW_NUMBER() OVER (ORDER BY s.route_code), s.route_code, s.route_name, s.route_branch
    FROM #route s WHERE NOT EXISTS (SELECT 1 FROM gold.dim_route d WHERE d.route_code = s.route_code);

    -- Customer, Type 2 on branch assignment. One version per row of the ERP's branch history.
    IF NOT EXISTS (SELECT 1 FROM gold.dim_customer WHERE customer_key = -1)
        INSERT gold.dim_customer VALUES (-1, '?', N'Unknown', 'Unknown', N'Unknown', '?', '1900-01-01', '9999-12-31', 1, 0);
    WITH v AS (
        SELECT cb.customer_number, cb.effective_from AS valid_from,
               ISNULL(DATEADD(day, -1, LEAD(cb.effective_from) OVER (PARTITION BY cb.customer_number
                                                                      ORDER BY cb.effective_from)),
                      CAST('9999-12-31' AS date)) AS valid_to,
               cb.branch_code, cb.segment, c.customer_name
        FROM silver.customer_branch cb JOIN silver.customer c ON c.customer_number = cb.customer_number)
    SELECT v.*, ISNULL(b.branch_name, N'Unknown') AS customer_branch INTO #cv
    FROM v LEFT JOIN silver.branch b ON b.branch_code = v.branch_code;

    UPDATE d SET valid_to = v.valid_to, is_current = CASE WHEN v.valid_to = '9999-12-31' THEN 1 ELSE 0 END,
                 customer_name = v.customer_name, segment = v.segment, branch_code = v.branch_code,
                 customer_branch = v.customer_branch,
                 changed_run_id = CASE WHEN d.valid_to <> v.valid_to OR d.branch_code <> v.branch_code
                                       THEN @run_id ELSE d.changed_run_id END
    FROM gold.dim_customer d JOIN #cv v ON v.customer_number = d.customer_number AND v.valid_from = d.valid_from;
    INSERT gold.dim_customer (customer_key, customer_number, customer_name, segment, customer_branch, branch_code,
                              valid_from, valid_to, is_current, changed_run_id)
    SELECT (SELECT ISNULL(MAX(customer_key), 0) FROM gold.dim_customer WHERE customer_key > 0)
           + ROW_NUMBER() OVER (ORDER BY v.customer_number, v.valid_from),
           v.customer_number, v.customer_name, v.segment, v.customer_branch, v.branch_code, v.valid_from, v.valid_to,
           CASE WHEN v.valid_to = '9999-12-31' THEN 1 ELSE 0 END, @run_id
    FROM #cv v
    WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer d
                      WHERE d.customer_number = v.customer_number AND d.valid_from = v.valid_from);

    -- A new or changed version re-keys that customer's facts, so their dates are rebuilt too.
    INSERT meta.affected_date (run_id, d)
    SELECT DISTINCT @run_id, x.d FROM (
        SELECT s.route_date AS d FROM silver.stop s
        WHERE s.customer_number IN (SELECT customer_number FROM gold.dim_customer WHERE changed_run_id = @run_id)
        UNION
        SELECT i.posting_date FROM silver.invoice_line i
        WHERE i.customer_number IN (SELECT customer_number FROM gold.dim_customer WHERE changed_run_id = @run_id)
    ) x
    WHERE NOT EXISTS (SELECT 1 FROM meta.affected_date a WHERE a.run_id = @run_id AND a.d = x.d);
END;
GO

CREATE OR ALTER PROCEDURE gold.load_fact_delivery_stop @run_id int
AS
BEGIN
    SET NOCOUNT ON;
    SELECT d INTO #d FROM meta.affected_date WHERE run_id = @run_id;

    -- The geofence arrival is the trusted time. It is matched to the stop by truck, customer site and
    -- local date; the first visit of the day wins.
    SELECT s.stop_id, s.route_date, s.branch_code, s.route_code, s.customer_number, s.driver_code, s.truck_code,
           s.stop_sequence, s.window_start_local, s.window_end_local, s.delivered_local, s.delivered_recorded_utc,
           s.ordered_cases, s.short_cases, s.refused_cases, rp.dispatch_local,
           v.visit_id, v.entered_local, v.exited_local, v.exited_utc
    INTO #s
    FROM silver.stop s
    LEFT JOIN silver.route_plan rp ON rp.route_plan_id = s.route_plan_id
    OUTER APPLY (SELECT TOP (1) vv.visit_id, vv.entered_local, vv.exited_local, vv.exited_utc
                 FROM silver.visit vv
                 WHERE vv.truck_code = s.truck_code AND vv.customer_number = s.customer_number
                   AND vv.visit_date = s.route_date
                 ORDER BY vv.entered_utc) v
    WHERE s.status = 'completed' AND s.route_date IN (SELECT d FROM #d);

    -- A geofence arrival before the route was dispatched is a GPS clock fault, not a delivery.
    DELETE q FROM dq.quarantine q
    WHERE q.rule_code = 'ARRIVAL_BEFORE_DISPATCH' AND q.record_date IN (SELECT d FROM #d);
    INSERT dq.quarantine (rule_code, record_id, record_date, branch_code, detail, run_id)
    SELECT 'ARRIVAL_BEFORE_DISPATCH', stop_id, route_date, branch_code,
           CONCAT(N'Geofence arrival ', CONVERT(varchar(16), entered_local, 120), N' is before dispatch at ',
                  CONVERT(varchar(16), dispatch_local, 120), N' for truck ', truck_code),
           @run_id
    FROM #s WHERE entered_local < dispatch_local;

    DELETE f FROM gold.fact_delivery_stop f WHERE f.service_date IN (SELECT d FROM #d);

    WITH x AS (
        SELECT *, COALESCE(entered_local, delivered_local) AS arrival_local,
               CAST(route_date AS datetime2(0)) AS midnight
        FROM #s
        WHERE entered_local IS NULL OR dispatch_local IS NULL OR entered_local >= dispatch_local)
    INSERT gold.fact_delivery_stop (stop_id, service_date, service_date_key, branch_key, route_key, customer_key,
        driver_key, truck_key, stop_sequence, window_start_minute, window_end_minute, arrival_minute, arrival_source,
        minutes_late, is_on_time, is_on_time_tms, is_in_full, is_otif, has_geofence, is_backfilled, ordered_cases,
        short_cases, refused_cases, delivered_cases, dwell_minutes, run_id)
    SELECT x.stop_id, x.route_date,
           YEAR(x.route_date) * 10000 + MONTH(x.route_date) * 100 + DAY(x.route_date),
           ISNULL(b.branch_key, -1), ISNULL(r.route_key, -1), ISNULL(c.customer_key, -1),
           ISNULL(dr.driver_key, -1), ISNULL(t.truck_key, -1), x.stop_sequence,
           DATEDIFF(minute, x.midnight, x.window_start_local), DATEDIFF(minute, x.midnight, x.window_end_local),
           CASE WHEN x.arrival_local IS NULL THEN NULL ELSE DATEDIFF(minute, x.midnight, x.arrival_local) END,
           CASE WHEN x.visit_id IS NOT NULL THEN 'Geofence' WHEN x.delivered_local IS NOT NULL THEN 'TMS' ELSE 'None' END,
           CASE WHEN x.arrival_local > x.window_end_local
                THEN DATEDIFF(minute, x.window_end_local, x.arrival_local) ELSE 0 END,
           CASE WHEN x.arrival_local IS NOT NULL AND x.arrival_local <= x.window_end_local THEN 1 ELSE 0 END,
           CASE WHEN x.delivered_local IS NOT NULL AND x.delivered_local <= x.window_end_local THEN 1 ELSE 0 END,
           CASE WHEN x.short_cases + x.refused_cases = 0 THEN 1 ELSE 0 END,
           CASE WHEN x.arrival_local IS NOT NULL AND x.arrival_local <= x.window_end_local
                 AND x.short_cases + x.refused_cases = 0 THEN 1 ELSE 0 END,
           CASE WHEN x.visit_id IS NOT NULL THEN 1 ELSE 0 END,
           CASE WHEN x.exited_utc IS NOT NULL AND x.delivered_recorded_utc > DATEADD(minute, 60, x.exited_utc)
                THEN 1 ELSE 0 END,
           x.ordered_cases, x.short_cases, x.refused_cases, x.ordered_cases - x.short_cases - x.refused_cases,
           CASE WHEN x.visit_id IS NULL THEN NULL ELSE DATEDIFF(minute, x.entered_local, x.exited_local) END,
           @run_id
    FROM x
    LEFT JOIN gold.dim_branch b ON b.branch_code = x.branch_code
    LEFT JOIN gold.dim_route r ON r.route_code = x.route_code
    LEFT JOIN gold.dim_customer c ON c.customer_number = x.customer_number
                                 AND x.route_date BETWEEN c.valid_from AND c.valid_to
    LEFT JOIN gold.dim_driver dr ON dr.driver_code = x.driver_code
    LEFT JOIN gold.dim_truck t ON t.truck_code = x.truck_code;
END;
GO

CREATE OR ALTER PROCEDURE gold.load_fact_invoice_line @run_id int
AS
BEGIN
    SET NOCOUNT ON;
    SELECT d INTO #d FROM meta.affected_date WHERE run_id = @run_id;
    DELETE f FROM gold.fact_invoice_line f WHERE f.posting_date IN (SELECT d FROM #d);
    -- Credits stay at their own posting date, which is how finance reports them; in-full on the
    -- delivery side comes from the short and refused cases recorded at the stop, not from credits.
    INSERT gold.fact_invoice_line (invoice_number, line_no, posting_date, posting_date_key, branch_key, customer_key,
                                   category_key, route_key, order_type, is_credit, cases, revenue, cost, run_id)
    SELECT i.invoice_number, i.line_no, i.posting_date,
           YEAR(i.posting_date) * 10000 + MONTH(i.posting_date) * 100 + DAY(i.posting_date),
           ISNULL(b.branch_key, -1), ISNULL(c.customer_key, -1), ISNULL(k.category_key, -1), ISNULL(r.route_key, -1),
           ISNULL(o.order_type, 'unknown'), i.is_credit, i.cases, i.revenue, i.cost, @run_id
    FROM silver.invoice_line i
    LEFT JOIN gold.dim_customer c ON c.customer_number = i.customer_number
                                 AND i.posting_date BETWEEN c.valid_from AND c.valid_to
    LEFT JOIN gold.dim_branch b ON b.branch_code = c.branch_code
    LEFT JOIN gold.dim_category k ON k.category_code = i.category_code
    LEFT JOIN silver.sales_order o ON o.order_number = i.order_number
    LEFT JOIN silver.stop s ON s.stop_id = o.tms_stop_id
    LEFT JOIN gold.dim_route r ON r.route_code = s.route_code
    WHERE i.posting_date IN (SELECT d FROM #d);
END;
GO

CREATE OR ALTER PROCEDURE gold.load_fact_route_trip @run_id int
AS
BEGIN
    SET NOCOUNT ON;
    SELECT d INTO #d FROM meta.affected_date WHERE run_id = @run_id;
    DELETE f FROM gold.fact_route_trip f WHERE f.service_date IN (SELECT d FROM #d);
    -- Driver hours run from dispatch to return plus 30 minutes of pre- and post-trip inspection.
    WITH cs AS (SELECT route_plan_id, COUNT(*) AS completed FROM silver.stop
                WHERE status = 'completed' AND route_date IN (SELECT d FROM #d) GROUP BY route_plan_id)
    INSERT gold.fact_route_trip (route_plan_id, service_date, service_date_key, branch_key, route_key, truck_key,
                                 driver_key, planned_stops, completed_stops, planned_miles, driven_miles,
                                 driver_hours, labor_cost, run_id)
    SELECT rp.route_plan_id, rp.route_date,
           YEAR(rp.route_date) * 10000 + MONTH(rp.route_date) * 100 + DAY(rp.route_date),
           ISNULL(b.branch_key, -1), ISNULL(r.route_key, -1), ISNULL(t.truck_key, -1), ISNULL(dr.driver_key, -1),
           rp.planned_stops, ISNULL(cs.completed, 0), rp.planned_miles, tr.miles,
           CAST(DATEDIFF(minute, tr.started_utc, tr.ended_utc) / 60.0 + 0.5 AS decimal(6,2)),
           CAST((DATEDIFF(minute, tr.started_utc, tr.ended_utc) / 60.0 + 0.5) * sd.hourly_rate AS decimal(10,2)),
           @run_id
    FROM silver.route_plan rp
    LEFT JOIN silver.trip tr ON tr.truck_code = rp.truck_code AND tr.trip_date = rp.route_date
    LEFT JOIN cs ON cs.route_plan_id = rp.route_plan_id
    LEFT JOIN silver.driver sd ON sd.driver_code = rp.driver_code
    LEFT JOIN gold.dim_branch b ON b.branch_code = rp.branch_code
    LEFT JOIN gold.dim_route r ON r.route_code = rp.route_code
    LEFT JOIN gold.dim_truck t ON t.truck_code = rp.truck_code
    LEFT JOIN gold.dim_driver dr ON dr.driver_code = rp.driver_code
    WHERE rp.route_date IN (SELECT d FROM #d)
      AND (tr.trip_id IS NOT NULL OR ISNULL(cs.completed, 0) > 0);
END;
GO

CREATE OR ALTER PROCEDURE gold.load_fact_fuel @run_id int
AS
BEGIN
    SET NOCOUNT ON;
    SELECT d INTO #d FROM meta.affected_date WHERE run_id = @run_id;
    DELETE f FROM gold.fact_fuel f WHERE f.txn_date IN (SELECT d FROM #d);
    INSERT gold.fact_fuel (file_name, line_no, txn_date, txn_date_key, branch_key, truck_key, gallons, fuel_cost,
                           is_on_route_day, run_id)
    SELECT f.file_name, f.line_no, f.txn_date, YEAR(f.txn_date) * 10000 + MONTH(f.txn_date) * 100 + DAY(f.txn_date),
           ISNULL(b.branch_key, -1), ISNULL(t.truck_key, -1), f.gallons, f.amount,
           CASE WHEN EXISTS (SELECT 1 FROM silver.route_plan rp
                             WHERE rp.truck_code = f.truck_code AND rp.route_date = f.txn_date) THEN 1 ELSE 0 END,
           @run_id
    FROM silver.fuel_txn f
    LEFT JOIN silver.truck st ON st.truck_code = f.truck_code
    LEFT JOIN gold.dim_branch b ON b.branch_code = st.branch_code
    LEFT JOIN gold.dim_truck t ON t.truck_code = f.truck_code
    WHERE f.txn_date IN (SELECT d FROM #d);
END;
GO
