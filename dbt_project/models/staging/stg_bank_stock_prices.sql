-- stg_bank_stock_prices.sql
-- Cleans raw ASX bank stock data and adds derived columns.

with source as (

    select * from {{ source('raw', 'raw_bank_stock_prices') }}

),

cleaned as (

    select
        ticker,
        price_date::date                                                        as price_date,
        open::float                                                             as open_price,
        high::float                                                             as high_price,
        low::float                                                              as low_price,
        close::float                                                            as close_price,
        volume::bigint                                                          as volume,
        coalesce(dividends::float, 0)                                           as dividends,
        coalesce(stock_splits::float, 0)                                        as stock_splits,

        -- Intraday return: (close - open) / open
        case
            when open::float = 0 then null
            else round((close::float - open::float) / open::float * 100, 4)
        end                                                                     as intraday_return_pct,

        -- Daily range: high - low
        round(high::float - low::float, 4)                                     as daily_range

    from source
    where
        ticker is not null
        and price_date is not null
        and close::float > 0

)

select * from cleaned
