-- stg_rba_cash_rate.sql
-- Cleans raw RBA cash rate data and adds rate_decision and rate_change_bps.

with source as (

    select * from {{ source('raw', 'raw_rba_cash_rate') }}

),

with_lag as (

    select
        rate_date::date     as rate_date,
        cash_rate_pct::float as cash_rate_pct,

        lag(cash_rate_pct::float) over (order by rate_date::date) as prev_cash_rate_pct

    from source
    where rate_date is not null
      and cash_rate_pct is not null

),

final as (

    select
        rate_date,
        cash_rate_pct,
        prev_cash_rate_pct,

        -- Change in basis points (1% = 100 bps)
        round((cash_rate_pct - coalesce(prev_cash_rate_pct, cash_rate_pct)) * 100, 0)
            as rate_change_bps,

        -- Rate decision classification
        case
            when prev_cash_rate_pct is null           then 'INITIAL'
            when cash_rate_pct > prev_cash_rate_pct   then 'HIKE'
            when cash_rate_pct < prev_cash_rate_pct   then 'CUT'
            else                                           'HOLD'
        end as rate_decision

    from with_lag

)

select * from final
