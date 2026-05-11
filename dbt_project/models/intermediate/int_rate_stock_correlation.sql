-- int_rate_stock_correlation.sql
-- Monthly grain: joins stock performance, RBA rate decisions, and ABS lending.

with monthly_stocks as (

    select
        ticker,
        date_trunc('month', price_date)::date                           as month_start,
        avg(close_price)                                                as avg_close,
        avg(daily_return_pct)                                           as avg_daily_return_pct,
        avg(rolling_30d_volatility)                                     as avg_30d_volatility,
        sum(volume)                                                     as total_volume

    from {{ ref('int_daily_returns') }}
    group by 1, 2

),

-- Pick the most recent RBA decision in each month
monthly_rba as (

    select distinct
        date_trunc('month', rate_date)::date                            as month_start,
        last_value(cash_rate_pct) over (
            partition by date_trunc('month', rate_date)
            order by rate_date
            rows between unbounded preceding and unbounded following
        )                                                               as eom_cash_rate_pct,
        last_value(rate_decision) over (
            partition by date_trunc('month', rate_date)
            order by rate_date
            rows between unbounded preceding and unbounded following
        )                                                               as last_rate_decision,
        sum(abs(rate_change_bps)) over (
            partition by date_trunc('month', rate_date)
        )                                                               as total_abs_rate_change_bps

    from {{ ref('stg_rba_cash_rate') }}

),

monthly_lending as (

    select
        date_trunc('month', lending_date)::date                        as month_start,
        avg(total_lending_m)                                           as avg_total_lending_m,
        avg(investor_share)                                            as avg_investor_share

    from {{ ref('stg_abs_lending') }}
    group by 1

),

joined as (

    select
        s.ticker,
        s.month_start,
        s.avg_close,
        s.avg_daily_return_pct,
        s.avg_30d_volatility,
        s.total_volume,
        r.eom_cash_rate_pct,
        r.last_rate_decision,
        r.total_abs_rate_change_bps,
        l.avg_total_lending_m,
        l.avg_investor_share

    from monthly_stocks        s
    left join monthly_rba      r on r.month_start = s.month_start
    left join monthly_lending  l on l.month_start = s.month_start

)

select * from joined
