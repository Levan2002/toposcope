# Toposcope

Help, privacy and data pages for **Toposcope**, the iPhone mountain identifier (https://levan2002.github.io/toposcope/).

## Peak database (ODbL)
`docs/data/peaks-v1/` (served at https://levan2002.github.io/toposcope/data/peaks-v1/) holds Toposcope's peak database: every named
`natural=peak` / `natural=volcano` node from OpenStreetMap, one raw-DEFLATE-compressed, tab-separated file per
5° × 5° cell (`p_<latIdx>_<lonIdx>.tsv.z`, latIdx = floor((lat+90)/5), lonIdx = floor((lon+180)/5)), plus
`peaks_major.tsv.z` (notable peaks worldwide), `lists.json` (peak lists) and `index.json`.

Columns: `osm_id, lat, lon, ele (m), name, alt_names (lang=name|…), wikidata, flags (v = volcano, p<m> = prominence)`.

Contains information from OpenStreetMap, © OpenStreetMap contributors, made available under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/). This derived database is
made available under the ODbL 1.0 as well. See `NOTICE-ODbL.txt`. The scripts that build it are in `data-tools/`.
