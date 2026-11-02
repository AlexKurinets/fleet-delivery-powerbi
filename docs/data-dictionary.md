# Data dictionary

Generated from the semantic model by `fleetbi model docs` (from `build/model.bim`, which `tools/TmdlCheck` compiles from the TMDL). Do not edit by hand; CI fails if it is out of date.

## Tables

| Table | Source | Description |
| --- | --- | --- |
| Branch | `gold.dim_branch` | Delivering branch. Row-level security filters this table. |
| Customer | `gold.dim_customer` | Customer, Type 2 on branch assignment: one row per customer and branch period. |
| Data Quality | `rpt.dq_result` | Latest result of each data-quality rule per branch and day (and per API source for freshness). |
| Date | `gold.dim_date` | Calendar from 2024 to 2027, marked as the model's date table. Facts relate on Date Key. |
| Delivery Stop | `gold.fact_delivery_stop` | One completed delivery stop. Incremental refresh: three years kept, last ten days refreshed. |
| Driver | `gold.dim_driver` | Driver. |
| Fuel | `gold.fact_fuel` | One fuel card transaction. |
| Invoice Line | `gold.fact_invoice_line` | One invoice or credit line, at its posting date. Incremental refresh: three years kept, last ten days refreshed. |
| Pipeline Run | `rpt.pipeline_run` | Pipeline runs, their status and whether the model refresh was triggered. |
| Product Category | `gold.dim_category` | Product category and its temperature zone. |
| Route Trip | `gold.fact_route_trip` | One truck on one route and day, with telematics miles and driver hours. |
| Route | `gold.dim_route` | Delivery route. Not related to Branch, so there is one filter path from Branch to each fact. |
| Security Branch Access (hidden) | `sec.user_branch_access` | User to branch mapping for the Branch Manager role, maintained by IT. |
| Time Calc | calculation group | Time intelligence applied to any measure: current, month to date, year to date, prior year, year over year. |
| Truck | `gold.dim_truck` | Refrigerated truck. |

## Branch

Delivering branch. Row-level security filters this table.

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Branch Key | int64 | `branch_key` | no |  |
| Branch Code | string | `branch_code` | yes |  |
| Branch | string | `branch_name` | yes |  |
| Region | string | `region` | yes |  |
| Time Zone | string | `time_zone` | yes |  |

## Customer

Customer, Type 2 on branch assignment: one row per customer and branch period.

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Customer Key | int64 | `customer_key` | no |  |
| Customer Number | string | `customer_number` | yes |  |
| Customer | string | `customer_name` | yes |  |
| Segment | string | `segment` | yes |  |
| Customer Branch | string | `customer_branch` | yes | Branch that served the customer in this version's period |
| Valid From | dateTime | `valid_from` | yes |  |
| Valid To | dateTime | `valid_to` | yes |  |
| Is Current | boolean | `is_current` | yes |  |

## Data Quality

Latest result of each data-quality rule per branch and day (and per API source for freshness).

| Measure | Folder | Format | Description | DAX |
| --- | --- | --- | --- | --- |
| Rule Breaches | Data Health | `#,0` | Branch-days (or sources) where a rule exceeded its threshold | `CALCULATE ( COUNTROWS ( 'Data Quality' ), 'Data Quality'[Breached] = 1 )` |
| Rule Failed % | Data Health | `0.0%` | Failed rows as a share of checked rows; trailing-window rules are averaged over the selected days | `DIVIDE ( SUM ( 'Data Quality'[Failed Rows] ), SUM ( 'Data Quality'[Checked Rows] ) )` |
| Worst Day % | Data Health | `0.0%` | Highest measured share on any selected branch-day | `MAX ( 'Data Quality'[Measured Value] )` |

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Rule Code | string | `rule_code` | yes |  |
| Rule | string | `description` | yes |  |
| Severity | string | `severity` | yes |  |
| Subject | string | `subject` | yes | API source for the freshness rule, blank for branch rules |
| Branch Key | int64 | `branch_key` | no |  |
| Check Date Key | int64 | `check_date_key` | no |  |
| Checked Rows | int64 | `checked_rows` | no |  |
| Failed Rows | int64 | `failed_rows` | no |  |
| Measured Value | double | `measured_value` | no |  |
| Threshold | double | `threshold` | no |  |
| Breached | int64 | `breached` | no |  |

## Date

