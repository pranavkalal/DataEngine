"""
ingestion/ingest.py
────────────────────────────────────────────────────────────────────────────
Australian Banking Intelligence Pipeline – Data Ingestion

Pulls three datasets and loads them into Snowflake RAW schema:
  1. ASX bank stock prices        (yfinance)
  2. RBA Official Cash Rate       (rba.gov.au public CSV)
  3. ABS Lending Indicators       (abs.gov.au public Excel download)

Run:
    python ingestion/ingest.py
"""

from __future__ import annotations

import io
import logging
import os
from datetime import date, timedelta

import pandas as pd
import requests
import snowflake.connector
import yfinance as yf
from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

ASX_TICKERS = ["CBA.AX", "WBC.AX", "ANZ.AX", "NAB.AX", "MQG.AX"]

# RBA cash rate target – official public CSV
RBA_CASH_RATE_URL = (
    "https://www.rba.gov.au/statistics/tables/csv/a2-data.csv"
)

# ABS Lending Indicators – Table 1, total housing finance
ABS_LENDING_URL = (
    "https://www.abs.gov.au/statistics/economy/finance/"
    "lending-indicators/latest-release/5601001.xlsx"
)

STOCK_TABLE = "RAW_BANK_STOCK_PRICES"
RBA_TABLE = "RAW_RBA_CASH_RATE"
ABS_TABLE = "RAW_ABS_LENDING"

HISTORY_START = "2019-01-01"


# ── Snowflake helpers ─────────────────────────────────────────────────────────

def _snowflake_account() -> str:
    return os.environ["SNOWFLAKE_ACCOUNT"]


def _snowflake_database() -> str:
    return os.environ["SNOWFLAKE_DATABASE"]


def get_connection() -> snowflake.connector.SnowflakeConnection:
    """Build a fresh Snowflake connection reading credentials from env vars."""
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        role=os.environ["SNOWFLAKE_ROLE"],
        schema="RAW",
    )


def ensure_schema(cur: snowflake.connector.cursor.SnowflakeCursor) -> None:
    cur.execute(
        f"CREATE SCHEMA IF NOT EXISTS {_snowflake_database()}.RAW"
    )


def create_stock_table(cur: snowflake.connector.cursor.SnowflakeCursor) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_snowflake_database()}.RAW.{STOCK_TABLE} (
            TICKER          VARCHAR(20),
            PRICE_DATE      DATE,
            OPEN            FLOAT,
            HIGH            FLOAT,
            LOW             FLOAT,
            CLOSE           FLOAT,
            VOLUME          BIGINT,
            DIVIDENDS       FLOAT,
            STOCK_SPLITS    FLOAT,
            LOADED_AT       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
        """
    )


def create_rba_table(cur: snowflake.connector.cursor.SnowflakeCursor) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_snowflake_database()}.RAW.{RBA_TABLE} (
            RATE_DATE       DATE,
            CASH_RATE_PCT   FLOAT,
            LOADED_AT       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
        """
    )


