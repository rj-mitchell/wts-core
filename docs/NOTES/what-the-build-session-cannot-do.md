**The sites' own evaluation sets can't be run from the build session (their data isn't there); real briefings on sample data can, since 13 November 2026.**

As of 13 November 2026, `HANSARD_ANTHROPIC_API_KEY` in the session is answered `401 invalid x-api-key` by
Anthropic (sent either as `x-api-key` or as a bearer token). Don't use the session's own model access in its
place: the sites deliberately ignore an inherited `ANTHROPIC_BASE_URL`. And each site's evaluation of briefings
needs its archive and index (0.2 to 34 GB), which live on the server.

What does work offline: Where MPs Stand's bundled sample (`hansard bootstrap --sample`, about three seconds, then
search and every page work); Where Countries Stand runs on an empty data folder; Where Councils Stand has
`scripts/fixture_site.py` (three made-up councils); the question-reading scores of `wcs evaluate` and
`councils evaluate` need no data. A script for timing real briefings on the sample is kept at
`docs/study/mps_smoke.py` for when there is a working key.

**Update, 13 November 2026.** The owner replaced the key in the environment's settings. A running session keeps the
value it started with; the new one arrived when the session's worker restarted, and Anthropic accepts it. A
changed environment variable is therefore tested after a restart, not straight away. With it, three real briefings
were run on Where MPs Stand's sample data on each side of its library upgrade (`study/smoke-2026-11-13/`): about
10p. The secure form for credentials refuses Anthropic's own hosts, so the environment variable is the only route.
