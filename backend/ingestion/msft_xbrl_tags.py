"""
Microsoft (CIK 0000789019) — hardcoded US-GAAP XBRL tags used with SEC Company Facts API.
Verified against MSFT filings; not a general-purpose mapping.
"""

CIK = "0000789019"
TICKER = "MSFT"

# Consolidated — us-gaap namespace in companyfacts JSON
TAG_TOTAL_REVENUE = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
TAG_OPERATING_INCOME = "us-gaap:OperatingIncomeLoss"
TAG_NET_INCOME = "us-gaap:NetIncomeLoss"
TAG_OPERATING_CASH_FLOW = "us-gaap:NetCashProvidedByUsedInOperatingActivities"
# Capex: payments for PPE (cash flow); use absolute value for display
TAG_CAPEX = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
TAG_DA = "us-gaap:Depreciation"
TAG_INTEREST_EXPENSE = "us-gaap:InterestExpense"
# Debt: sum of short-term borrowings + long-term debt (common MSFT presentation)
TAG_DEBT_ST = "us-gaap:LongTermDebtNoncurrent"
TAG_DEBT_CURRENT = "us-gaap:ShortTermBorrowings"
# Fallback if ShortTermBorrowings missing — also try NotesPayable
TAG_CASH = "us-gaap:CashAndCashEquivalentsAtCarryingValue"
# Weighted average diluted shares — DEI tag in facts
TAG_DILUTED_SHARES_DEI = "dei:EntityCommonStockSharesOutstanding"
# US-GAAP diluted weighted average (preferred for EPS denominator when present)
TAG_DILUTED_SHARES_GAAP = "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding"

# Effective tax rate: prefer explicit rate; else derived from tax / pretax
TAG_EFFECTIVE_TAX_RATE = "us-gaap:EffectiveIncomeTaxRateContinuingOperations"
TAG_INCOME_TAX_EXPENSE = "us-gaap:IncomeTaxExpenseBenefit"
TAG_INCOME_BEFORE_TAX = "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"

# Corporate / unallocated — operating income reconciliation to consolidated
TAG_SEGMENT_RECONCILE = "us-gaap:SegmentReportingReconcilingItemForOperatingProfitLossFromSegmentToConsolidatedAmount"

# Segment members (explicit members on StatementBusinessSegmentsAxis in MSFT ixbrl)
SEGMENT_AXIS = "http://fasb.org/us-gaap/2023#StatementBusinessSegmentsAxis"
MEMBER_PRODUCTIVITY = "http://microsoft.com/20240630#ProductivityAndBusinessProcessesMember"
MEMBER_INTELLIGENT_CLOUD = "http://microsoft.com/20240630#IntelligentCloudMember"
MEMBER_MORE_PERSONAL = "http://microsoft.com/20240630#MorePersonalComputingMember"

# Member local names vary by filing date namespace year — match by suffix
MEMBER_SUFFIXES = {
    "ProductivityAndBusinessProcessesMember": "Productivity and Business Processes",
    "IntelligentCloudMember": "Intelligent Cloud",
    "MorePersonalComputingMember": "More Personal Computing",
}

TAG_SEGMENT_REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
TAG_SEGMENT_OP_INCOME = "OperatingIncomeLoss"
