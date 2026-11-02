-- Warehouse tables. landing = raw copies (the Lakehouse in production), silver = typed and deduplicated,
-- gold = the star schema the semantic model imports, dq = data-quality results, meta = run bookkeeping.

IF SCHEMA_ID('landing') IS NULL EXEC('CREATE SCHEMA landing');
IF SCHEMA_ID('silver') IS NULL EXEC('CREATE SCHEMA silver');
IF SCHEMA_ID('gold') IS NULL EXEC('CREATE SCHEMA gold');
IF SCHEMA_ID('dq') IS NULL EXEC('CREATE SCHEMA dq');
IF SCHEMA_ID('meta') IS NULL EXEC('CREATE SCHEMA meta');
IF SCHEMA_ID('sec') IS NULL EXEC('CREATE SCHEMA sec');
IF SCHEMA_ID('rpt') IS NULL EXEC('CREATE SCHEMA rpt');
GO

------------------------------------------------------------------------------------------------ meta
IF OBJECT_ID('meta.run') IS NULL
CREATE TABLE meta.run (
    run_id           int           NOT NULL PRIMARY KEY,
    started_utc      datetime2(0)  NOT NULL,
    finished_utc     datetime2(0)  NULL,
    source_clock_utc datetime2(0)  NOT NULL,
    status           varchar(12)   NOT NULL,   -- running, succeeded, blocked, failed
    refresh_status   varchar(20)   NULL,       -- triggered, skipped, not configured
    message          nvarchar(400) NULL
);
IF OBJECT_ID('meta.watermark') IS NULL
CREATE TABLE meta.watermark (
    source      varchar(40)  NOT NULL PRIMARY KEY,
    value       varchar(40)  NOT NULL,
    updated_utc datetime2(0) NOT NULL
);
IF OBJECT_ID('meta.source_load') IS NULL
CREATE TABLE meta.source_load (
    run_id         int         NOT NULL,
    source         varchar(40) NOT NULL,
    rows_landed    int         NOT NULL,
    watermark_from varchar(40) NULL,
    watermark_to   varchar(40) NULL,
    PRIMARY KEY (run_id, source)
);
IF OBJECT_ID('meta.file_log') IS NULL
CREATE TABLE meta.file_log (
    file_name   varchar(80)  NOT NULL PRIMARY KEY,
    sha256      char(64)     NOT NULL,
    rows_landed int          NOT NULL,
    run_id      int          NOT NULL,
    loaded_utc  datetime2(0) NOT NULL DEFAULT SYSUTCDATETIME()
);
IF OBJECT_ID('meta.affected_date') IS NULL
CREATE TABLE meta.affected_date (
    run_id int  NOT NULL,
    d      date NOT NULL,
    PRIMARY KEY (run_id, d)
);
GO

------------------------------------------------------------------------------------------------ landing
IF OBJECT_ID('landing.erp_branch') IS NULL
CREATE TABLE landing.erp_branch (branch_code varchar(8), branch_name nvarchar(60), region varchar(20),
    time_zone varchar(40), rv bigint, run_id int, loaded_utc datetime2(0) DEFAULT SYSUTCDATETIME());
IF OBJECT_ID('landing.erp_category') IS NULL
CREATE TABLE landing.erp_category (category_code varchar(8), category_name nvarchar(40), temp_zone varchar(10),
    rv bigint, run_id int, loaded_utc datetime2(0) DEFAULT SYSUTCDATETIME());
IF OBJECT_ID('landing.erp_truck') IS NULL
CREATE TABLE landing.erp_truck (truck_code varchar(8), branch_code varchar(8), model_year int, reefer_type varchar(20),
    rv bigint, run_id int, loaded_utc datetime2(0) DEFAULT SYSUTCDATETIME());
IF OBJECT_ID('landing.erp_driver') IS NULL
CREATE TABLE landing.erp_driver (driver_code varchar(8), driver_name nvarchar(60), branch_code varchar(8),
    hourly_rate decimal(6,2), rv bigint, run_id int, loaded_utc datetime2(0) DEFAULT SYSUTCDATETIME());
