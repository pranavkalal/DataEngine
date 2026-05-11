-- int_daily_returns.sql
-- Computes per-ticker rolling statistics using window functions.

with base as (

    select * from {{ ref('stg_bank_stock_prices') }}

),

enriched as (

    select
        ticker,
        price_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        dividends,
        stock_splits,
        intraday_return_pct,
        daily_range,

        -- Day-over-day return
        lag(close_price) over (
            partition by ticker order by price_date
        )                                                               as prev_close_price,

        case
            when lag(close_price) over (
                     partition by ticker order by price_date
                 ) = 0
                then null
            else round(
                (close_price - lag(close_price) over (
                    partition by ticker order by price_date
                )) / lag(close_price) over (
                    partition by ticker order by price_date
                ) * 100,
                4
            )
        end                                                             as daily_return_pct,

        -- 30-day rolling average closing price
        round(avg(close_price) over (
            partition by ticker
            order by price_date
            rows between 29 preceding and current row
        ), 4)                                                           as rolling_30d_avg_close,

        -- 30-day rolling volatility (population std dev of daily returns)
        round(stddev_pop(close_price) over (
            partition by ticker
            order by price_date
            rows between 29 preceding and current row
        ), 4)                                                           as rolling_30d_volatility,

        -- 30-day cumulative return from the start of the window
        case
            when first_value(close_price) over (
                     partition by ticker
                     order by price_date
                     rows between 29 preceding and current row
                 ) = 0
                then null
            else round(
                (close_price - first_value(close_price) over (
                    partition by ticker
                    order by price_date
                    rows between 29 preceding and current row
                )) / first_value(close_price) over (
                    partition by ticker
                    order by price_date
                    rows between 29 preceding and current row
                ) * 100,
                4
            )
        end                                                             as rolling_30d_cumulative_return_pct

    from base

)

select * from enriched