Calendar from 2024 to 2027, marked as the model's date table. Facts relate on Date Key.

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Date Key | int64 | `date_key` | no |  |
| Date | dateTime | `date` | yes |  |
| Year | int64 | `year` | yes |  |
| Quarter | string | `quarter_label` | yes |  |
| Month Number | int64 | `month_number` | no |  |
| Month | string | `month_name` | yes |  |
| Month Start | dateTime | `month_start` | yes |  |
| Year Month | string | `year_month` | yes |  |
| ISO Week | int64 | `iso_week` | yes |  |
| Weekday Number | int64 | `weekday_number` | no |  |
| Weekday | string | `weekday_name` | yes |  |
| Is Operating Day | boolean | `is_operating_day` | yes |  |

## Delivery Stop

One completed delivery stop. Incremental refresh: three years kept, last ten days refreshed.

Incremental refresh: keep 3 years, refresh the last 10 days.

| Measure | Folder | Format | Description | DAX |
| --- | --- | --- | --- | --- |
| Backfilled Entry % | Data Health | `0.0%` | Share of geofenced stops whose TMS delivered time was typed in more than 60 minutes after the truck left | `DIVIDE ( SUM ( 'Delivery Stop'[Is Backfilled] ), SUM ( 'Delivery Stop'[Has Geofence] ) )` |
| Geofence Coverage % | Data Health | `0.0%` | Share of stops scored on a telematics geofence arrival | `DIVIDE ( SUM ( 'Delivery Stop'[Has Geofence] ), [Stops] )` |
| On-Time % (TMS Time) | Data Health | `0.0%` | On-time scored on the driver-entered TMS time, kept only to show how far it overstates | `DIVIDE ( SUM ( 'Delivery Stop'[Is On Time TMS] ), [Stops] )` |
| TMS On-Time Overstatement | Data Health | `0.0%` | Percentage points by which the driver-entered time overstates on-time delivery | `[On-Time % (TMS Time)] - [On-Time %]` |
| Avg Dwell Minutes | Delivery | `#,0.0` | Average minutes inside the customer geofence | `AVERAGE ( 'Delivery Stop'[Dwell Minutes] )` |
| Avg Minutes Late | Delivery | `#,0` | Average minutes past the window end, late stops only | `CALCULATE ( AVERAGE ( 'Delivery Stop'[Minutes Late] ), 'Delivery Stop'[Minutes Late] > 0 )` |
| In-Full % | Delivery | `0.0%` | Share of stops with no short or refused cases, as recorded at the stop | `DIVIDE ( SUM ( 'Delivery Stop'[Is In Full] ), [Stops] )` |
| Late Stops | Delivery | `#,0` | Stops that arrived after the window closed | `[Stops] - [On-Time Stops]` |
| OTIF % | Delivery | `0.0%` | Share of stops that were both on time and in full | `DIVIDE ( SUM ( 'Delivery Stop'[Is OTIF] ), [Stops] )` |
| On-Time % | Delivery | `0.0%` | Share of stops that arrived by the end of the window, on the geofence arrival (TMS time only as a flagged fallback) | `DIVIDE ( [On-Time Stops], [Stops] )` |
| On-Time Stops | Delivery | `#,0` | Stops whose arrival was at or before the end of the delivery window | `SUM ( 'Delivery Stop'[Is On Time] )` |
| Stops | Delivery | `#,0` | Completed delivery stops (quarantined stops excluded) | `COUNTROWS ( 'Delivery Stop' )` |
| Delivered Cases | Delivery\Cases | `#,0` | Ordered cases less short and refused cases | `SUM ( 'Delivery Stop'[Delivered Cases] )` |
| Fill Rate % | Delivery\Cases | `0.0%` | Delivered cases as a share of ordered cases | `DIVIDE ( [Delivered Cases], [Ordered Cases] )` |
| Ordered Cases | Delivery\Cases | `#,0` | Cases ordered for the stop | `SUM ( 'Delivery Stop'[Ordered Cases] )` |
| Refused Cases | Delivery\Cases | `#,0` | Cases refused at the door | `SUM ( 'Delivery Stop'[Refused Cases] )` |
| Short Cases | Delivery\Cases | `#,0` | Cases not on the truck | `SUM ( 'Delivery Stop'[Short Cases] )` |

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Service Date Key | int64 | `service_date_key` | no |  |
| Branch Key | int64 | `branch_key` | no |  |
| Route Key | int64 | `route_key` | no |  |
| Customer Key | int64 | `customer_key` | no |  |
| Driver Key | int64 | `driver_key` | no |  |
| Truck Key | int64 | `truck_key` | no |  |
| Stop Sequence | int64 | `stop_sequence` | yes |  |
| Window Start Minute | int64 | `window_start_minute` | no | Minutes after local midnight |
| Window End Minute | int64 | `window_end_minute` | no | Minutes after local midnight |
| Arrival Minute | int64 | `arrival_minute` | no | Minutes after local midnight, from the arrival source |
| Arrival Source | string | `arrival_source` | yes | Geofence when telematics saw the arrival, TMS when the stop fell back to the driver-entered time |
| Minutes Late | int64 | `minutes_late` | no |  |
| Is On Time | int64 | `is_on_time` | no |  |
| Is On Time TMS | int64 | `is_on_time_tms` | no |  |
| Is In Full | int64 | `is_in_full` | no |  |
| Is OTIF | int64 | `is_otif` | no |  |
| Has Geofence | int64 | `has_geofence` | no |  |
| Is Backfilled | int64 | `is_backfilled` | no |  |
| Ordered Cases | int64 | `ordered_cases` | no |  |
| Short Cases | int64 | `short_cases` | no |  |
| Refused Cases | int64 | `refused_cases` | no |  |
| Delivered Cases | int64 | `delivered_cases` | no |  |
| Dwell Minutes | int64 | `dwell_minutes` | no |  |

