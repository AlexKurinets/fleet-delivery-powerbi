-- Silver: typed, deduplicated, one row per business key, timestamps converted to branch local time.
-- Each procedure reads only the landing rows of the current run and upserts by business key
-- (delete then insert; no MERGE), so re-running a run or re-reading an overlap window is harmless.

CREATE OR ALTER PROCEDURE silver.load_erp @run_id int
AS
BEGIN
    SET NOCOUNT ON;

    WITH n AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY branch_code ORDER BY rv DESC) AS rn
               FROM landing.erp_branch WHERE run_id = @run_id)
    SELECT branch_code, branch_name, region, time_zone INTO #branch FROM n WHERE rn = 1;
    DELETE s FROM silver.branch s WHERE EXISTS (SELECT 1 FROM #branch n WHERE n.branch_code = s.branch_code);
    INSERT silver.branch (branch_code, branch_name, region, time_zone, run_id)
    SELECT branch_code, branch_name, region, time_zone, @run_id FROM #branch;

    WITH n AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY category_code ORDER BY rv DESC) AS rn
               FROM landing.erp_category WHERE run_id = @run_id)
    SELECT category_code, category_name, temp_zone INTO #category FROM n WHERE rn = 1;
    DELETE s FROM silver.category s WHERE EXISTS (SELECT 1 FROM #category n WHERE n.category_code = s.category_code);
    INSERT silver.category (category_code, category_name, temp_zone, run_id)
    SELECT category_code, category_name, temp_zone, @run_id FROM #category;

    WITH n AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY truck_code ORDER BY rv DESC) AS rn
               FROM landing.erp_truck WHERE run_id = @run_id)
    SELECT truck_code, branch_code, model_year, reefer_type INTO #truck FROM n WHERE rn = 1;
    DELETE s FROM silver.truck s WHERE EXISTS (SELECT 1 FROM #truck n WHERE n.truck_code = s.truck_code);
    INSERT silver.truck (truck_code, branch_code, model_year, reefer_type, run_id)
    SELECT truck_code, branch_code, model_year, reefer_type, @run_id FROM #truck;

    WITH n AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY driver_code ORDER BY rv DESC) AS rn
               FROM landing.erp_driver WHERE run_id = @run_id)
    SELECT driver_code, driver_name, branch_code, hourly_rate INTO #driver FROM n WHERE rn = 1;
    DELETE s FROM silver.driver s WHERE EXISTS (SELECT 1 FROM #driver n WHERE n.driver_code = s.driver_code);
    INSERT silver.driver (driver_code, driver_name, branch_code, hourly_rate, run_id)
    SELECT driver_code, driver_name, branch_code, hourly_rate, @run_id FROM #driver;

    WITH n AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_number ORDER BY rv DESC) AS rn
               FROM landing.erp_customer WHERE run_id = @run_id)
    SELECT customer_number, customer_name, segment, branch_code INTO #customer FROM n WHERE rn = 1;
    DELETE s FROM silver.customer s WHERE EXISTS (SELECT 1 FROM #customer n WHERE n.customer_number = s.customer_number);
    INSERT silver.customer (customer_number, customer_name, segment, branch_code, run_id)
    SELECT customer_number, customer_name, segment, branch_code, @run_id FROM #customer;

    WITH n AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_number, effective_from ORDER BY rv DESC) AS rn
               FROM landing.erp_customer_branch_history WHERE run_id = @run_id)
    SELECT customer_number, effective_from, branch_code, segment INTO #cbh FROM n WHERE rn = 1;
    DELETE s FROM silver.customer_branch s
    WHERE EXISTS (SELECT 1 FROM #cbh n WHERE n.customer_number = s.customer_number AND n.effective_from = s.effective_from);
    INSERT silver.customer_branch (customer_number, effective_from, branch_code, segment, run_id)
    SELECT customer_number, effective_from, branch_code, segment, @run_id FROM #cbh;

    WITH n AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY order_number ORDER BY rv DESC) AS rn
               FROM landing.erp_sales_order WHERE run_id = @run_id)
    SELECT order_number, customer_number, service_date, tms_stop_id, order_type INTO #order FROM n WHERE rn = 1;
    DELETE s FROM silver.sales_order s WHERE EXISTS (SELECT 1 FROM #order n WHERE n.order_number = s.order_number);
    INSERT silver.sales_order (order_number, customer_number, service_date, tms_stop_id, order_type, run_id)
    SELECT order_number, customer_number, service_date, tms_stop_id, order_type, @run_id FROM #order;

    WITH n AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY invoice_number, line_no ORDER BY rv DESC) AS rn
               FROM landing.erp_invoice_line WHERE run_id = @run_id)
    SELECT invoice_number, line_no, order_number, customer_number, posting_date, category_code, cases, revenue, cost,
           original_invoice_number INTO #line FROM n WHERE rn = 1;
    DELETE s FROM silver.invoice_line s
    WHERE EXISTS (SELECT 1 FROM #line n WHERE n.invoice_number = s.invoice_number AND n.line_no = s.line_no);
    INSERT silver.invoice_line (invoice_number, line_no, order_number, customer_number, posting_date, category_code,
                                cases, revenue, cost, original_invoice_number, is_credit, run_id)
    SELECT invoice_number, line_no, order_number, customer_number, posting_date, category_code, cases, revenue, cost,
           original_invoice_number,
           CASE WHEN original_invoice_number IS NOT NULL OR cases < 0 THEN 1 ELSE 0 END, @run_id
    FROM #line;
END;
GO

CREATE OR ALTER PROCEDURE silver.load_api @run_id int
AS
BEGIN
    SET NOCOUNT ON;

    -- Route plans (TMS). dispatch_at is branch local time with no offset, as the TMS sends it.
    WITH n AS (SELECT payload, updated_utc,
                      ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY updated_utc DESC, loaded_utc DESC) AS rn
               FROM landing.api_record WHERE entity = 'tms_route_plan' AND run_id = @run_id)
    SELECT j.*, n.updated_utc INTO #rp
    FROM n CROSS APPLY OPENJSON(n.payload) WITH (
        route_plan_id varchar(36) '$.id', route_code varchar(12) '$.route_code', route_name nvarchar(60) '$.route_name',
        branch_code varchar(8) '$.branch_code', route_date date '$.route_date', truck_code varchar(8) '$.truck_code',
        driver_code varchar(8) '$.driver_code', dispatch_local datetime2(0) '$.dispatch_at',
        planned_miles decimal(7,1) '$.planned_miles', planned_stops int '$.planned_stops') j
    WHERE n.rn = 1;
    DELETE s FROM silver.route_plan s JOIN #rp n ON n.route_plan_id = s.route_plan_id WHERE n.updated_utc >= s.updated_utc;
    INSERT silver.route_plan (route_plan_id, route_code, route_name, branch_code, route_date, truck_code, driver_code,
                              dispatch_local, planned_miles, planned_stops, updated_utc, run_id)
    SELECT route_plan_id, route_code, route_name, branch_code, route_date, truck_code, driver_code, dispatch_local,
           planned_miles, planned_stops, updated_utc, @run_id
    FROM #rp n WHERE NOT EXISTS (SELECT 1 FROM silver.route_plan s WHERE s.route_plan_id = n.route_plan_id);

    -- Stops (TMS). Windows and delivered_at are local; delivered_recorded_at is UTC.
    WITH n AS (SELECT payload, updated_utc,
                      ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY updated_utc DESC, loaded_utc DESC) AS rn
               FROM landing.api_record WHERE entity = 'tms_stop' AND run_id = @run_id)
    SELECT j.stop_id, j.route_plan_id, j.route_code, j.route_date, j.branch_code, j.truck_code, j.driver_code,
           j.stop_sequence, j.customer_number, j.order_number, j.status, j.window_start_local, j.window_end_local,
           j.delivered_local, CAST(j.delivered_recorded AS datetime2(0)) AS delivered_recorded_utc,
           j.ordered_cases, j.short_cases, j.refused_cases, n.updated_utc
    INTO #stop
    FROM n CROSS APPLY OPENJSON(n.payload) WITH (
        stop_id varchar(36) '$.id', route_plan_id varchar(36) '$.route_plan_id', route_code varchar(12) '$.route_code',
        route_date date '$.route_date', branch_code varchar(8) '$.branch_code', truck_code varchar(8) '$.truck_code',
        driver_code varchar(8) '$.driver_code', stop_sequence int '$.sequence',
        customer_number varchar(12) '$.customer_number', order_number varchar(16) '$.order_number',
        status varchar(12) '$.status', window_start_local datetime2(0) '$.window_start',
        window_end_local datetime2(0) '$.window_end', delivered_local datetime2(0) '$.delivered_at',
        delivered_recorded datetimeoffset(0) '$.delivered_recorded_at', ordered_cases int '$.ordered_cases',
        short_cases int '$.short_cases', refused_cases int '$.refused_cases') j
    WHERE n.rn = 1;
    DELETE s FROM silver.stop s JOIN #stop n ON n.stop_id = s.stop_id WHERE n.updated_utc >= s.updated_utc;
    INSERT silver.stop (stop_id, route_plan_id, route_code, route_date, branch_code, truck_code, driver_code,
                        stop_sequence, customer_number, order_number, status, window_start_local, window_end_local,
                        delivered_local, delivered_recorded_utc, ordered_cases, short_cases, refused_cases,
                        updated_utc, run_id)
    SELECT stop_id, route_plan_id, route_code, route_date, branch_code, truck_code, driver_code, stop_sequence,
           customer_number, order_number, status, window_start_local, window_end_local, delivered_local,
           delivered_recorded_utc, ordered_cases, short_cases, refused_cases, updated_utc, @run_id
    FROM #stop n WHERE NOT EXISTS (SELECT 1 FROM silver.stop s WHERE s.stop_id = n.stop_id);

    -- Geofence visits (telematics, UTC). Local time uses the time zone of the truck's home branch.
    WITH n AS (SELECT payload, updated_utc,
                      ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY updated_utc DESC, loaded_utc DESC) AS rn
               FROM landing.api_record WHERE entity = 'tel_visit' AND run_id = @run_id)
    SELECT j.visit_id, j.truck_code, j.customer_number,
           CAST(j.entered AS datetime2(0)) AS entered_utc, CAST(j.exited AS datetime2(0)) AS exited_utc,
           CAST(j.entered AT TIME ZONE ISNULL(b.time_zone, 'UTC') AS datetime2(0)) AS entered_local,
           CAST(j.exited AT TIME ZONE ISNULL(b.time_zone, 'UTC') AS datetime2(0)) AS exited_local,
           n.updated_utc
    INTO #visit
    FROM n CROSS APPLY OPENJSON(n.payload) WITH (
        visit_id varchar(36) '$.id', truck_code varchar(8) '$.truck_code',
        customer_number varchar(12) '$.customer_number', entered datetimeoffset(0) '$.entered_at',
        exited datetimeoffset(0) '$.exited_at') j
    LEFT JOIN silver.truck t ON t.truck_code = j.truck_code
    LEFT JOIN silver.branch b ON b.branch_code = t.branch_code
    WHERE n.rn = 1;
    DELETE s FROM silver.visit s JOIN #visit n ON n.visit_id = s.visit_id WHERE n.updated_utc >= s.updated_utc;
    INSERT silver.visit (visit_id, truck_code, customer_number, entered_utc, exited_utc, entered_local, exited_local,
                         visit_date, updated_utc, run_id)
    SELECT visit_id, truck_code, customer_number, entered_utc, exited_utc, entered_local, exited_local,
           CAST(entered_local AS date), updated_utc, @run_id
    FROM #visit n WHERE NOT EXISTS (SELECT 1 FROM silver.visit s WHERE s.visit_id = n.visit_id);

    -- Trips (telematics, UTC; trip_date is already the local operating date).
    WITH n AS (SELECT payload, updated_utc,
                      ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY updated_utc DESC, loaded_utc DESC) AS rn
               FROM landing.api_record WHERE entity = 'tel_trip' AND run_id = @run_id)
    SELECT j.trip_id, j.truck_code, j.trip_date, CAST(j.started AS datetime2(0)) AS started_utc,
           CAST(j.ended AS datetime2(0)) AS ended_utc, j.miles, j.idle_minutes, n.updated_utc
    INTO #trip
    FROM n CROSS APPLY OPENJSON(n.payload) WITH (
        trip_id varchar(36) '$.id', truck_code varchar(8) '$.truck_code', trip_date date '$.trip_date',
        started datetimeoffset(0) '$.started_at', ended datetimeoffset(0) '$.ended_at', miles decimal(7,1) '$.miles',
        idle_minutes int '$.idle_minutes') j
    WHERE n.rn = 1;
    DELETE s FROM silver.trip s JOIN #trip n ON n.trip_id = s.trip_id WHERE n.updated_utc >= s.updated_utc;
    INSERT silver.trip (trip_id, truck_code, trip_date, started_utc, ended_utc, miles, idle_minutes, updated_utc, run_id)
    SELECT trip_id, truck_code, trip_date, started_utc, ended_utc, miles, idle_minutes, updated_utc, @run_id
    FROM #trip n WHERE NOT EXISTS (SELECT 1 FROM silver.trip s WHERE s.trip_id = n.trip_id);
