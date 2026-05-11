"""
agent/banking_agent.py
────────────────────────────────────────────────────────────────────────────
Australian Banking Intelligence Pipeline – LangChain ReAct Agent

Uses Gemini 2.0 Flash (via ChatGoogleGenerativeAI) with three custom tools:
  1. get_bank_performance  – translates natural language to SQL and runs it
  2. get_rba_rate_history  – returns recent RBA rate decisions
  3. compare_banks_on_date – compares all tracked banks on a given date

Run:
    python agent/banking_agent.py
"""

from __future__ import annotations

import os
import re
import textwrap
from typing import Any

import snowflake.connector
from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

# ── Snowflake connection ───────────────────────────────────────────────────────

def _get_conn() -> snowflake.connector.SnowflakeConnection:
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        role=os.environ["SNOWFLAKE_ROLE"],
        schema="MARTS",
    )


def _run_query(sql: str) -> list[dict[str, Any]]:
    """Execute a SQL query and return rows as list of dicts."""
    conn = _get_conn()
    try:
        cur = conn.cursor(snowflake.connector.DictCursor)
        cur.execute(sql)
        rows = cur.fetchall()
        return rows
    finally:
        conn.close()


# ── Schema context (injected into prompt) ─────────────────────────────────────

SCHEMA_CONTEXT = textwrap.dedent("""
    Database: {database}  (Snowflake)

    Key tables in schema MARTS:
    ─────────────────────────────────────────────────────────────
    FACT_BANKING_PERFORMANCE  – daily fact, grain: ticker + price_date
      Columns: performance_key, ticker, price_date, open_price, high_price,
               low_price, close_price, volume, dividends, stock_splits,
               intraday_return_pct, daily_range, prev_close_price,
               daily_return_pct, rolling_30d_avg_close, rolling_30d_volatility,
               rolling_30d_cumulative_return_pct, current_cash_rate_pct,
               last_rate_decision, last_rate_change_bps, dbt_loaded_at

    DIM_BANK  – bank dimension
      Columns: bank_key, ticker, full_name, category, hq_city

    DIM_DATE  – date dimension
      Columns: date_key, full_date, year_num, quarter_num, month_num,
               month_name, day_of_month, day_of_week, day_name,
               week_of_year, day_of_year, is_weekend, aus_fiscal_year

    Tickers: CBA.AX (Commonwealth), WBC.AX (Westpac), ANZ.AX (ANZ),
             NAB.AX (National Australia), MQG.AX (Macquarie)
    ─────────────────────────────────────────────────────────────
""").format(database=os.environ.get("SNOWFLAKE_DATABASE", "AUS_BANKING"))


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def get_bank_performance(question: str) -> str:
    """
    Translates a natural-language question about bank stock performance into
    a Snowflake SQL query using the schema context, executes it, and returns
    the results as a formatted string.

    Use this for questions about stock prices, returns, volatility, volume,
    or comparisons between banks over time.

    Input: A plain-English question (e.g. "What was CBA's average close price in 2023?")
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=os.environ["GEMINI_API_KEY"],
        temperature=0,
    )

    sql_prompt = textwrap.dedent(f"""
        You are an expert Snowflake SQL analyst.
        Given the schema below, write a single valid Snowflake SQL SELECT query
        that answers the user's question.
        Return ONLY the SQL query – no explanation, no markdown fences.

        Schema:
        {SCHEMA_CONTEXT}

        Question: {question}

        SQL:
    """)

    sql_response = llm.invoke(sql_prompt)
    sql = sql_response.content.strip()
    # Strip markdown code fences if the model included them
    if sql.startswith("```"):
        sql = "\n".join(
            line for line in sql.splitlines()
            if not line.strip().startswith("```")
        ).strip()

    try:
        rows = _run_query(sql)
    except Exception as exc:
        return f"SQL execution error: {exc}\n\nGenerated SQL:\n{sql}"

    if not rows:
        return "Query returned no results."

    # Format as a simple table
    headers = list(rows[0].keys())
    lines = [" | ".join(headers)]
    lines.append("-" * len(lines[0]))
    for row in rows[:50]:  # cap at 50 rows
        lines.append(" | ".join(str(row[h]) for h in headers))
    if len(rows) > 50:
        lines.append(f"... ({len(rows) - 50} more rows)")
    return "\n".join(lines)


@tool
def get_rba_rate_history(n_decisions: str = "10") -> str:
    """
    Returns the most recent RBA cash rate decisions from the data warehouse.

    Input: Number of decisions to return (default: 10).
    """
    try:
        limit = int(n_decisions)
    except ValueError:
        limit = 10

    database = os.environ.get("SNOWFLAKE_DATABASE", "AUS_BANKING")
    sql = textwrap.dedent(f"""
        select
            rate_date,
            cash_rate_pct,
            rate_decision,
            rate_change_bps
        from {database}.STAGING.STG_RBA_CASH_RATE
        order by rate_date desc
        limit {limit}
    """)

    try:
        rows = _run_query(sql)
    except Exception as exc:
        return f"Error fetching RBA rate history: {exc}"

    if not rows:
        return "No RBA rate data found."

    lines = ["RATE_DATE | CASH_RATE_PCT | DECISION | CHANGE_BPS"]
    lines.append("-" * 55)
    for r in rows:
        lines.append(
            f"{r['RATE_DATE']} | {r['CASH_RATE_PCT']}% | "
            f"{r['RATE_DECISION']} | {r['RATE_CHANGE_BPS']} bps"
        )
    return "\n".join(lines)


@tool
def compare_banks_on_date(date_str: str) -> str:
    """
    Compares all tracked ASX banks on a specific date, showing close price,
    daily return, volume, and the prevailing RBA cash rate.

    Input: A date string in YYYY-MM-DD format (e.g. "2024-02-07").
    """
    # Validate strict YYYY-MM-DD format to prevent SQL injection
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return "Invalid date format. Please use YYYY-MM-DD (e.g. 2024-02-07)."

    database = os.environ.get("SNOWFLAKE_DATABASE", "AUS_BANKING")
    sql = textwrap.dedent(f"""
        select
            f.ticker,
            b.full_name,
            f.close_price,
            f.daily_return_pct,
            f.volume,
            f.rolling_30d_volatility,
            f.current_cash_rate_pct,
            f.last_rate_decision
        from {database}.MARTS.FACT_BANKING_PERFORMANCE f
        join {database}.MARTS.DIM_BANK b
            on b.ticker = f.ticker
        where f.price_date = '{date_str}'
        order by f.close_price desc
    """)

    try:
        rows = _run_query(sql)
    except Exception as exc:
        return f"Error comparing banks on {date_str}: {exc}"

    if not rows:
        return f"No data found for {date_str}. Check the date is a trading day."

    lines = [f"Bank comparison for {date_str}:"]
    lines.append(
        "TICKER | BANK                         | CLOSE  | DAILY_RTN% | VOL (M) | RATE%"
    )
    lines.append("-" * 80)
    for r in rows:
        vol_m = f"{r['VOLUME'] / 1_000_000:.1f}" if r["VOLUME"] else "N/A"
        lines.append(
            f"{r['TICKER']:<8} | {r['FULL_NAME']:<28} | "
            f"{r['CLOSE_PRICE']:>6.2f} | {str(r['DAILY_RETURN_PCT'] or 'N/A'):>10} | "
            f"{vol_m:>7} | {r['CURRENT_CASH_RATE_PCT']}"
        )
    return "\n".join(lines)


# ── Agent setup ───────────────────────────────────────────────────────────────

REACT_PROMPT_TEMPLATE = textwrap.dedent("""
    You are the Australian Banking Intelligence Agent. You help users explore
    ASX bank stock performance, RBA interest rate history, and ABS lending data.

    You have access to the following tools:
    {tools}

    Use the following format:
    Question: the input question you must answer
    Thought: consider what you need to do
    Action: the action to take, should be one of [{tool_names}]
    Action Input: the input to the action
    Observation: the result of the action
    ... (repeat Thought/Action/Action Input/Observation as needed)
    Thought: I now know the final answer
    Final Answer: the final answer to the original question

    Begin!

    Question: {input}
    Thought: {agent_scratchpad}