## Driver

Driver.

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Driver Key | int64 | `driver_key` | no |  |
| Driver Code | string | `driver_code` | yes |  |
| Driver | string | `driver_name` | yes |  |
| Home Branch | string | `home_branch` | yes |  |

## Fuel

One fuel card transaction.

| Measure | Folder | Format | Description | DAX |
| --- | --- | --- | --- | --- |
| Off-Route Fuel Transactions | Data Health | `#,0` | Fuel card transactions for a truck that was not on a route that day | `CALCULATE ( COUNTROWS ( Fuel ), Fuel[Is On Route Day] = 0 )` |
| Fuel Cost | Fleet | `"$"#,0;("$"#,0);"$"#,0` | Fuel card spend | `SUM ( Fuel[Fuel Cost] )` |
| Gallons | Fleet | `#,0` | Gallons on fuel card transactions | `SUM ( Fuel[Gallons] )` |
| MPG | Fleet | `0.0` | Driven miles per gallon | `DIVIDE ( [Driven Miles], [Gallons] )` |

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Txn Date Key | int64 | `txn_date_key` | no |  |
| Branch Key | int64 | `branch_key` | no |  |
| Truck Key | int64 | `truck_key` | no |  |
| Gallons | double | `gallons` | no |  |
| Fuel Cost | decimal | `fuel_cost` | no |  |
| Is On Route Day | int64 | `is_on_route_day` | no |  |

## Invoice Line

One invoice or credit line, at its posting date. Incremental refresh: three years kept, last ten days refreshed.

Incremental refresh: keep 3 years, refresh the last 10 days.

| Measure | Folder | Format | Description | DAX |
| --- | --- | --- | --- | --- |
| Cases Invoiced | Revenue | `#,0` | Cases on invoice lines, net of credits | `SUM ( 'Invoice Line'[Cases] )` |
| Cost | Revenue | `"$"#,0;("$"#,0);"$"#,0` | Cost of goods on the invoice lines, net of credits | `SUM ( 'Invoice Line'[Cost] )` |
| Credit % | Revenue | `0.0%` | Credits as a share of gross invoiced revenue | `DIVIDE ( -[Credits], CALCULATE ( SUM ( 'Invoice Line'[Revenue] ), 'Invoice Line'[Is Credit] = 0 ) )` |
| Credits | Revenue | `"$"#,0;("$"#,0);"$"#,0` | Credit memo lines for short and refused cases (negative) | `CALCULATE ( SUM ( 'Invoice Line'[Revenue] ), 'Invoice Line'[Is Credit] = 1 )` |
| Gross Margin | Revenue | `"$"#,0;("$"#,0);"$"#,0` | Revenue less cost of goods | `[Revenue] - [Cost]` |
| Gross Margin % | Revenue | `0.0%` | Gross margin as a share of revenue | `DIVIDE ( [Gross Margin], [Revenue] )` |
| Revenue | Revenue | `"$"#,0;("$"#,0);"$"#,0` | Invoiced revenue net of credits, by posting date | `SUM ( 'Invoice Line'[Revenue] )` |
| Revenue per Stop | Revenue | `"$"#,0;("$"#,0);"$"#,0` | Revenue divided by completed stops over the shared dimensions | `DIVIDE ( [Revenue], [Stops] )` |

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Posting Date Key | int64 | `posting_date_key` | no |  |
| Branch Key | int64 | `branch_key` | no |  |
| Customer Key | int64 | `customer_key` | no |  |
| Category Key | int64 | `category_key` | no |  |
| Route Key | int64 | `route_key` | no |  |
| Order Type | string | `order_type` | yes | delivery, or pickup for will-call orders with no stop |
| Is Credit | int64 | `is_credit` | no |  |
| Cases | int64 | `cases` | no |  |
| Revenue | decimal | `revenue` | no |  |
| Cost | decimal | `cost` | no |  |

