-- fact_banking_performance.sql
-- Daily fact table with surrogate key, joined to RBA rate context.

with daily_returns as (

    select * from {{ ref('int_daily_returns') }}

),

rba as (

    select * from {{ ref('stg_rba_cash_rate') }}

),

-- Carry-forward the most recent cash rate to every trading date
-- by finding the latest RBA rate date <= stock price date.
latest_rate as (

    select
        d.ticker,
        d.price_date,
        max(r.rate_date) as last_rate_date

    from daily_returns d
    left join rba r
        on r.rate_date <= d.price_date

    group by 1, 2

),

rate_context as (

    select
        lr.ticker,
        lr.price_date,
        r.cash_rate_pct          as current_cash_rate_pct,
        r.rate_decision          as last_rate_decision,
        r.rate_change_bps        as last_rate_change_bps

    from latest_rate lr
    left join rba r
        on r.rate_date = lr.last_rate_date

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['dr.ticker', 'dr.price_date']) }}
                                                                        as performance_key,

        dr.ticker,
        dr.price_date,
        dr.open_price,
        dr.high_price,
        dr.low_price,
        dr.close_price,
        dr.volume,
        dr.dividends,
        dr.stock_splits,
        dr.intraday_return_pct,
        dr.daily_range,
        dr.prev_close_price,
        dr.daily_return_pct,
        dr.rolling_30d_avg_close,
        dr.rolling_30d_volatility,
        dr.rolling_30d_cumulative_return_pct,

        rc.current_cash_rate_pct,
        rc.last_rate_decision,
        rc.last_rate_change_bps,

        current_timestamp()                                             as dbt_loaded_at

    from daily_returns  dr
    left join rate_context rc
        on rc.ticker     = dr.ticker
        and rc.price_date = dr.price_date

)

select * from final
