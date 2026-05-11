-- dim_date.sql
-- Date dimension spanning 2019-01-01 to today, built with dbt_utils.date_spine.

{{ config(materialized='table') }}

with date_spine as (

    {{ dbt_utils.date_spine(
        datepart  = "day",
        start_date = cast('2019-01-01' as date),
        end_date   = cast(dateadd(day, 1, current_date()) as date)
    ) }}

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['date_day']) }}    as date_key,
        date_day::date                                          as full_date,
        year(date_day)                                          as year_num,
        quarter(date_day)                                       as quarter_num,
        month(date_day)                                         as month_num,
        monthname(date_day)                                     as month_name,
        day(date_day)                                           as day_of_month,
        dayofweek(date_day)                                     as day_of_week,       -- 0=Sun in Snowflake
        dayname(date_day)                                       as day_name,
        weekofyear(date_day)                                    as week_of_year,
        dayofyear(date_day)                                     as day_of_year,

        -- is_weekend: Saturday (6) or Sunday (0) in Snowflake's dayofweek
        case
            when dayofweek(date_day) in (0, 6) then true
            else false
        end                                                     as is_weekend,

        -- Simple fiscal year for Australian FY (starts 1 July)
        case
            when month(date_day) >= 7
                then year(date_day) + 1
            else year(date_day)
        end                                                     as aus_fiscal_year

    from date_spine

)

select * from final
