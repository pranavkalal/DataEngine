# 🏦 Australian Banking Intelligence Pipeline

A production-grade data engineering portfolio project that ingests Australian
banking and macroeconomic data into Snowflake, transforms it with dbt Core into
a star schema, and exposes it through a Gemini-powered LangChain agent for
natural-language querying. CI/CD is orchestrated via GitHub Actions.

---

## 📐 Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          DATA SOURCES                                   │
│                                                                         │
│  yfinance (ASX stocks)   rba.gov.au (Cash Rate)   ABS (Lending)        │
└────────────┬────────────────────┬────────────────────┬──────────────────┘
             │                    │                    │
             ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     ingestion/ingest.py                                 │
│          Python  ·  yfinance  ·  requests  ·  snowflake-connector      │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  write_pandas
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Snowflake  ·  RAW Schema                            │
│                                                                         │
│   RAW_BANK_STOCK_PRICES   RAW_RBA_CASH_RATE   RAW_ABS_LENDING          │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  dbt run
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     dbt Core 1.8  ·  Staging Layer (VIEW)               │
│                                                                         │
│   stg_bank_stock_prices   stg_rba_cash_rate   stg_abs_lending           │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Intermediate Layer (VIEW)                           │
│                                                                         │
│   int_daily_returns          int_rate_stock_correlation                 │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Marts Layer (TABLE) – Star Schema                   │
│                                                                         │
│   fact_banking_performance   dim_bank   dim_date                        │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  Snowflake SQL
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│           agent/banking_agent.py  –  LangChain ReAct Agent              │
│                                                                         │
│   Gemini 2.0 Flash  ·  get_bank_performance  ·  get_rba_rate_history   │
│   compare_banks_on_date  ·  CLI interface                               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🛠 Stack

| Component           | Technology                                   |
|---------------------|----------------------------------------------|
| Language            | Python 3.11                                  |
| Data Warehouse      | Snowflake                                    |
| Transformation      | dbt Core 1.8 + dbt_utils 1.x                 |
| Stock Data          | yfinance                                     |
| Macro Data          | RBA (rba.gov.au), ABS (abs.gov.au)           |
| LLM                 | Google Gemini 2.0 Flash                      |
| Agent Framework     | LangChain (ReAct)                            |
| CI/CD               | GitHub Actions                               |
| Env Management      | python-dotenv                                |

---

## 📊 Data Sources

| Source | Dataset | Frequency | Method |
|--------|---------|-----------|--------|
| Yahoo Finance | ASX bank stock prices (CBA, WBC, ANZ, NAB, MQG) | Daily | yfinance API |
| Reserve Bank of Australia | Official Cash Rate target | Ad-hoc | Public CSV from rba.gov.au |
| Australian Bureau of Statistics | Lending Indicators (Table 5601001) | Monthly | Public Excel from abs.gov.au |

---

## 🗂 Project Structure

```
aus-banking-intelligence-pipeline/
├── ingestion/
│   └── ingest.py               # Data extraction & Snowflake loading
├── dbt_project/
│   ├── models/
│   │   ├── staging/            # Clean raw sources → views
│   │   ├── intermediate/       # Enriched calculations → views
│   │   └── marts/              # Star schema tables
│   ├── tests/                  # Custom dbt tests
│   ├── macros/                 # Jinja macros
│   ├── dbt_project.yml
│   ├── packages.yml
│   └── profiles.yml
├── agent/
│   └── banking_agent.py        # LangChain ReAct agent
├── .github/
│   └── workflows/
│       └── dbt_pipeline.yml    # CI/CD pipeline
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 🚀 Setup Instructions

### Prerequisites

- Python 3.11+
- Snowflake account with a database, warehouse, and role
- Google Cloud project with Gemini API access
- dbt CLI (`pip install dbt-snowflake`)

### 1. Clone and install dependencies

```bash
git clone https://github.com/pranavkalal/DataEngine.git
cd DataEngine
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env and fill in your Snowflake and Gemini credentials
```

### 3. Run ingestion

```bash
python ingestion/ingest.py
```

This creates the `RAW` schema in Snowflake and loads:
- `RAW_BANK_STOCK_PRICES`
- `RAW_RBA_CASH_RATE`
- `RAW_ABS_LENDING`

### 4. Set up dbt

```bash
cp dbt_project/profiles.yml ~/.dbt/profiles.yml
cd dbt_project
dbt deps            # installs dbt_utils
dbt debug           # validates Snowflake connection
dbt test --select source:*   # validates raw tables
dbt run             # builds all layers
dbt test            # runs all model tests
dbt docs generate && dbt docs serve  # browse lineage
```

### 5. Launch the agent

```bash
python agent/banking_agent.py
```

---

## 🤖 Example Agent Questions

```
You: What was CBA's average closing price in 2023?
You: Which bank had the highest daily return on 2024-02-07?
You: Show me the last 5 RBA cash rate decisions.
You: Compare all banks on 2024-11-05.
You: What is the 30-day rolling volatility trend for MQG.AX in 2023?
You: How did bank stocks perform in the month after the RBA's last rate hike?
```

---

## ⚙️ CI/CD (GitHub Actions)

The workflow `.github/workflows/dbt_pipeline.yml` runs on every push to `main`
or `develop` and performs:

1. **Checkout** repository
2. **Setup** Python 3.11
3. **Install** `dbt-snowflake`
4. **Copy** `profiles.yml` to `~/.dbt/`
5. **`dbt debug`** – validate connection
6. **`dbt deps`** – install `dbt_utils`
7. **`dbt test --select source:*`** – validate raw tables
8. **`dbt run --select staging`**
9. **`dbt run --select intermediate`**
10. **`dbt run --select marts`**
11. **`dbt test`** – run all model tests
12. **`dbt docs generate`** – generate documentation site
13. **Upload docs** as a GitHub Actions artifact (30-day retention)

Snowflake credentials are injected from GitHub repository secrets:

| Secret Name          | Description                        |
|----------------------|------------------------------------|
| `SNOWFLAKE_ACCOUNT`  | Account identifier                 |
| `SNOWFLAKE_USER`     | Snowflake username                 |
| `SNOWFLAKE_PASSWORD` | Snowflake password                 |
| `SNOWFLAKE_DATABASE` | Target database name               |
| `SNOWFLAKE_WAREHOUSE`| Compute warehouse name             |
| `SNOWFLAKE_ROLE`     | Snowflake role                     |

---

## 🔗 dbt Lineage

```
RAW Sources
    ├── raw_bank_stock_prices  ──►  stg_bank_stock_prices
    │                                     │
    │                                     ▼
    │                              int_daily_returns  ──►  fact_banking_performance
    │                                                              │
    ├── raw_rba_cash_rate  ──►  stg_rba_cash_rate                │
    │                                     │                       │
    │                                     ├──────────────────────►│
    │                                     ▼
    │                         int_rate_stock_correlation
    │                                     ▲
    └── raw_abs_lending   ──►  stg_abs_lending ──────────────────┘

    dim_bank   (static seed values)
    dim_date   (dbt_utils.date_spine)
```

---

## 📄 License

MIT