IF OBJECT_ID('landing.erp_customer') IS NULL
CREATE TABLE landing.erp_customer (customer_number varchar(12), customer_name nvarchar(80), segment varchar(20),
    branch_code varchar(8), rv bigint, run_id int, loaded_utc datetime2(0) DEFAULT SYSUTCDATETIME());
IF OBJECT_ID('landing.erp_customer_branch_history') IS NULL
CREATE TABLE landing.erp_customer_branch_history (customer_number varchar(12), effective_from date,
    branch_code varchar(8), segment varchar(20), rv bigint, run_id int, loaded_utc datetime2(0) DEFAULT SYSUTCDATETIME());
IF OBJECT_ID('landing.erp_sales_order') IS NULL
CREATE TABLE landing.erp_sales_order (order_number varchar(16), customer_number varchar(12), service_date date,
    tms_stop_id varchar(36), order_type varchar(10), rv bigint, run_id int, loaded_utc datetime2(0) DEFAULT SYSUTCDATETIME());
IF OBJECT_ID('landing.erp_invoice_line') IS NULL
CREATE TABLE landing.erp_invoice_line (invoice_number varchar(16), line_no int, order_number varchar(16),
    customer_number varchar(12), posting_date date, category_code varchar(8), cases int, revenue decimal(12,2),
    cost decimal(12,2), original_invoice_number varchar(16), rv bigint, run_id int,
    loaded_utc datetime2(0) DEFAULT SYSUTCDATETIME());

