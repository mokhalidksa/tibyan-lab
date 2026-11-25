# Bundled datasets

Both files are refreshed by `scripts/fetch_data.py`, which reduces each source to two columns.

| File | Source | Licence or terms | Rows | Range | SHA-256 |
| --- | --- | --- | --- | --- | --- |
| co2_monthly.csv | NOAA Global Monitoring Laboratory, Mauna Loa monthly mean CO2 (Scripps Institution of Oceanography before April 1974). https://gml.noaa.gov/ccgg/trends/ | Free to use; NOAA GML asks for credit. | 824 | 1958-03 to 2026-10 | 92929d09509ea765c28eca4ccedd6af46ee54c9c6f50c0212e66a54dd5719347 |
| us_births_daily.csv | US births per day, Social Security Administration data via FiveThirtyEight. https://github.com/fivethirtyeight/data/tree/master/births | CC BY 4.0 (credit FiveThirtyEight). | 5,479 | 2000-01-01 to 2014-12-31 | 6b97d706d69075969f517799fa2f93b6ba36cf98de137a739ea40b82032c0c19 |

Downloaded on 25 November 2026. NOAA fills the few missing months by interpolation; the file keeps them as published.
