**No live briefing or evaluation run can be made from the build session: the API key is refused and the sites' data is not there.**

As of 13 November 2026, `HANSARD_ANTHROPIC_API_KEY` in the session is answered `401 invalid x-api-key` by
Anthropic (sent either as `x-api-key` or as a bearer token). Don't use the session's own model access in its
place: the sites deliberately ignore an inherited `ANTHROPIC_BASE_URL`. And each site's evaluation of briefings
needs its archive and index (0.2 to 34 GB), which live on the server.

What does work offline: Where MPs Stand's bundled sample (`hansard bootstrap --sample`, about three seconds, then
search and every page work); Where Countries Stand runs on an empty data folder; Where Councils Stand has
`scripts/fixture_site.py` (three made-up councils); the question-reading scores of `wcs evaluate` and
`councils evaluate` need no data. A script for timing real briefings on the sample is kept at
`docs/study/mps_smoke.py` for when there is a working key.
