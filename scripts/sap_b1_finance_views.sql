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