def create_abs_table(cur: snowflake.connector.cursor.SnowflakeCursor) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_snowflake_database()}.RAW.{ABS_TABLE} (
            LENDING_DATE                DATE,
            TOTAL_HOUSING_FINANCE_M     FLOAT,
            OWNER_OCCUPIER_FINANCE_M    FLOAT,
            INVESTOR_FINANCE_M          FLOAT,
            LOADED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
        """
    )


# ── Extract helpers ───────────────────────────────────────────────────────────

def fetch_asx_stocks() -> pd.DataFrame:
    """Download daily OHLCV data for ASX bank tickers via yfinance."""
    log.info("Fetching ASX stock data for: %s", ASX_TICKERS)
    frames = []
    for ticker in ASX_TICKERS:
        df = yf.download(
            ticker,
            start=HISTORY_START,
            end=date.today().isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            log.warning("No data returned for %s", ticker)
            continue
        df = df.reset_index()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.insert(0, "TICKER", ticker)
        frames.append(df)

    if not frames:
        raise RuntimeError("No stock data fetched for any ticker.")

    result = pd.concat(frames, ignore_index=True)
    result = result.rename(
        columns={
            "Date": "PRICE_DATE",
            "Open": "OPEN",
            "High": "HIGH",
            "Low": "LOW",
            "Close": "CLOSE",
            "Volume": "VOLUME",
            "Dividends": "DIVIDENDS",
            "Stock Splits": "STOCK_SPLITS",
        }
    )
    result["PRICE_DATE"] = pd.to_datetime(result["PRICE_DATE"]).dt.date
    # Fill missing optional columns
    for col in ("DIVIDENDS", "STOCK_SPLITS"):
        if col not in result.columns:
            result[col] = 0.0
    result = result[
        ["TICKER", "PRICE_DATE", "OPEN", "HIGH", "LOW", "CLOSE",
         "VOLUME", "DIVIDENDS", "STOCK_SPLITS"]
    ]
    log.info("Fetched %d stock rows across %d tickers.", len(result), len(ASX_TICKERS))
    return result


def fetch_rba_cash_rate() -> pd.DataFrame:
    """Download the RBA cash rate target CSV and parse it."""
    log.info("Fetching RBA cash rate from %s", RBA_CASH_RATE_URL)
    response = requests.get(RBA_CASH_RATE_URL, timeout=30)
    response.raise_for_status()

    # The RBA CSV has several header rows before the actual data.
    # We skip rows until we find a line that starts with a plausible date.
    lines = response.text.splitlines()
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and stripped[0].isdigit():
            data_start = i
            break

    csv_text = "\n".join(lines[data_start:])
    df = pd.read_csv(
        io.StringIO(csv_text),
        header=None,
        names=["RATE_DATE", "CASH_RATE_PCT"],
        usecols=[0, 1],
    )
    df = df.dropna(subset=["RATE_DATE", "CASH_RATE_PCT"])
    df["RATE_DATE"] = pd.to_datetime(df["RATE_DATE"], dayfirst=True, errors="coerce").dt.date
    df["CASH_RATE_PCT"] = pd.to_numeric(df["CASH_RATE_PCT"], errors="coerce")
    df = df.dropna()
    df = df[df["RATE_DATE"] >= date.fromisoformat(HISTORY_START)]
    log.info("Fetched %d RBA cash rate rows.", len(df))
    return df.reset_index(drop=True)


def fetch_abs_lending() -> pd.DataFrame:
    """
    Download ABS Lending Indicators table 5601001 (Excel) and extract
    total housing finance, owner-occupier, and investor series.
    """
    log.info("Fetching ABS lending indicators from %s", ABS_LENDING_URL)
    response = requests.get(ABS_LENDING_URL, timeout=60)
    response.raise_for_status()

    xl = pd.ExcelFile(io.BytesIO(response.content), engine="openpyxl")

    # Table 1 is the first sheet named "Data1" or similar – try by index
    sheet_name = xl.sheet_names[0]
    log.info("Reading ABS Excel sheet: %s", sheet_name)
    raw = xl.parse(sheet_name, header=None)

    # Row 0 is typically the series description; find the date column
    # ABS time-series workbooks have dates in column 0 starting after header rows
    # Strategy: find the first row where column 0 parses as a date
    date_row = None
    for i, row in raw.iterrows():
        val = row.iloc[0]
        if isinstance(val, str) and len(val) >= 4:
            parsed = pd.to_datetime(val, dayfirst=True, errors="coerce")
            if not pd.isnull(parsed):
                date_row = i
                break
        elif hasattr(val, "year"):
            date_row = i
            break

    if date_row is None:
        raise RuntimeError("Could not identify date rows in ABS Excel file.")

    data = raw.iloc[date_row:].copy()
    data.columns = list(range(data.shape[1]))
    data = data.rename(columns={0: "LENDING_DATE"})
    data["LENDING_DATE"] = pd.to_datetime(
        data["LENDING_DATE"], dayfirst=True, errors="coerce"
    ).dt.date
    data = data.dropna(subset=["LENDING_DATE"])

    # Use first three numeric columns as total, owner-occ, investor
    numeric_cols = [c for c in data.columns if c != "LENDING_DATE"]
    if len(numeric_cols) < 3:
        raise RuntimeError(
            f"Expected at least 3 numeric columns in ABS file, found {len(numeric_cols)}"
        )

    result = data[["LENDING_DATE", numeric_cols[0], numeric_cols[1], numeric_cols[2]]].copy()
    result.columns = [
        "LENDING_DATE",
        "TOTAL_HOUSING_FINANCE_M",
        "OWNER_OCCUPIER_FINANCE_M",
        "INVESTOR_FINANCE_M",
    ]
    for col in ("TOTAL_HOUSING_FINANCE_M", "OWNER_OCCUPIER_FINANCE_M", "INVESTOR_FINANCE_M"):
        result[col] = pd.to_numeric(result[col], errors="coerce")

    result = result.dropna()
    result = result[result["LENDING_DATE"] >= date.fromisoformat(HISTORY_START)]
    log.info("Fetched %d ABS lending rows.", len(result))
    return result.reset_index(drop=True)


# ── Load helpers ──────────────────────────────────────────────────────────────

def truncate_and_load(
    conn: snowflake.connector.SnowflakeConnection,
    df: pd.DataFrame,
    table: str,
    schema: str = "RAW",
) -> None:
    """Truncate the target table and bulk-load the DataFrame."""
    database = _snowflake_database()
    full_name = f"{database}.{schema}.{table}"
    log.info("Truncating %s ...", full_name)
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE IF EXISTS {full_name}")

    log.info("Loading %d rows into %s ...", len(df), full_name)
    success, nchunks, nrows, _ = write_pandas(
        conn=conn,
        df=df,
        table_name=table,
        schema=schema,
        database=database,
        auto_create_table=False,
        quote_identifiers=False,
    )
    if not success:
        raise RuntimeError(f"write_pandas failed for table {full_name}")
    log.info("Loaded %d rows in %d chunk(s) into %s.", nrows, nchunks, full_name)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Australian Banking Intelligence Pipeline – Ingestion ===")

    # 1. Extract
    stock_df = fetch_asx_stocks()
    rba_df = fetch_rba_cash_rate()
    abs_df = fetch_abs_lending()

    # 2. Connect and initialise schema / tables
    log.info("Connecting to Snowflake account: %s", _snowflake_account())
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            ensure_schema(cur)
            create_stock_table(cur)
            create_rba_table(cur)
            create_abs_table(cur)

        # 3. Load
        truncate_and_load(conn, stock_df, STOCK_TABLE)
        truncate_and_load(conn, rba_df, RBA_TABLE)
        truncate_and_load(conn, abs_df, ABS_TABLE)

    finally:
        conn.close()

    log.info("=== Ingestion complete ===")


if __name__ == "__main__":
    main()
