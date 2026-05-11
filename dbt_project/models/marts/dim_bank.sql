-- dim_bank.sql
-- Bank dimension with descriptive attributes.

with banks as (

    select * from (values
        ('CBA.AX', 'Commonwealth Bank of Australia', 'Big 4',           'Sydney'),
        ('WBC.AX', 'Westpac Banking Corporation',    'Big 4',           'Sydney'),
        ('ANZ.AX', 'ANZ Banking Group',              'Big 4',           'Melbourne'),
        ('NAB.AX', 'National Australia Bank',        'Big 4',           'Melbourne'),
        ('MQG.AX', 'Macquarie Group',                'Investment Bank', 'Sydney')
    ) as t (ticker, full_name, category, hq_city)

)

select
    {{ dbt_utils.generate_surrogate_key(['ticker']) }}  as bank_key,
    ticker,
    full_name,
    category,
    hq_city

from banks