-- API records are kept exactly as the API returned them, so any load can be replayed.
IF OBJECT_ID('landing.api_record') IS NULL
CREATE TABLE landing.api_record (
    entity      varchar(30)   NOT NULL,   -- tms_stop, tms_route_plan, tel_visit, tel_trip
    record_id   varchar(36)   NOT NULL,
    updated_utc datetime2(0)  NOT NULL,
    payload     nvarchar(max) NOT NULL,
    run_id      int           NOT NULL,
    loaded_utc  datetime2(0)  NOT NULL DEFAULT SYSUTCDATETIME()
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_api_record_run')
CREATE INDEX ix_api_record_run ON landing.api_record (entity, run_id) INCLUDE (record_id, updated_utc);

IF OBJECT_ID('landing.fuel_txn') IS NULL
CREATE TABLE landing.fuel_txn (file_name varchar(80), line_no int, card_number varchar(20), truck_code varchar(8),
    txn_time_local varchar(19), site_name nvarchar(60), gallons varchar(12), price_per_gallon varchar(12),
    amount varchar(12), run_id int, loaded_utc datetime2(0) DEFAULT SYSUTCDATETIME());
GO

------------------------------------------------------------------------------------------------ silver
IF OBJECT_ID('silver.branch') IS NULL
CREATE TABLE silver.branch (branch_code varchar(8) NOT NULL PRIMARY KEY, branch_name nvarchar(60) NOT NULL,
    region varchar(20) NOT NULL, time_zone varchar(40) NOT NULL, run_id int NOT NULL);
IF OBJECT_ID('silver.category') IS NULL
CREATE TABLE silver.category (category_code varchar(8) NOT NULL PRIMARY KEY, category_name nvarchar(40) NOT NULL,
    temp_zone varchar(10) NOT NULL, run_id int NOT NULL);
IF OBJECT_ID('silver.truck') IS NULL
CREATE TABLE silver.truck (truck_code varchar(8) NOT NULL PRIMARY KEY, branch_code varchar(8) NOT NULL,
    model_year int NOT NULL, reefer_type varchar(20) NOT NULL, run_id int NOT NULL);
IF OBJECT_ID('silver.driver') IS NULL
CREATE TABLE silver.driver (driver_code varchar(8) NOT NULL PRIMARY KEY, driver_name nvarchar(60) NOT NULL,
    branch_code varchar(8) NOT NULL, hourly_rate decimal(6,2) NOT NULL, run_id int NOT NULL);
IF OBJECT_ID('silver.customer') IS NULL
CREATE TABLE silver.customer (customer_number varchar(12) NOT NULL PRIMARY KEY, customer_name nvarchar(80) NOT NULL,
    segment varchar(20) NOT NULL, branch_code varchar(8) NOT NULL, run_id int NOT NULL);
IF OBJECT_ID('silver.customer_branch') IS NULL
CREATE TABLE silver.customer_branch (customer_number varchar(12) NOT NULL, effective_from date NOT NULL,
    branch_code varchar(8) NOT NULL, segment varchar(20) NOT NULL, run_id int NOT NULL,
    PRIMARY KEY (customer_number, effective_from));
IF OBJECT_ID('silver.sales_order') IS NULL
CREATE TABLE silver.sales_order (order_number varchar(16) NOT NULL PRIMARY KEY, customer_number varchar(12) NOT NULL,
    service_date date NOT NULL, tms_stop_id varchar(36) NULL, order_type varchar(10) NOT NULL, run_id int NOT NULL);
IF OBJECT_ID('silver.invoice_line') IS NULL
CREATE TABLE silver.invoice_line (invoice_number varchar(16) NOT NULL, line_no int NOT NULL,
    order_number varchar(16) NOT NULL, customer_number varchar(12) NOT NULL, posting_date date NOT NULL,
    category_code varchar(8) NOT NULL, cases int NOT NULL, revenue decimal(12,2) NOT NULL, cost decimal(12,2) NOT NULL,
    original_invoice_number varchar(16) NULL, is_credit bit NOT NULL, run_id int NOT NULL,
    PRIMARY KEY (invoice_number, line_no));
IF OBJECT_ID('silver.route_plan') IS NULL
CREATE TABLE silver.route_plan (route_plan_id varchar(36) NOT NULL PRIMARY KEY, route_code varchar(12) NOT NULL,
    route_name nvarchar(60) NOT NULL, branch_code varchar(8) NOT NULL, route_date date NOT NULL,
    truck_code varchar(8) NOT NULL, driver_code varchar(8) NOT NULL, dispatch_local datetime2(0) NOT NULL,
    planned_miles decimal(7,1) NOT NULL, planned_stops int NOT NULL, updated_utc datetime2(0) NOT NULL,
    run_id int NOT NULL);
IF OBJECT_ID('silver.stop') IS NULL
CREATE TABLE silver.stop (stop_id varchar(36) NOT NULL PRIMARY KEY, route_plan_id varchar(36) NOT NULL,
    route_code varchar(12) NOT NULL, route_date date NOT NULL, branch_code varchar(8) NOT NULL,
    truck_code varchar(8) NOT NULL, driver_code varchar(8) NOT NULL, stop_sequence int NOT NULL,
    customer_number varchar(12) NOT NULL, order_number varchar(16) NULL, status varchar(12) NOT NULL,
    window_start_local datetime2(0) NOT NULL, window_end_local datetime2(0) NOT NULL,
    delivered_local datetime2(0) NULL, delivered_recorded_utc datetime2(0) NULL,
    ordered_cases int NOT NULL, short_cases int NOT NULL, refused_cases int NOT NULL,
    updated_utc datetime2(0) NOT NULL, run_id int NOT NULL);
IF OBJECT_ID('silver.visit') IS NULL
CREATE TABLE silver.visit (visit_id varchar(36) NOT NULL PRIMARY KEY, truck_code varchar(8) NOT NULL,
    customer_number varchar(12) NOT NULL, entered_utc datetime2(0) NOT NULL, exited_utc datetime2(0) NOT NULL,
    entered_local datetime2(0) NOT NULL, exited_local datetime2(0) NOT NULL, visit_date date NOT NULL,
    updated_utc datetime2(0) NOT NULL, run_id int NOT NULL);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_visit_match')
CREATE INDEX ix_visit_match ON silver.visit (truck_code, customer_number, visit_date) INCLUDE (entered_utc, entered_local, exited_local, exited_utc);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_stop_date')
CREATE INDEX ix_stop_date ON silver.stop (route_date) INCLUDE (status, customer_number, truck_code);
IF OBJECT_ID('silver.trip') IS NULL
CREATE TABLE silver.trip (trip_id varchar(36) NOT NULL PRIMARY KEY, truck_code varchar(8) NOT NULL,
    trip_date date NOT NULL, started_utc datetime2(0) NOT NULL, ended_utc datetime2(0) NOT NULL,
    miles decimal(7,1) NOT NULL, idle_minutes int NOT NULL, updated_utc datetime2(0) NOT NULL, run_id int NOT NULL);
IF OBJECT_ID('silver.fuel_txn') IS NULL
CREATE TABLE silver.fuel_txn (file_name varchar(80) NOT NULL, line_no int NOT NULL, card_number varchar(20) NOT NULL,
    truck_code varchar(8) NOT NULL, txn_local datetime2(0) NOT NULL, txn_date date NOT NULL,
    site_name nvarchar(60) NOT NULL, gallons decimal(8,1) NOT NULL, price_per_gallon decimal(6,3) NOT NULL,
    amount decimal(10,2) NOT NULL, run_id int NOT NULL, PRIMARY KEY (file_name, line_no));
GO

------------------------------------------------------------------------------------------------ gold
IF OBJECT_ID('gold.dim_date') IS NULL
CREATE TABLE gold.dim_date (date_key int NOT NULL PRIMARY KEY, [date] date NOT NULL, [year] int NOT NULL,
    quarter_label varchar(7) NOT NULL, month_number int NOT NULL, month_name varchar(9) NOT NULL,
    month_start date NOT NULL, year_month varchar(7) NOT NULL, iso_week int NOT NULL, weekday_number int NOT NULL,
    weekday_name varchar(9) NOT NULL, is_operating_day bit NOT NULL);
IF OBJECT_ID('gold.dim_branch') IS NULL
CREATE TABLE gold.dim_branch (branch_key int NOT NULL PRIMARY KEY, branch_code varchar(8) NOT NULL,
    branch_name nvarchar(60) NOT NULL, region varchar(20) NOT NULL, time_zone varchar(40) NOT NULL);
IF OBJECT_ID('gold.dim_category') IS NULL
CREATE TABLE gold.dim_category (category_key int NOT NULL PRIMARY KEY, category_code varchar(8) NOT NULL,
    category_name nvarchar(40) NOT NULL, temp_zone varchar(10) NOT NULL);
IF OBJECT_ID('gold.dim_truck') IS NULL
CREATE TABLE gold.dim_truck (truck_key int NOT NULL PRIMARY KEY, truck_code varchar(8) NOT NULL,
    home_branch nvarchar(60) NOT NULL, model_year int NULL, reefer_type varchar(20) NOT NULL);
IF OBJECT_ID('gold.dim_driver') IS NULL
CREATE TABLE gold.dim_driver (driver_key int NOT NULL PRIMARY KEY, driver_code varchar(8) NOT NULL,
    driver_name nvarchar(60) NOT NULL, home_branch nvarchar(60) NOT NULL);
IF OBJECT_ID('gold.dim_route') IS NULL
CREATE TABLE gold.dim_route (route_key int NOT NULL PRIMARY KEY, route_code varchar(12) NOT NULL,
    route_name nvarchar(60) NOT NULL, route_branch nvarchar(60) NOT NULL);
-- Type 2: one row per customer and branch assignment, so history stays with the branch that served it.
IF OBJECT_ID('gold.dim_customer') IS NULL
CREATE TABLE gold.dim_customer (customer_key int NOT NULL PRIMARY KEY, customer_number varchar(12) NOT NULL,
    customer_name nvarchar(80) NOT NULL, segment varchar(20) NOT NULL, customer_branch nvarchar(60) NOT NULL,
    branch_code varchar(8) NOT NULL, valid_from date NOT NULL, valid_to date NOT NULL, is_current bit NOT NULL,
    changed_run_id int NOT NULL);

IF OBJECT_ID('gold.fact_delivery_stop') IS NULL
CREATE TABLE gold.fact_delivery_stop (
    stop_id            varchar(36) NOT NULL PRIMARY KEY,  -- TMS GUID: stays in the warehouse, not imported
    service_date       date        NOT NULL,              -- incremental refresh filter, not imported
    service_date_key   int         NOT NULL,
    branch_key         int         NOT NULL,
    route_key          int         NOT NULL,
    customer_key       int         NOT NULL,
    driver_key         int         NOT NULL,
    truck_key          int         NOT NULL,
    stop_sequence      smallint    NOT NULL,
    window_start_minute smallint   NOT NULL,
    window_end_minute  smallint    NOT NULL,
    arrival_minute     smallint    NULL,
    arrival_source     varchar(10) NOT NULL,              -- Geofence, TMS, None
    minutes_late       int         NOT NULL,
    is_on_time         tinyint     NOT NULL,
    is_on_time_tms     tinyint     NOT NULL,
    is_in_full         tinyint     NOT NULL,
    is_otif            tinyint     NOT NULL,
    has_geofence       tinyint     NOT NULL,
    is_backfilled      tinyint     NOT NULL,
    ordered_cases      int         NOT NULL,
    short_cases        int         NOT NULL,
    refused_cases      int         NOT NULL,
    delivered_cases    int         NOT NULL,
    dwell_minutes      smallint    NULL,
    run_id             int         NOT NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_fact_stop_date')
CREATE INDEX ix_fact_stop_date ON gold.fact_delivery_stop (service_date);

IF OBJECT_ID('gold.fact_invoice_line') IS NULL
CREATE TABLE gold.fact_invoice_line (
    invoice_number   varchar(16)   NOT NULL,
    line_no          int           NOT NULL,
    posting_date     date          NOT NULL,
    posting_date_key int           NOT NULL,
    branch_key       int           NOT NULL,
    customer_key     int           NOT NULL,
    category_key     int           NOT NULL,
    route_key        int           NOT NULL,
    order_type       varchar(10)   NOT NULL,
    is_credit        tinyint       NOT NULL,
    cases            int           NOT NULL,
    revenue          decimal(12,2) NOT NULL,
    cost             decimal(12,2) NOT NULL,
    run_id           int           NOT NULL,
    PRIMARY KEY (invoice_number, line_no)
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_fact_invoice_date')
CREATE INDEX ix_fact_invoice_date ON gold.fact_invoice_line (posting_date);

IF OBJECT_ID('gold.fact_route_trip') IS NULL
CREATE TABLE gold.fact_route_trip (
    route_plan_id    varchar(36)   NOT NULL PRIMARY KEY,
    service_date     date          NOT NULL,
    service_date_key int           NOT NULL,
    branch_key       int           NOT NULL,
    route_key        int           NOT NULL,
    truck_key        int           NOT NULL,
    driver_key       int           NOT NULL,
    planned_stops    int           NOT NULL,
    completed_stops  int           NOT NULL,
    planned_miles    decimal(7,1)  NOT NULL,
    driven_miles     decimal(7,1)  NULL,
    driver_hours     decimal(6,2)  NULL,
    labor_cost       decimal(10,2) NULL,
    run_id           int           NOT NULL
);

IF OBJECT_ID('gold.fact_fuel') IS NULL
CREATE TABLE gold.fact_fuel (
    file_name        varchar(80)   NOT NULL,
    line_no          int           NOT NULL,
    txn_date         date          NOT NULL,
    txn_date_key     int           NOT NULL,
    branch_key       int           NOT NULL,
    truck_key        int           NOT NULL,
    gallons          decimal(8,1)  NOT NULL,
    fuel_cost        decimal(10,2) NOT NULL,
    is_on_route_day  tinyint       NOT NULL,
    run_id           int           NOT NULL,
    PRIMARY KEY (file_name, line_no)
);
GO

------------------------------------------------------------------------------------------------ dq and sec
IF OBJECT_ID('dq.rule_def') IS NULL
CREATE TABLE dq.rule_def (
    rule_code       varchar(40)   NOT NULL PRIMARY KEY,
    description     nvarchar(200) NOT NULL,
    severity        varchar(8)    NOT NULL,   -- warn: shown and alerted; block: stops the model refresh
    threshold       decimal(9,4)  NOT NULL,   -- per branch and day (a share, or hours for freshness)
    block_threshold decimal(9,4)  NULL        -- across the whole run, block rules only
);
IF OBJECT_ID('dq.result') IS NULL
CREATE TABLE dq.result (
    rule_code      varchar(40)  NOT NULL,
    subject        varchar(40)  NOT NULL,   -- the API source for SOURCE_STALE, empty for branch-level rules
    branch_key     int          NOT NULL,
    check_date     date         NOT NULL,
    check_date_key int          NOT NULL,
    checked_rows   int          NOT NULL,
    failed_rows    int          NOT NULL,
    measured_value decimal(9,4) NOT NULL,
    threshold      decimal(9,4) NOT NULL,
    breached       tinyint      NOT NULL,
    run_id         int          NOT NULL,
    PRIMARY KEY (rule_code, subject, branch_key, check_date)
);
IF OBJECT_ID('dq.run_summary') IS NULL
CREATE TABLE dq.run_summary (
    run_id         int          NOT NULL,
    rule_code      varchar(40)  NOT NULL,
    severity       varchar(8)   NOT NULL,
    checked_rows   int          NOT NULL,
    failed_rows    int          NOT NULL,
    breaches       int          NOT NULL,
    blocks_refresh tinyint      NOT NULL,
    PRIMARY KEY (run_id, rule_code)
);
IF OBJECT_ID('dq.quarantine') IS NULL
CREATE TABLE dq.quarantine (
    rule_code   varchar(40)   NOT NULL,
    record_id   varchar(36)   NOT NULL,
    record_date date          NOT NULL,
    branch_code varchar(8)    NOT NULL,
    detail      nvarchar(400) NOT NULL,
    run_id      int           NOT NULL,
    PRIMARY KEY (rule_code, record_id)
);
IF OBJECT_ID('sec.user_branch') IS NULL
CREATE TABLE sec.user_branch (
    user_principal_name nvarchar(120) NOT NULL,
    branch_code         varchar(8)    NOT NULL,
    PRIMARY KEY (user_principal_name, branch_code)
);
GO

-- Rule definitions are reference data; reinsert them on every init so threshold edits in this file apply.
DELETE FROM dq.rule_def;
INSERT dq.rule_def (rule_code, description, severity, threshold, block_threshold) VALUES
 ('GEOFENCE_MISSING', N'Stops with no telematics geofence arrival, scored on the driver-entered TMS time instead (trailing 7 days)', 'warn', 0.05, NULL),
 ('TMS_BACKFILLED', N'TMS delivered time recorded more than 60 minutes after the truck left the geofence (trailing 7 days)', 'warn', 0.20, NULL),
 ('ARRIVAL_BEFORE_DISPATCH', N'Geofence arrival earlier than the route dispatch; the stop is quarantined', 'block', 0.05, 0.02),
 ('ORDER_WITHOUT_STOP', N'Delivery orders in the ERP whose TMS stop is missing (trailing 7 days)', 'warn', 0.02, NULL),
 ('FUEL_OFF_ROUTE', N'Fuel card transactions for a truck that was not on a route that day', 'warn', 0.0, NULL),
 ('SOURCE_STALE', N'Hours since the newest record from an API source', 'warn', 30.0, NULL);
GO