## Pipeline Run

Pipeline runs, their status and whether the model refresh was triggered.

| Measure | Folder | Format | Description | DAX |
| --- | --- | --- | --- | --- |
| Last Successful Load UTC | Data Health | `yyyy-mm-dd hh:nn` | When the last run that passed every blocking rule finished | `CALCULATE ( MAX ( 'Pipeline Run'[Finished UTC] ), 'Pipeline Run'[Status] = "succeeded" )` |
| Runs Blocked | Data Health | `#,0` | Runs where a blocking data-quality rule stopped the refresh | `CALCULATE ( COUNTROWS ( 'Pipeline Run' ), 'Pipeline Run'[Status] = "blocked" )` |

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Run Id | int64 | `run_id` | yes |  |
| Started UTC | dateTime | `started_utc` | yes |  |
| Finished UTC | dateTime | `finished_utc` | yes |  |
| Source Clock UTC | dateTime | `source_clock_utc` | yes |  |
| Status | string | `status` | yes |  |
| Refresh Status | string | `refresh_status` | yes |  |

## Product Category

Product category and its temperature zone.

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Category Key | int64 | `category_key` | no |  |
| Category Code | string | `category_code` | yes |  |
| Category | string | `category_name` | yes |  |
| Temperature Zone | string | `temp_zone` | yes |  |

## Route Trip

One truck on one route and day, with telematics miles and driver hours.

| Measure | Folder | Format | Description | DAX |
| --- | --- | --- | --- | --- |
| Cost per Case | Fleet | `"$"#,0.00;("$"#,0.00);"$"#,0.00` | Fleet cost per delivered case | `DIVIDE ( [Fleet Cost], [Delivered Cases] )` |
| Cost per Mile | Fleet | `"$"#,0.00;("$"#,0.00);"$"#,0.00` | Fleet cost per driven mile | `DIVIDE ( [Fleet Cost], [Driven Miles] )` |
| Cost per Stop | Fleet | `"$"#,0.00;("$"#,0.00);"$"#,0.00` | Fleet cost per completed stop | `DIVIDE ( [Fleet Cost], [Stops] )` |
| Driven Miles | Fleet | `#,0` | Miles from the telematics trip | `SUM ( 'Route Trip'[Driven Miles] )` |
| Driver Hours | Fleet | `#,0` | Dispatch to return plus 30 minutes of inspections | `SUM ( 'Route Trip'[Driver Hours] )` |
| Fleet Cost | Fleet | `"$"#,0;("$"#,0);"$"#,0` | Driver labor plus fuel | `[Labor Cost] + [Fuel Cost]` |
| Labor Cost | Fleet | `"$"#,0;("$"#,0);"$"#,0` | Driver hours at each driver's hourly rate | `SUM ( 'Route Trip'[Labor Cost] )` |
| Mile Variance % | Fleet | `0.0%` | Driven miles above plan, as a share of planned miles | `DIVIDE ( [Driven Miles] - [Planned Miles], [Planned Miles] )` |
| Planned Miles | Fleet | `#,0` | Miles on the TMS route plan | `SUM ( 'Route Trip'[Planned Miles] )` |
| Route Days | Fleet | `#,0` | Routes run, one per route and day | `COUNTROWS ( 'Route Trip' )` |

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Service Date Key | int64 | `service_date_key` | no |  |
| Branch Key | int64 | `branch_key` | no |  |
| Route Key | int64 | `route_key` | no |  |
| Truck Key | int64 | `truck_key` | no |  |
| Driver Key | int64 | `driver_key` | no |  |
| Planned Stops | int64 | `planned_stops` | no |  |
| Completed Stops | int64 | `completed_stops` | no |  |
| Planned Miles | double | `planned_miles` | no |  |
| Driven Miles | double | `driven_miles` | no |  |
| Driver Hours | double | `driver_hours` | no |  |
| Labor Cost | decimal | `labor_cost` | no |  |