""")

EXAMPLE_QUESTIONS = [
    "What was CBA's average closing price in 2023?",
    "Which bank had the highest daily return on 2024-02-07?",
    "Show me the last 5 RBA cash rate decisions.",
    "Compare all banks on 2024-11-05.",
    "What is the 30-day rolling volatility trend for MQG.AX in 2023?",
    "How did bank stocks perform in the month after the RBA's last rate hike?",
]


def build_agent() -> AgentExecutor:
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=os.environ["GEMINI_API_KEY"],
        temperature=0,
    )
    tools = [get_bank_performance, get_rba_rate_history, compare_banks_on_date]
    prompt = PromptTemplate.from_template(REACT_PROMPT_TEMPLATE)
    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=6)


def main() -> None:
    print("\n=== Australian Banking Intelligence Agent ===")
    print("Type 'quit' or 'exit' to stop.\n")
    print("Example questions:")
    for q in EXAMPLE_QUESTIONS:
        print(f"  • {q}")
    print()

    executor = build_agent()

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() in {"quit", "exit"}:
            print("Goodbye!")
            break

        try:
            result = executor.invoke({"input": question})
            print(f"\nAgent: {result.get('output', 'No response.')}\n")
        except Exception as exc:
            print(f"\n[Error] {exc}\n")


if __name__ == "__main__":
    main()
