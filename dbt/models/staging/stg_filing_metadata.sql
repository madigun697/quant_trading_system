select
    cik as stable_id_or_cik,
    accession_number,
    form,
    filing_date,
    accepted_at,
    period_end,
    fiscal_year,
    fiscal_period,
    primary_document,
    filing_href,
    is_xbrl,
    available_at,
    ingested_at,
    'sec' as source
from {{ source('raw', 'sec_filing_metadata') }}
