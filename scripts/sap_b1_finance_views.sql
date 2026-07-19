-- CyveTech finance analysis layer for SAP Business One (SQL Server)
-- Run once per company database in SSMS. Creates the CVT_* views that
-- Insights (dashboards, templates and the AI ask-box) build on.
-- Uses DROP + CREATE (not CREATE OR ALTER) so it runs on SQL Server 2012+.

-- ============================================================ base GL view
-- Every journal line joined to its account, classified by GroupMask, with
-- the SAP B1 analysis dimensions: cost center (ProfitCode -> OPRC) and
-- project (Project -> OPRJ).
-- PnLAmount sign convention: revenue positive, costs negative, so
-- SUM(PnLAmount) over classes 4-8 = net result.
IF OBJECT_ID('dbo.CVT_FIN_GL', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_FIN_GL;
GO
CREATE VIEW dbo.CVT_FIN_GL AS
SELECT
    J.TransId,
    J.RefDate,
    YEAR(J.RefDate)  AS PostYear,
    MONTH(J.RefDate) AS PostMonth,
    DATEFROMPARTS(YEAR(J.RefDate), MONTH(J.RefDate), 1) AS MonthStart,
    J.Account        AS AcctCode,
    A.AcctName,
    A.GroupMask      AS ClassCode,
    CASE A.GroupMask
        WHEN 1 THEN '1 - Assets'
        WHEN 2 THEN '2 - Liabilities'
        WHEN 3 THEN '3 - Equity'
        WHEN 4 THEN '4 - Revenue'
        WHEN 5 THEN '5 - Cost of Sales'
        WHEN 6 THEN '6 - Expenses'
        WHEN 7 THEN '7 - Financing'
        ELSE '8 - Other'
    END AS AccountClass,
    J.ProfitCode                       AS CostCenterCode,
    ISNULL(P.PrcName, 'Unassigned')    AS CostCenter,
    J.Project                          AS ProjectCode,
    ISNULL(PJ.PrjName, 'No Project')   AS Project,
    CAST(J.Debit  AS FLOAT) AS Debit,
    CAST(J.Credit AS FLOAT) AS Credit,
    CAST(J.Debit - J.Credit AS FLOAT) AS DebitBalance,
    CAST(J.Credit - J.Debit AS FLOAT) AS PnLAmount
FROM dbo.JDT1 J
INNER JOIN dbo.OACT A ON A.AcctCode = J.Account
LEFT JOIN dbo.OPRC P  ON P.PrcCode = J.ProfitCode
LEFT JOIN dbo.OPRJ PJ ON PJ.PrjCode = J.Project;
GO

-- ==================================================== monthly P&L by account
-- Amount: revenue positive / costs negative (net result = SUM(Amount)).
-- NetDebit: positive magnitude for expense accounts (top-expense rankings).
-- Grain includes CostCenter and Project so profitability can be sliced by
-- either dimension ("net profit per cost center" = GROUP BY CostCenter).
IF OBJECT_ID('dbo.CVT_FIN_PNL_MONTHLY', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_FIN_PNL_MONTHLY;
GO
CREATE VIEW dbo.CVT_FIN_PNL_MONTHLY AS
SELECT
    MonthStart, PostYear, PostMonth,
    AccountClass, ClassCode, AcctCode, AcctName,
    CostCenter, Project,
    SUM(PnLAmount)      AS Amount,
    SUM(Credit)         AS CreditTotal,
    SUM(Debit)          AS DebitTotal,
    SUM(Debit - Credit) AS NetDebit
FROM dbo.CVT_FIN_GL
WHERE ClassCode BETWEEN 4 AND 8
GROUP BY MonthStart, PostYear, PostMonth, AccountClass, ClassCode, AcctCode, AcctName,
    CostCenter, Project;
GO

-- ================================================== balance sheet positions
-- Cumulative balances of asset / liability / equity accounts (debit-positive).
IF OBJECT_ID('dbo.CVT_FIN_BALANCES', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_FIN_BALANCES;
GO
CREATE VIEW dbo.CVT_FIN_BALANCES AS
SELECT
    AccountClass, ClassCode, AcctCode, AcctName,
    SUM(DebitBalance)  AS Balance,
    -SUM(DebitBalance) AS CreditBalance  -- positive for liabilities/equity
FROM dbo.CVT_FIN_GL
WHERE ClassCode BETWEEN 1 AND 3
GROUP BY AccountClass, ClassCode, AcctCode, AcctName;
GO

-- ====================================================== monthly cash motion
-- Incoming payments (ORCT) vs outgoing payments (OVPM), cancelled excluded.
IF OBJECT_ID('dbo.CVT_FIN_CASH_MONTHLY', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_FIN_CASH_MONTHLY;
GO
CREATE VIEW dbo.CVT_FIN_CASH_MONTHLY AS
SELECT
    MonthStart,
    SUM(CashIn)  AS CashIn,
    SUM(CashOut) AS CashOut,
    SUM(CashIn) - SUM(CashOut) AS NetCash
FROM (
    SELECT
        DATEFROMPARTS(YEAR(R.DocDate), MONTH(R.DocDate), 1) AS MonthStart,
        CAST(R.DocTotal AS FLOAT) AS CashIn,
        CAST(0 AS FLOAT)          AS CashOut
    FROM dbo.ORCT R
    WHERE R.Canceled = 'N'
    UNION ALL
    SELECT
        DATEFROMPARTS(YEAR(P.DocDate), MONTH(P.DocDate), 1),
        CAST(0 AS FLOAT),
        CAST(P.DocTotal AS FLOAT)
    FROM dbo.OVPM P
    WHERE P.Canceled = 'N'
) X
GROUP BY MonthStart;
GO

-- ======================================================== receivables aging
-- Every open (unpaid, uncancelled) AR invoice with its remaining balance and
-- days overdue, pre-bucketed for aging charts. Bucket labels are zero-padded
-- so an alphabetical sort is also the correct age order.
IF OBJECT_ID('dbo.CVT_AR_AGING', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_AR_AGING;
GO
CREATE VIEW dbo.CVT_AR_AGING AS
SELECT
    I.DocEntry, I.DocNum, I.CardCode, I.CardName,
    I.DocDate, I.DocDueDate,
    CAST(I.DocTotal - I.PaidToDate AS FLOAT)  AS OpenBalance,
    DATEDIFF(DAY, I.DocDueDate, GETDATE())    AS DaysOverdue,
    CASE
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 0  THEN 'Not due'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 10 THEN '01-10'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 20 THEN '11-20'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 30 THEN '21-30'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 40 THEN '31-40'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 50 THEN '41-50'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 60 THEN '51-60'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 90 THEN '61-90'
        ELSE '91+'
    END AS AgeBucket10,
    CASE
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 0   THEN 'Not due'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 30  THEN '01-30'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 60  THEN '31-60'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 90  THEN '61-90'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 120 THEN '91-120'
        ELSE '>120'
    END AS AgeBucket30
FROM dbo.OINV I
WHERE I.CANCELED = 'N' AND I.DocStatus = 'O';
GO

-- =========================================================== payables aging
-- Mirror of CVT_AR_AGING for open AP invoices (what you owe suppliers).
IF OBJECT_ID('dbo.CVT_AP_AGING', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_AP_AGING;
GO
CREATE VIEW dbo.CVT_AP_AGING AS
SELECT
    I.DocEntry, I.DocNum, I.CardCode, I.CardName,
    I.DocDate, I.DocDueDate,
    CAST(I.DocTotal - I.PaidToDate AS FLOAT)  AS OpenBalance,
    DATEDIFF(DAY, I.DocDueDate, GETDATE())    AS DaysOverdue,
    CASE
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 0  THEN 'Not due'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 10 THEN '01-10'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 20 THEN '11-20'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 30 THEN '21-30'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 40 THEN '31-40'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 50 THEN '41-50'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 60 THEN '51-60'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 90 THEN '61-90'
        ELSE '91+'
    END AS AgeBucket10,
    CASE
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 0   THEN 'Not due'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 30  THEN '01-30'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 60  THEN '31-60'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 90  THEN '61-90'
        WHEN DATEDIFF(DAY, I.DocDueDate, GETDATE()) <= 120 THEN '91-120'
        ELSE '>120'
    END AS AgeBucket30
FROM dbo.OPCH I
WHERE I.CANCELED = 'N' AND I.DocStatus = 'O';
GO

-- ============================================================== stock value
-- Warehouse stock with cost value and item group, so stock value can be
-- sliced by warehouse, item group or item. AvgPrice is the company average
-- cost from the item master.
IF OBJECT_ID('dbo.CVT_STOCK_VALUE', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_STOCK_VALUE;
GO
CREATE VIEW dbo.CVT_STOCK_VALUE AS
SELECT
    W.WhsCode,
    W.ItemCode,
    I.ItemName,
    ISNULL(G.ItmsGrpNam, 'Ungrouped') AS ItemGroup,
    CAST(W.OnHand AS FLOAT)              AS OnHand,
    CAST(W.OnHand * I.AvgPrice AS FLOAT) AS StockValue
FROM dbo.OITW W
INNER JOIN dbo.OITM I ON I.ItemCode = W.ItemCode
LEFT JOIN dbo.OITB G  ON G.ItmsGrpCod = I.ItmsGrpCod
WHERE W.OnHand <> 0;
GO

-- ================================================= monthly stock in vs out
-- Inbound vs outbound stock value and quantity per month, from the
-- inventory journal. Value split follows the sign of TransValue.
IF OBJECT_ID('dbo.CVT_STOCK_MOVEMENT_MONTHLY', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_STOCK_MOVEMENT_MONTHLY;
GO
CREATE VIEW dbo.CVT_STOCK_MOVEMENT_MONTHLY AS
SELECT
    DATEFROMPARTS(YEAR(DocDate), MONTH(DocDate), 1) AS MonthStart,
    SUM(CAST(InQty AS FLOAT))  AS QtyIn,
    SUM(CAST(OutQty AS FLOAT)) AS QtyOut,
    SUM(CASE WHEN TransValue > 0 THEN CAST(TransValue AS FLOAT) ELSE 0 END)  AS InValue,
    SUM(CASE WHEN TransValue < 0 THEN -CAST(TransValue AS FLOAT) ELSE 0 END) AS OutValue,
    SUM(CAST(TransValue AS FLOAT)) AS NetValue
FROM dbo.OINM
GROUP BY DATEFROMPARTS(YEAR(DocDate), MONTH(DocDate), 1);
GO

-- ==================================== monthly purchases vs goods returns
IF OBJECT_ID('dbo.CVT_PURCHASE_VS_RETURNS_MONTHLY', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_PURCHASE_VS_RETURNS_MONTHLY;
GO
CREATE VIEW dbo.CVT_PURCHASE_VS_RETURNS_MONTHLY AS
SELECT
    MonthStart,
    SUM(PurchaseAmount) AS PurchaseAmount,
    SUM(ReturnAmount)   AS ReturnAmount
FROM (
    SELECT DATEFROMPARTS(YEAR(DocDate), MONTH(DocDate), 1) AS MonthStart,
           CAST(DocTotal AS FLOAT) AS PurchaseAmount, CAST(0 AS FLOAT) AS ReturnAmount
    FROM dbo.OPCH WHERE CANCELED = 'N'
    UNION ALL
    SELECT DATEFROMPARTS(YEAR(DocDate), MONTH(DocDate), 1),
           CAST(0 AS FLOAT), CAST(DocTotal AS FLOAT)
    FROM dbo.ORPD WHERE CANCELED = 'N'
) X
GROUP BY MonthStart;
GO

-- ======================================================= delivery performance
-- Each delivery matched to the sales order it fulfils (via base document
-- links): fulfillment days, delay vs promised date and on-time flag.
-- OnTimePct is 100/0 per delivery so AVG() gives the on-time rate in %.
IF OBJECT_ID('dbo.CVT_DELIVERY_PERF', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_DELIVERY_PERF;
GO
CREATE VIEW dbo.CVT_DELIVERY_PERF AS
SELECT
    D.DocEntry, D.DocNum, D.CardCode, D.CardName,
    D.DocDate      AS DeliveryDate,
    O.DocDate      AS OrderDate,
    O.DocDueDate   AS PromisedDate,
    DATEDIFF(DAY, O.DocDate, D.DocDate)    AS FulfillmentDays,
    DATEDIFF(DAY, O.DocDueDate, D.DocDate) AS DelayDays,
    CASE WHEN D.DocDate <= O.DocDueDate THEN 100.0 ELSE 0.0 END AS OnTimePct
FROM dbo.ODLN D
INNER JOIN (
    SELECT DISTINCT DocEntry, BaseEntry FROM dbo.DLN1 WHERE BaseType = 17
) L ON L.DocEntry = D.DocEntry
INNER JOIN dbo.ORDR O ON O.DocEntry = L.BaseEntry
WHERE D.CANCELED = 'N';
GO

-- ======================================================= opportunity stages
-- Every opportunity with its current pipeline stage name (last stage line).
IF OBJECT_ID('dbo.CVT_OPP_STAGES', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_OPP_STAGES;
GO
CREATE VIEW dbo.CVT_OPP_STAGES AS
SELECT
    O.OpprId, O.CardCode, O.Status, O.OpenDate, O.CloseDate,
    CAST(O.MaxSumLoc AS FLOAT) AS PotentialAmount,
    CAST(O.WtSumLoc AS FLOAT)  AS WeightedAmount,
    ISNULL(S.Descript, 'No Stage') AS StageName
FROM dbo.OOPR O
OUTER APPLY (
    SELECT TOP 1 Step_Id FROM dbo.OPR1 WHERE OpprId = O.OpprId ORDER BY Line DESC
) L
LEFT JOIN dbo.OOST S ON S.Num = L.Step_Id;
GO

-- ========================================================== ratio KPI board
-- One row of pre-computed ratios for the cockpit KPI tiles: margins, ROE,
-- working capital, DSO/DPO/DIO/CCC, stock and asset turnover, win rate.
-- 12M = trailing 12 months; YTD = current calendar year. Working capital
-- uses total assets minus total liabilities (approximation: B1's GroupMask
-- does not separate current from non-current).
IF OBJECT_ID('dbo.CVT_KPI_SUMMARY', 'V') IS NOT NULL
    DROP VIEW dbo.CVT_KPI_SUMMARY;
GO
CREATE VIEW dbo.CVT_KPI_SUMMARY AS
WITH rev AS (
    SELECT
        SUM(CASE WHEN H.DocDate >= DATEADD(MONTH, -12, GETDATE()) THEN CAST(L.LineTotal AS FLOAT) END)  AS Revenue12M,
        SUM(CASE WHEN H.DocDate >= DATEADD(MONTH, -12, GETDATE()) THEN CAST(L.GrssProfit AS FLOAT) END) AS GrossProfit12M,
        SUM(CASE WHEN YEAR(H.DocDate) = YEAR(GETDATE()) THEN CAST(L.LineTotal AS FLOAT) END)  AS RevenueYTD,
        SUM(CASE WHEN YEAR(H.DocDate) = YEAR(GETDATE()) THEN CAST(L.GrssProfit AS FLOAT) END) AS GrossProfitYTD
    FROM dbo.INV1 L
    INNER JOIN dbo.OINV H ON H.DocEntry = L.DocEntry
    WHERE H.CANCELED = 'N'
), gl AS (
    SELECT
        SUM(CASE WHEN A.GroupMask BETWEEN 4 AND 8 AND J.RefDate >= DATEADD(MONTH, -12, GETDATE())
                 THEN CAST(J.Credit - J.Debit AS FLOAT) END) AS NetProfit12M,
        SUM(CASE WHEN A.GroupMask = 1 THEN CAST(J.Debit - J.Credit AS FLOAT) END) AS Assets,
        SUM(CASE WHEN A.GroupMask = 2 THEN CAST(J.Credit - J.Debit AS FLOAT) END) AS Liabilities,
        SUM(CASE WHEN A.GroupMask = 3 THEN CAST(J.Credit - J.Debit AS FLOAT) END) AS Equity
    FROM dbo.JDT1 J
    INNER JOIN dbo.OACT A ON A.AcctCode = J.Account
), ar AS (
    SELECT SUM(CAST(DocTotal - PaidToDate AS FLOAT)) AS OpenAR
    FROM dbo.OINV WHERE CANCELED = 'N' AND DocStatus = 'O'
), ap AS (
    SELECT SUM(CAST(DocTotal - PaidToDate AS FLOAT)) AS OpenAP
    FROM dbo.OPCH WHERE CANCELED = 'N' AND DocStatus = 'O'
), stk AS (
    SELECT
        SUM(CAST(TransValue AS FLOAT)) AS StockValue,
        SUM(CASE WHEN TransValue < 0 AND DocDate >= DATEADD(MONTH, -12, GETDATE())
                 THEN -CAST(TransValue AS FLOAT) ELSE 0 END) AS COGS12M
    FROM dbo.OINM
), pur AS (
    SELECT SUM(CASE WHEN DocDate >= DATEADD(MONTH, -12, GETDATE()) THEN CAST(DocTotal AS FLOAT) END) AS Purchases12M
    FROM dbo.OPCH WHERE CANCELED = 'N'
), opp AS (
    SELECT
        SUM(CASE WHEN Status = 'W' THEN 1.0 ELSE 0 END) AS Won,
        SUM(CASE WHEN Status IN ('W', 'L') THEN 1.0 ELSE 0 END) AS Closed
    FROM dbo.OOPR
)
SELECT
    rev.RevenueYTD,
    rev.GrossProfitYTD,
    100.0 * rev.GrossProfitYTD / NULLIF(rev.RevenueYTD, 0) AS GrossMarginYTD,
    100.0 * gl.NetProfit12M / NULLIF(rev.Revenue12M, 0)    AS NetMargin12M,
    gl.Assets, gl.Liabilities, gl.Equity,
    gl.Assets - gl.Liabilities                              AS WorkingCapital,
    100.0 * gl.NetProfit12M / NULLIF(gl.Equity, 0)          AS ROE,
    ar.OpenAR, ap.OpenAP,
    365.0 * ar.OpenAR / NULLIF(rev.Revenue12M, 0)           AS DSODays,
    365.0 * ap.OpenAP / NULLIF(pur.Purchases12M, 0)         AS DPODays,
    365.0 * stk.StockValue / NULLIF(stk.COGS12M, 0)         AS DIODays,
    365.0 * ar.OpenAR / NULLIF(rev.Revenue12M, 0)
        + 365.0 * stk.StockValue / NULLIF(stk.COGS12M, 0)
        - 365.0 * ap.OpenAP / NULLIF(pur.Purchases12M, 0)   AS CCCDays,
    stk.StockValue,
    stk.COGS12M / NULLIF(stk.StockValue, 0)                 AS StockTurnover12M,
    rev.Revenue12M / NULLIF(gl.Assets, 0)                   AS AssetTurnover12M,
    100.0 * opp.Won / NULLIF(opp.Closed, 0)                 AS OppWinRatePct
FROM rev CROSS JOIN gl CROSS JOIN ar CROSS JOIN ap
CROSS JOIN stk CROSS JOIN pur CROSS JOIN opp;
GO