## Route

Delivery route. Not related to Branch, so there is one filter path from Branch to each fact.

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Route Key | int64 | `route_key` | no |  |
| Route Code | string | `route_code` | yes |  |
| Route | string | `route_name` | yes |  |
| Route Branch | string | `route_branch` | yes |  |

## Security Branch Access

User to branch mapping for the Branch Manager role, maintained by IT.

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| User Principal Name | string | `user_principal_name` | yes |  |
| Branch Key | int64 | `branch_key` | yes |  |

## Time Calc

Time intelligence applied to any measure: current, month to date, year to date, prior year, year over year.

| Calculation item | Expression |
| --- | --- |
| Current | `SELECTEDMEASURE ()` |
| MTD | `CALCULATE ( SELECTEDMEASURE (), DATESMTD ( 'Date'[Date] ) )` |
| YTD | `CALCULATE ( SELECTEDMEASURE (), DATESYTD ( 'Date'[Date] ) )` |
| PY | `CALCULATE ( SELECTEDMEASURE (), SAMEPERIODLASTYEAR ( 'Date'[Date] ) )` |
| YoY Change | `VAR CurrentValue = SELECTEDMEASURE () VAR PriorValue = CALCULATE ( SELECTEDMEASURE (), SAMEPERIODLASTYEAR ( 'Date'[Date] ) ) RETURN IF ( NOT ISBLANK ( CurrentValue ) && NOT ISBLANK ( PriorValue ), CurrentValue - PriorValue )` |

## Truck

Refrigerated truck.

| Column | Type | Source column | Visible | Description |
| --- | --- | --- | --- | --- |
| Truck Key | int64 | `truck_key` | no |  |
| Truck | string | `truck_code` | yes |  |
| Home Branch | string | `home_branch` | yes |  |
| Model Year | int64 | `model_year` | yes |  |
| Reefer Type | string | `reefer_type` | yes |  |

## Relationships

All many-to-one, single direction, active.

| From | To |
| --- | --- |
| Delivery Stop[Service Date Key] | Date[Date Key] |
| Delivery Stop[Branch Key] | Branch[Branch Key] |
| Delivery Stop[Route Key] | Route[Route Key] |
| Delivery Stop[Customer Key] | Customer[Customer Key] |
| Delivery Stop[Driver Key] | Driver[Driver Key] |
| Delivery Stop[Truck Key] | Truck[Truck Key] |
| Invoice Line[Posting Date Key] | Date[Date Key] |
| Invoice Line[Branch Key] | Branch[Branch Key] |
| Invoice Line[Customer Key] | Customer[Customer Key] |
| Invoice Line[Category Key] | Product Category[Category Key] |
| Invoice Line[Route Key] | Route[Route Key] |
| Route Trip[Service Date Key] | Date[Date Key] |
| Route Trip[Branch Key] | Branch[Branch Key] |
| Route Trip[Route Key] | Route[Route Key] |
| Route Trip[Truck Key] | Truck[Truck Key] |
| Route Trip[Driver Key] | Driver[Driver Key] |
| Fuel[Txn Date Key] | Date[Date Key] |
| Fuel[Branch Key] | Branch[Branch Key] |
| Fuel[Truck Key] | Truck[Truck Key] |
| Data Quality[Check Date Key] | Date[Date Key] |
| Data Quality[Branch Key] | Branch[Branch Key] |

## Roles

### All Branches

Executives and finance: every branch.

- No row filters.

### Branch Manager

Sees the branches mapped to the signed-in user in the security table. The filter looks the user up
directly, so no relationship has to filter in both directions.

- Branch: `[Branch Key] IN CALCULATETABLE ( VALUES ( 'Security Branch Access'[Branch Key] ), 'Security Branch Access'[User Principal Name] = USERPRINCIPALNAME () )`
- Security Branch Access: `'Security Branch Access'[User Principal Name] = USERPRINCIPALNAME ()`

## Parameters

| Name | Default | Description |
| --- | --- | --- |
| SqlServer | `"localhost,14330"` | SQL Server or Fabric Warehouse SQL endpoint. Deployment rules set it per stage. |
| SqlDatabase | `"fleetdw"` | Warehouse database name. |
| RangeStart | `#datetime(2025, 10, 1, 0, 0, 0)` | Incremental refresh lower bound; the service replaces it per partition. |
| RangeEnd | `#datetime(2027, 1, 1, 0, 0, 0)` | Incremental refresh upper bound; the service replaces it per partition. |