END;
GO

CREATE OR ALTER PROCEDURE silver.load_fuel @run_id int
AS
BEGIN
    SET NOCOUNT ON;
    SELECT file_name, line_no, card_number, truck_code, TRY_CAST(txn_time_local AS datetime2(0)) AS txn_local,
           site_name, TRY_CAST(gallons AS decimal(8,1)) AS gallons,
           TRY_CAST(price_per_gallon AS decimal(6,3)) AS price_per_gallon, TRY_CAST(amount AS decimal(10,2)) AS amount
    INTO #fuel
    FROM landing.fuel_txn WHERE run_id = @run_id;
    DELETE s FROM silver.fuel_txn s JOIN #fuel n ON n.file_name = s.file_name AND n.line_no = s.line_no;
    INSERT silver.fuel_txn (file_name, line_no, card_number, truck_code, txn_local, txn_date, site_name, gallons,
                            price_per_gallon, amount, run_id)
    SELECT file_name, line_no, card_number, truck_code, txn_local, CAST(txn_local AS date), site_name, gallons,
           price_per_gallon, amount, @run_id
    FROM #fuel
    WHERE txn_local IS NOT NULL AND gallons IS NOT NULL AND amount IS NOT NULL;
END;
GO

-- Every operating date touched by this run. Gold rebuilds exactly these dates, the way the model's
-- incremental refresh only reprocesses its most recent partitions.
CREATE OR ALTER PROCEDURE silver.collect_affected_dates @run_id int
AS
BEGIN
    SET NOCOUNT ON;
    INSERT meta.affected_date (run_id, d)
    SELECT DISTINCT @run_id, x.d FROM (
        SELECT route_date AS d FROM silver.stop WHERE run_id = @run_id
        UNION SELECT route_date FROM silver.route_plan WHERE run_id = @run_id
        UNION SELECT visit_date FROM silver.visit WHERE run_id = @run_id
        UNION SELECT trip_date FROM silver.trip WHERE run_id = @run_id
        UNION SELECT posting_date FROM silver.invoice_line WHERE run_id = @run_id
        UNION SELECT service_date FROM silver.sales_order WHERE run_id = @run_id
        UNION SELECT txn_date FROM silver.fuel_txn WHERE run_id = @run_id
    ) x
    WHERE NOT EXISTS (SELECT 1 FROM meta.affected_date a WHERE a.run_id = @run_id AND a.d = x.d);
END;
GO
