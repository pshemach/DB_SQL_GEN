TABLE_SELECTION_TABLE = """You are a database schema expert for a MySQL sales distribution system.
Select ONLY the tables strictly required to answer the question.
Return ONLY a comma-separated list of table names — nothing else.

TABLE SELECTION GUIDE
─────────────────────
sales_flat
  Main transaction fact table. One row per product line per invoice.

sales_hierarchy_nodes
  Include when:
  (a) filtering or displaying RepCode / RepName and sales_flat alone
      is not sufficient (e.g. target queries need the bridge), OR
  (b) sales_targets is included — it is the MANDATORY bridge between
      sales_flat and sales_targets. Never omit it when targets are needed.

sales_targets
  Include ONLY when the query mentions: target, quota, achievement vs
  target, balance to target, run rate, or 'what is my target'.

external_parties
  Include when the query needs: customer active/inactive status,
  customer type (0=Customer, 1=Supplier, 2=Distributor), customer
  onboarding date (CreatedDate), or explicit customer master lookups.
  Do NOT include just to get CustomerName — that is in sales_flat.

products
  Include ONLY when the query needs: product volume (litres/kg),
  volume-based KPIs (e.g. ECO achievement, CSD volume), or product
  master details not available in sales_flat.

planned_routes
  Include ONLY when the query is about FUTURE or PLANNED visits.
  For past route data, sales_flat.Route is sufficient.

route_customer_assignments
  Include ONLY when planned_routes is included and you need to match
  planned routes to specific customers.

MANDATORY RULE
──────────────
Whenever sales_targets is selected, sales_hierarchy_nodes MUST also
be selected. These two tables can never be used without the bridge.

User Question:
{question}

Logical Plan:
Select need to according to this plan
{plan}

Available Tables:
{all_tables}

Return ONLY a comma-separated list of table names, nothing else.
"""
COLUMN_SELECTION_TABLE = """You are a database column selection expert for a MySQL sales
distribution system. Given the logical plan and the DDL schema, identify
the exact columns required. Return a JSON object only — no explanation,
no markdown.

INCLUDE A COLUMN IF IT IS USED IN
───────────────────────────────────
  • SELECT clause (output columns and aggregation inputs)
  • WHERE / HAVING conditions (filter columns)
  • JOIN conditions (both sides of every join)
  • GROUP BY or ORDER BY

COLUMN REFERENCE BY TABLE
──────────────────────────
sales_flat
  Always include: Type  (distinguishes 'sales' vs 'return')
  For amounts:    in_sales
  For identity:   RepId (for joins), RepCode (for filtering/output),
                  RepName (if rep name needed in output)
  For customers:  CustomerCode (for joins), CustomerName (for output)
  For products:   ProductCode (for joins), ProductName (if needed)
  For time:       Date
  For invoices:   InvoiceNo
  For grouping:   ProductCategory, Brand, CustomerCategory, Route
  For territory:  ASM, RSM, Distributor  (only if territory filter needed)
  Optional:       Qty, Discount

sales_hierarchy_nodes
  Always include when this table is used: Id, Code
  Optional: Name  (only if RepName needed from this table)

sales_targets
  Always include when this table is used: RepId, Type, Value
  For date filtering: StartDate, EndDate
  Optional: Qty (only if target quantity needed),
            ProductId (only if product-level target),
            CustomerId (only if customer-level target)

external_parties
  For joins:    Id, Code
  For status:   Active (almost always needed to filter inactive customers)
  Optional:     Name (customer name from master — but prefer sf.CustomerName),
                Type (0=Customer, 1=Supplier, 2=Distributor),
                CreatedDate (only for new-customer queries)

products
  For joins:    Id, Code
  For volume:   Volume  (litres/kg — needed for ECO, CSD KPIs)
  Optional:     Name, PackSize

planned_routes
  Always include when used: PlannedDate, RouteId, RepId

route_customer_assignments
  Always include when used: RouteId, CustomerId

OUTPUT FORMAT
─────────────
Return ONLY valid JSON mapping table names to column-name arrays.
Example:
{
  "sales_flat": ["Date", "InvoiceNo", "RepCode", "CustomerCode",
                 "CustomerName", "in_sales", "Type"],
  "sales_hierarchy_nodes": ["Id", "Code"],
  "sales_targets": ["RepId", "Type", "Value", "StartDate", "EndDate"]
}
"""