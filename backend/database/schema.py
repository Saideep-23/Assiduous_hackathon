"""SQLite DDL for Microsoft Corporate Finance Autopilot."""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS raw_filings (
    filing_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    form_type TEXT NOT NULL,
    filed_date TEXT,
    period_of_report TEXT,
    source_url TEXT
);

CREATE TABLE IF NOT EXISTS raw_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id TEXT NOT NULL REFERENCES raw_filings(filing_id),
    xbrl_tag TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    unit TEXT NOT NULL,
    value REAL,
    pulled_at TEXT NOT NULL,
    fiscal_year INTEGER,
    fiscal_period TEXT,
    composite_key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS financial_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_metric_id INTEGER REFERENCES raw_metrics(id),
    metric_name TEXT NOT NULL,
    period_label TEXT NOT NULL,
    value REAL,
    is_ttm INTEGER NOT NULL DEFAULT 0,
    is_derived INTEGER NOT NULL DEFAULT 0,
    derivation_formula TEXT,
    is_estimated INTEGER NOT NULL DEFAULT 0,
    pulled_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segment_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_metric_id INTEGER REFERENCES raw_metrics(id),
    segment_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    period_label TEXT NOT NULL,
    value REAL,
    is_ttm INTEGER NOT NULL DEFAULT 0,
    pulled_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL,
    pulled_at TEXT NOT NULL,
    is_stale INTEGER NOT NULL DEFAULT 0,
    observation_date TEXT,
    UNIQUE(ticker, metric_name)
);

CREATE TABLE IF NOT EXISTS qualitative_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id TEXT NOT NULL REFERENCES raw_filings(filing_id),
    section_name TEXT NOT NULL,
    raw_text TEXT,
    pulled_at TEXT NOT NULL,
    UNIQUE(filing_id, section_name)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_trace (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_number INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    tool_input_json TEXT,
    tool_output_json TEXT,
    reasoning_text TEXT,
    timestamp TEXT NOT NULL,
    UNIQUE(run_id, step_number)
);

CREATE TABLE IF NOT EXISTS validation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    check_name TEXT NOT NULL,
    passed INTEGER NOT NULL,
    detail TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id TEXT,
    metric_name TEXT,
    warning_type TEXT NOT NULL,
    detail TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_metrics_filing ON raw_metrics(filing_id);
CREATE INDEX IF NOT EXISTS idx_financial_metrics_name ON financial_metrics(metric_name, period_label);
CREATE INDEX IF NOT EXISTS idx_segment_metrics_seg ON segment_metrics(segment_name, metric_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_segment_metrics_raw ON segment_metrics(raw_metric_id);
CREATE INDEX IF NOT EXISTS idx_agent_trace_run ON agent_trace(run_id);
"""
