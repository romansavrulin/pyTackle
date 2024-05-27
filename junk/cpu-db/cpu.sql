SELECT
    Model, CoreName, Cores, FreqMHz, TurboFreqMHz, TDPWatt
from
    data
where
    Sockettype like '%3647%' And
    CAST(TDPWatt as integer) <= 110
order by
    Cores DESC,
    TDPWatt DESC,
    Model;

SELECT *
from
    main.data
where
    model like '%5218%' And
    Sockettype like '%3647%';

select count(*) from data;