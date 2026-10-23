-- Optional KPI views over live SFA tables. Apply when you want a mart layer.
-- Analysis tools already compile equivalent SQL against the base tables.

CREATE OR REPLACE VIEW v_rep_month_net_sales AS
SELECT
    shn.Code AS RepCode,
    shn.Name AS RepName,
    DATE_FORMAT(sf.Date, '%Y-%m-01') AS MonthStart,
    SUM(CASE WHEN sf.Type = 'sales' THEN sf.NetValue ELSE -sf.NetValue END) AS NetSales
FROM sales_flat AS sf
INNER JOIN sales_hierarchy_nodes AS shn ON shn.Id = sf.RepId
GROUP BY shn.Code, shn.Name, DATE_FORMAT(sf.Date, '%Y-%m-01');
