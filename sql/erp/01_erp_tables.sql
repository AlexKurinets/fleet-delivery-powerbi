-- Synthetic ERP source database (stands in for the on-prem ERP behind the data gateway).
-- Every table carries a rowversion so the warehouse can extract changes by watermark.

IF OBJECT_ID('dbo.branch') IS NULL
CREATE TABLE dbo.branch (
    branch_code   varchar(8)   NOT NULL PRIMARY KEY,
    branch_name   nvarchar(60) NOT NULL,
    region        varchar(20)  NOT NULL,
    time_zone     varchar(40)  NOT NULL,
    rv            rowversion
);
GO
IF OBJECT_ID('dbo.category') IS NULL
CREATE TABLE dbo.category (
    category_code varchar(8)   NOT NULL PRIMARY KEY,
    category_name nvarchar(40) NOT NULL,
    temp_zone     varchar(10)  NOT NULL,
    rv            rowversion
);
GO
IF OBJECT_ID('dbo.truck') IS NULL
CREATE TABLE dbo.truck (
    truck_code    varchar(8)  NOT NULL PRIMARY KEY,
    branch_code   varchar(8)  NOT NULL,
    model_year    int         NOT NULL,
    reefer_type   varchar(20) NOT NULL,
    rv            rowversion
);
GO
IF OBJECT_ID('dbo.driver') IS NULL
CREATE TABLE dbo.driver (
    driver_code   varchar(8)   NOT NULL PRIMARY KEY,
    driver_name   nvarchar(60) NOT NULL,
    branch_code   varchar(8)   NOT NULL,
    hourly_rate   decimal(6,2) NOT NULL,
    rv            rowversion
);
GO
IF OBJECT_ID('dbo.customer') IS NULL
CREATE TABLE dbo.customer (
    customer_number varchar(12)  NOT NULL PRIMARY KEY,
    customer_name   nvarchar(80) NOT NULL,
    segment         varchar(20)  NOT NULL,
    branch_code     varchar(8)   NOT NULL,
    rv              rowversion
);
GO
IF OBJECT_ID('dbo.customer_branch_history') IS NULL
CREATE TABLE dbo.customer_branch_history (
    customer_number varchar(12) NOT NULL,
    effective_from  date        NOT NULL,
    branch_code     varchar(8)  NOT NULL,
    segment         varchar(20) NOT NULL,
    rv              rowversion,
    PRIMARY KEY (customer_number, effective_from)
);
GO
IF OBJECT_ID('dbo.sales_order') IS NULL
CREATE TABLE dbo.sales_order (
    order_number    varchar(16) NOT NULL PRIMARY KEY,
    customer_number varchar(12) NOT NULL,
    service_date    date        NOT NULL,
    tms_stop_id     varchar(36) NULL,
    order_type      varchar(10) NOT NULL,
    rv              rowversion
);
GO
IF OBJECT_ID('dbo.invoice_line') IS NULL
CREATE TABLE dbo.invoice_line (
    invoice_number          varchar(16)   NOT NULL,
    line_no                 int           NOT NULL,
    order_number            varchar(16)   NOT NULL,
    customer_number         varchar(12)   NOT NULL,
    posting_date            date          NOT NULL,
    category_code           varchar(8)    NOT NULL,
    cases                   int           NOT NULL,
    revenue                 decimal(12,2) NOT NULL,
    cost                    decimal(12,2) NOT NULL,
    original_invoice_number varchar(16)   NULL,
    rv                      rowversion,
    PRIMARY KEY (invoice_number, line_no)
);
GO
