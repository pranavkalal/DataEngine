-- stg_abs_lending.sql
-- Cleans raw ABS lending indicators and adds derived columns.

with source as (

    select * from {{ source('raw', 'raw_abs_lending') }}

),

cleaned as (

    select
        lending_date::date                                          as lending_date,
        total_housing_finance_m::float                             as total_housing_finance_m,
        owner_occupier_finance_m::float                            as owner_occupier_finance_m,
        investor_finance_m::float                                  as investor_finance_m,

        -- total_lending_m is an alias kept for downstream readability
        total_housing_finance_m::float                             as total_lending_m,

        -- Investor share of total housing lending (0–1)
        case
            when total_housing_finance_m::float = 0 then null
            else round(
                investor_finance_m::float / total_housing_finance_m::float,
                4
            )
        end                                                        as investor_share

    from source
    where
        lending_date is not null
        and total_housing_finance_m::float > 0

)

select * from cleaned
