# Study: config, backup, off-site copies, the DuckDB wrapper, and how they are run

12 November 2026. Read from the four working trees as they stood that day (each checked out on the branch
`claude/gallant-cerf-xxy2ge`). Nothing was run except a normalised diff, a TOML key listing and one four-line SQLite
experiment (noted where used). No site's tests were run.

**Short names used below**

| Short | Repository | Package path | Prefix |
|---|---|---|---|
| MPs | `/home/user/wherempsstand` | `src/hansard/` | `HANSARD_` |
| Countries | `/home/user/wherecountriesstand` | `src/wcs/` | `WCS_` |
| Councils | `/home/user/wherecouncilsstand` | `src/councils/` | `COUNCILS_` |
| Landlords | `/home/user/wherelandlordsstand` | `src/landlords/` | `LANDLORDS_` |

A reference such as `hansard/backup.py:24` is under that site's `src/`; `deploy/…`, `tests/…` and `config/…` are
under the repository named in the sentence or column.

**Classes of difference:** (a) a fix one copy has and others lack; (b) deliberate and site-specific; (c) incidental.

**Two statements in `family/ENGINE.md` are out of date** (found while reading; they change which copy is upstream):

1. "Config loading … MPs … alone layers and writes `data/settings.local.toml`": Countries (`wcs/config.py:95-99`)
   and Councils (`councils/config.py:85-89`) also *layer* it. Only MPs *writes* it (`hansard/config.py:114-136`).
2. "Off-site copies … MPs … alone raises backup alerts": Countries (`wcs/offsite.py:155-185`) and Councils
   (`councils/offsite.py:155-184`) both have `backup_alerts`. Only Landlords lacks it. For backup, Countries'
   `restore_backup` is safer than MPs' (section 2), so MPs is not the best copy of restore.

## Contents

1. [Config loading](#1-config-loading)
2. [Backup and restore](#2-backup-and-restore)
3. [Off-site copies to Backblaze B2](#3-off-site-copies-to-backblaze-b2)
4. [The thread-safe DuckDB wrapper](#4-the-thread-safe-duckdb-wrapper)
5. [How they are invoked: commands, units, timers](#5-how-they-are-invoked-commands-units-timers)
6. [Ports worth making now](#6-ports-worth-making-now)
7. [Open questions](#7-open-questions)
8. [What was not read](#8-what-was-not-read)

---

## 1. Config loading

### What it does

Reads one TOML file (`config/settings.toml`, or the file named by `<PREFIX>CONFIG`), works out the data folder
(`<PREFIX>DATA_DIR`, else `[paths] data_dir`, else `"data"`; relative paths are relative to the repository root), and
returns a frozen `Settings` dataclass holding the raw dictionary. MPs, Countries and Councils then merge
`<data_dir>/settings.local.toml` over it, section by section, and then any `section.key=value` keyword overrides.
`get_settings()` caches one `Settings` for the process.

### Public names and signatures

| Name | MPs `hansard/config.py` | Countries `wcs/config.py` | Councils `councils/config.py` | Landlords `landlords/config.py` |
|---|---|---|---|---|
| `REPO_ROOT = Path(__file__).resolve().parents[2]` | :13 | :13 | :13 | :12 |
| `DEFAULT_CONFIG = REPO_ROOT / "config" / "settings.toml"` | :14 | :14 | :14 | absent; `CONFIG_DIR = REPO_ROOT / "config"` :13 |
| `STATIC_DIR = REPO_ROOT / "data_static"` | :15 | :15 | :15 | :14 |
| `Settings` (frozen dataclass): `raw: dict[str, Any]`, `data_dir: Path`, `config_path: Path` | :18-22 | :18-22 | :18-22 | :17-21 |
| `Settings.overrides: dict[str, Any] = field(default_factory=dict)` | :23 | :23 | :23 | absent |
| `Settings.section(name: str) -> dict[str, Any]` (`self.raw.get(name, {})`) | :25-26 | :25-26 | :25-26 | :23-24 |
| `_resolve(path: str \| Path) -> Path` | :92-94 | :85-87 | :75-77 | :42-44 |
| `load_settings(config_path: str \| Path \| None = None, **overrides: Any) -> Settings` | :97-111 | :90-103 | :80-93 | `load_settings(config_path: str \| Path \| None = None) -> Settings` :47-59 (no overrides) |
| `save_local_settings(data_dir: Path, updates: dict[str, dict[str, Any]]) -> Path` | :114-136 | absent | absent | absent |
| `get_settings() -> Settings` (`@lru_cache(maxsize=1)`) | :139-141 | :106-108 | :96-98 | :62-64 |
| `load_toml(name: str) -> dict[str, Any]` (a file in `config/`) | absent | absent | absent | :67-70 |

Per-site accessors on `Settings` (all are thin reads of `raw` or joins on `data_dir`; ENGINE.md says they differ on
purpose):

| Site | Section accessors | Data-layout accessors |
|---|---|---|
| MPs | `archive_start -> date` (default `"1997-05-01"`) :30-31; `record_dirs` :34-35; `ranking` :38; `answer` :42; `embedding` :46; `regions` :50; `usage` :54; `sources` :58 | `raw_xml_dir` = `raw/scrapedxml` :63; `parlparse_dir` = `raw/parlparse` :67; `reference_dir` :71; `parquet_dir` :75; `index_dir` :79; **`state_db` = `data_dir / "state.sqlite"`** :83-85; `log_dir` = `logs` :88 |
| Countries | `archive` :30; `start_date` (default `"1992-01-01"`) :34-36; `archive_start` (key `archive_start_date`, default `"1946-01-01"`) :39-41; `born_digital_from` (default 1994) :44-45; `ranking` :48; `answer` :52; `embedding` :56; `sources` :60; `usage` :64 | `raw_dir` :69; `parquet_dir` :73; `index_dir` :77; `models_dir` :81 |
| Councils | `start_date` (default `"2018-05-01"`) :29-31; `modgov` :34; `archive` :38; `ranking` :42; `answer` :46; `embedding` :50; `usage` :54 | `raw_dir` :59; `parquet_dir` :63; `index_dir` :67; `models_dir` :71 |
| Landlords | `fetch` :27-28 | `raw_dir` :32-34; `staging_dir` :37-39 |

Note the same name with two meanings: `archive_start` is the 1997 start in MPs and the 1946 archive in Countries.

### Differences

| # | What | MPs | Countries | Councils | Landlords | Class |
|---|---|---|---|---|---|---|
| 1 | Layering `<data_dir>/settings.local.toml` over the file (`raw.setdefault(section, {}).update(values)`) | `config.py:103-107` | `config.py:95-99` | `config.py:85-89` | not done | (c) for the three (identical code); Landlords' absence looks deliberate (no command writes one), not settled: open question |
| 2 | Writing `settings.local.toml` | `save_local_settings` `config.py:114-136`; called by `bootstrap.py:84` (`archive.start_date`, `embedding.enabled`) and `cli.py:282` (`ranking.vector_nprobes`, `ranking.vector_refine_factor`, from `reindex-vectors` :267 and `vectors-f16` :392). `bootstrap --sample` writes the whole file by hand, replacing it (`bootstrap.py:66-68`) | none in `src/` | none in `src/`; `scripts/fixture_site.py:131` writes one by hand | none | (b): only MPs has commands that need to remember a choice. A shared package should carry the writer for all |
| 3 | Keyword overrides `load_settings(**{"embedding.backend": "hashing"})`, split on the first dot | `config.py:108-110` | `:100-102` | `:90-92` | not supported (`:47`) | (c) for three; Landlords never needed it (its `conftest.py:17-19` only sets `LANDLORDS_DATA_DIR`) |
| 4 | Environment overrides of settings values | none in `config.py` (`HANSARD_DONATE_URL` is read in `api/app.py`, not here) | none in `config.py` | none | `LANDLORDS_SITE_URL` → `site.url` (stripped) `:55-56`; `LANDLORDS_LAUNCHED` → `site.launched`, true only for `1`, `true`, `yes` (case-insensitive) `:57-58` | (b) |
| 5 | Default config path constant | `DEFAULT_CONFIG` | `DEFAULT_CONFIG` | `DEFAULT_CONFIG` | `CONFIG_DIR / "settings.toml"` inline `:48` | (c) |
| 6 | Other files in `config/` | `topics.toml`, found as `settings.config_path.parent / [topics] file` (`topics.py:49-50`): follows `HANSARD_CONFIG` | none | none | six more, read by `load_toml(name)` from `CONFIG_DIR` always (`:67-70`): does **not** follow `LANDLORDS_CONFIG` | (b)/(c): two ways of finding sibling files |
| 7 | State database path | `settings.state_db` → `state.sqlite` (`config.py:83-85`) | `load_settings().data_dir / "state.db"` written out at each use (`cli.py:206, 230, 257, 288, 300, 327, 420`) | the same, `cli.py:181, 242` | the same, `cli.py:190, 259, 305` | (b) on-disk name; (c) where it is computed |
| 8 | Comment at `load_settings` | `# Per-installation overrides written by \`hansard bootstrap\`…` `:102` | none | none | comment on `.env` `:52-53` | (c) |

**No (a) differences in the loader itself:** lines 97-111 of MPs, 90-103 of Countries and 80-93 of Councils are the
same statements.

### What an operator or reader would notice

- **Environment variables read by `config.py`:** `HANSARD_CONFIG`, `HANSARD_DATA_DIR`; `WCS_CONFIG`, `WCS_DATA_DIR`;
  `COUNCILS_CONFIG`, `COUNCILS_DATA_DIR`; `LANDLORDS_CONFIG`, `LANDLORDS_DATA_DIR`, `LANDLORDS_SITE_URL`,
  `LANDLORDS_LAUNCHED`. An empty value counts as unset (`os.environ.get(...) or ...`).
- **Order of precedence** (three AI sites): `settings.toml` < `settings.local.toml` < keyword overrides. The data
  folder is fixed before the local file is read, so `[paths] data_dir` in a local file has no effect on where data is.
- **The merge is one level deep.** A local `[usage.models."x"]` table replaces the whole `usage.models` table rather
  than adding to it. A top-level key outside a table in the local file raises (`.update` on a non-table).
- **`save_local_settings` (MPs) file format,** exact: first line
  ``# Per-installation settings written by `hansard bootstrap`; they override config/settings.toml.``, then for each
  section a blank line, `[section]`, and `key = value` lines; file ends with a newline (`:131-135`). Values: booleans
  as `true`/`false`; ints and floats by `repr`; everything else as a double-quoted string with `\` and `"` escaped
  (`:124-129`). Lists, dates, nested tables and strings with newlines are **not** written correctly (a list becomes a
  quoted string). It merges with what is there (`:117-122`), creates the folder, and returns the path. The header says
  "`hansard bootstrap`" even when `reindex-vectors` wrote it.
- **`bootstrap --sample` (MPs) content,** exact (`bootstrap.py:67-68`):
  `# Written by \`hansard bootstrap --sample\`: offline demo settings.` then `[embedding]`, `backend = "hashing"`,
  `dim = 64`, blank, `[auth]`, `required = false`.
- MPs' backup archive carries `settings.local.toml` and restore puts it back (section 2): the file is part of MPs'
  state. On the server it is `/data/settings.local.toml` (MPs `docs/HOSTING.md:243, 610, 659`).
- `Settings` is frozen but `raw` is a plain dict and is mutated in place by the loader (`setdefault`).
- A missing or malformed config file raises `FileNotFoundError` / `tomllib.TOMLDecodeError` uncaught in all four.

### Settings sections and keys in `config/settings.toml`

Section header lines:

| Section | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| `[paths]` | :4 | :4 | :4 | :4 |
| `[archive]` | :7 | :7 | :7 | – |
| `[live]` | – | :18 | – | – |
| `[sources]` | :16 | :37 | – | – |
| `[regions]` | :25 | – | – | – |
| `[modgov]` | – | – | :13 | – |
| `[robots]` | – | – | :29 | – |
| `[fetch]` | – | – | – | :7 |
| `[coverage]` | – | – | – | :15 |
| `[ranking]` | :32 | :51 | :36 | – |
| `[answer]` | :84 | :73 | :51 | – |
| `[embedding]` | :108 | :84 | :63 | – |
| `[usage]` | :120 | :93 | :72 | – |
| `[usage.models."claude-sonnet-5-5"]` | :139 | – | – | – |
| `[usage.models."claude-haiku-5-5"]` | :144 | :113 | :90 | – |
| `[auth]` | :150 | – | – | – |
| `[sync]` | :156 | – | – | – |
| `[site]` | :160 | :118 | :95 | :19 |
| `[topics]` | :166 | – | – | – |
| `[groups]` | :173 | – | – | – |
| `[sister_sites]` | – | – | – | :35 |
| `[publish]` | – | – | – | :42 |

Every key and its value in each file (made by reading the four files with `tomllib`; "–" means the key is not in that
file; **In** counts the sites that have it). Only `[paths] data_dir` is in all four. Keys commented out in the file are
not listed: MPs has `# vector_nprobes = 20` (:42) and `# reranker = "Xenova/ms-marco-MiniLM-L-6-v2"` (:79), both read
by code when set. Keys the code reads but no file sets (for example `embedding.enabled`, written to
`settings.local.toml` by MPs' bootstrap) were not searched for exhaustively.

| Section | Key | MPs | Countries | Councils | Landlords | In |
|---|---|---|---|---|---|---|
| `[answer]` | `comprehensive_effort` | `"high"` | `"high"` | `"high"` | – | 3 (same value) |
| `[answer]` | `comprehensive_side_sources` | `15` | – | – | – | 1 |
| `[answer]` | `comprehensive_sources` | `40` | `40` | `40` | – | 3 (same value) |
| `[answer]` | `interests_check` | `true` | – | – | – | 1 |
| `[answer]` | `max_tokens` | `16000` | `16000` | `16000` | – | 3 (same value) |
| `[answer]` | `model` | `"claude-sonnet-5-5"` | `"claude-sonnet-5-5"` | `"claude-sonnet-5-5"` | – | 3 (same value) |
| `[answer]` | `query_parse_effort` | `"low"` | `"low"` | `"low"` | – | 3 (same value) |
| `[answer]` | `query_parse_model` | `"claude-haiku-5-5"` | `"claude-haiku-5-5"` | `"claude-haiku-5-5"` | – | 3 (same value) |
| `[answer]` | `side_sources` | `10` | – | – | – | 1 |
| `[answer]` | `summary_effort` | `"medium"` | `"medium"` | `"medium"` | – | 3 (same value) |
| `[answer]` | `summary_sources` | `24` | `24` | `24` | – | 3 (same value) |
| `[answer]` | `use_fallbacks` | `true` | `true` | `true` | – | 3 (same value) |
| `[archive]` | `archive_start_date` | – | `"1946-01-01"` | – | – | 1 |
| `[archive]` | `born_digital_from` | – | `1994` | – | – | 1 |
| `[archive]` | `default_years` | – | `10` | `4` | – | 2 |
| `[archive]` | `record_dirs` | `["debates", "westminhall", "lordspages", "wrans", "lordswrans", "wms", "lordswms", "standing"]` | – | – | – | 1 |
| `[archive]` | `start_date` | `"1997-05-01"` | `"1992-01-01"` | `"2018-05-01"` | – | 3 |
| `[auth]` | `required` | `false` | – | – | – | 1 |
| `[auth]` | `session_days` | `14` | – | – | – | 1 |
| `[coverage]` | `min_homes` | – | – | – | `1000` | 1 |
| `[embedding]` | `backend` | `"fastembed"` | `"fastembed"` | `"fastembed"` | – | 3 (same value) |
| `[embedding]` | `batch_size` | `8` | `8` | `8` | – | 3 (same value) |
| `[embedding]` | `dim` | `384` | `384` | `384` | – | 3 (same value) |
| `[embedding]` | `model` | `"snowflake/snowflake-arctic-embed-xs"` | `"snowflake/snowflake-arctic-embed-xs"` | `"snowflake/snowflake-arctic-embed-xs"` | – | 3 (same value) |
| `[embedding]` | `passage_words` | `250` | `250` | `250` | – | 3 (same value) |
| `[fetch]` | `min_interval_seconds` | – | – | – | `1.0` | 1 |
| `[fetch]` | `retries` | – | – | – | `3` | 1 |
| `[fetch]` | `timeout_seconds` | – | – | – | `60` | 1 |
| `[fetch]` | `user_agent` | – | – | – | `"Mozilla/5.0 (compatible; WhereLandlordsStand/0.1; +https://github.com/rj-mitchell/wherelandlordsstand)"` | 1 |
| `[groups]` | `show_ipsa` | `true` | – | – | – | 1 |
| `[live]` | `gd_bundled` | – | `"gd_website"` | – | – | 1 |
| `[live]` | `gd_from_session` | – | `79` | – | – | 1 |
| `[live]` | `gd_website` | – | `true` | – | – | 1 |
| `[live]` | `sc_after_meeting` | – | `9524` | – | – | 1 |
| `[live]` | `sc_from` | – | `"2024-01-01"` | – | – | 1 |
| `[modgov]` | `min_interval_seconds` | – | – | `1.0` | – | 1 |
| `[modgov]` | `read_documents` | – | – | `true` | – | 1 |
| `[modgov]` | `refetch_days` | – | – | `120` | – | 1 |
| `[modgov]` | `retries` | – | – | `3` | – | 1 |
| `[modgov]` | `timeout_seconds` | – | – | `40` | – | 1 |
| `[modgov]` | `timeouts_in_a_row` | – | – | `2` | – | 1 |
| `[modgov]` | `user_agent` | – | – | `"Mozilla/5.0 (compatible; WhereCouncilsStand/0.1; +https://github.com/rj-mitchell/wherecouncilsstand)"` | – | 1 |
| `[paths]` | `data_dir` | `"data"` | `"data"` | `"data"` | `"data"` | 4 (same value) |
| `[publish]` | `approval_days` | – | – | – | `14` | 1 |
| `[publish]` | `keep_builds` | – | – | – | `6` | 1 |
| `[publish]` | `mode` | – | – | – | `"approve"` | 1 |
| `[publish]` | `notify_to` | – | – | – | `"wheretheystanduk@gmail.com"` | 1 |
| `[ranking]` | `bm25_weight` | `0.5` | `0.5` | `0.5` | – | 3 (same value) |
| `[ranking]` | `candidates_bm25` | `300` | `300` | `300` | – | 3 (same value) |
| `[ranking]` | `candidates_frontbench` | `100` | – | – | – | 1 |
| `[ranking]` | `candidates_vector` | `300` | `300` | `300` | – | 3 (same value) |
| `[ranking]` | `default_recency` | `0.25` | `0.4` | `0.4` | – | 3 |
| `[ranking]` | `default_role_weight` | `1.5` | `1.3` | – | – | 2 |
| `[ranking]` | `local_factor` | `0.7` | – | – | – | 1 |
| `[ranking]` | `m_chair_match` | `1.0` | – | – | – | 1 |
| `[ranking]` | `m_chair_other` | `0.5` | – | – | – | 1 |
| `[ranking]` | `m_gov_match` | `1.0` | – | – | – | 1 |
| `[ranking]` | `m_gov_other` | `0.5` | – | – | – | 1 |
| `[ranking]` | `m_head` | – | `1.0` | – | – | 1 |
| `[ranking]` | `m_member_match` | `0.3` | – | – | – | 1 |
| `[ranking]` | `m_minister` | – | `0.7` | – | – | 1 |
| `[ranking]` | `m_representative` | – | `0.3` | – | – | 1 |
| `[ranking]` | `m_shadow_match` | `1.0` | – | – | – | 1 |
| `[ranking]` | `m_shadow_other` | `0.5` | – | – | – | 1 |
| `[ranking]` | `max_per_council` | – | – | `2` | – | 1 |
| `[ranking]` | `max_per_country` | – | `2` | – | – | 1 |
| `[ranking]` | `max_per_meeting` | – | – | `1` | – | 1 |
| `[ranking]` | `max_per_speaker` | `2` | `2` | – | – | 2 (same value) |
| `[ranking]` | `max_persistent` | `4` | – | – | – | 1 |
| `[ranking]` | `min_half_life_years` | `0.5` | `3.0` | `3.0` | – | 3 |
| `[ranking]` | `min_occasions` | `3` | – | – | – | 1 |
| `[ranking]` | `min_relevance_ratio` | `0.25` | `0.25` | `0.25` | – | 3 (same value) |
| `[ranking]` | `no_records_threshold` | `0.2` | – | – | – | 1 |
| `[ranking]` | `recency_floor` | `0.35` | `0.35` | `0.35` | – | 3 (same value) |
| `[ranking]` | `rerank_query` | `"both"` | – | – | – | 1 |
| `[ranking]` | `rerank_top` | `100` | – | – | – | 1 |
| `[ranking]` | `rerank_weight` | `0.6` | – | – | – | 1 |
| `[ranking]` | `vector_refine_factor` | `5` | `5` | `5` | – | 3 (same value) |
| `[regions]` | `devolved_nations` | `["Scotland", "Wales", "Northern Ireland"]` | – | – | – | 1 |
| `[regions]` | `midlands` | `["East Midlands", "West Midlands"]` | – | – | – | 1 |
| `[regions]` | `northern` | `["North East", "North West", "Yorkshire and The Humber"]` | – | – | – | 1 |
| `[regions]` | `southern` | `["London", "South East", "South West", "East of England"]` | – | – | – | 1 |
| `[robots]` | `obey` | – | – | `false` | – | 1 |
| `[sister_sites]` | `where_councils_stand` | – | – | – | `"https://wherecouncilsstand.com/councils/{gss}"` | 1 |
| `[sister_sites]` | `where_councils_stand_list` | – | – | – | `"https://wherecouncilsstand.com/api/councils"` | 1 |
| `[site]` | `contact` | – | – | – | `"admin@wherelandlordsstand.com"` | 1 |
| `[site]` | `dir` | – | `""` | – | – | 1 |
| `[site]` | `donate_url` | `"https://wheretheystand.uk/donate"` | – | `""` | – | 2 |
| `[site]` | `feedback_email` | – | – | – | `"admin@wherelandlordsstand.com"` | 1 |
| `[site]` | `launched` | – | – | – | `false` | 1 |
| `[site]` | `name` | – | – | `"Where Councils Stand"` | `"Where Landlords Stand"` | 2 |
| `[site]` | `operator` | – | – | – | `"Rob Mitchell"` | 1 |
| `[site]` | `parent_name` | – | – | – | `"Where They Stand"` | 1 |
| `[site]` | `stage` | – | – | – | `"alpha"` | 1 |
| `[site]` | `url` | – | `""` | `"https://wherecouncilsstand.com"` | `"https://wherelandlordsstand.com"` | 3 |
| `[sources]` | `compress_raw_xml` | `true` | – | – | – | 1 |
| `[sources]` | `parlparse_branch` | `"master"` | – | – | – | 1 |
| `[sources]` | `parlparse_repo` | `"https://github.com/mysociety/parlparse"` | – | – | – | 1 |
| `[sources]` | `sc_meta` | – | `"https://dataverse.harvard.edu/api/access/datafile/10809806"` | – | – | 1 |
| `[sources]` | `sc_speakers` | – | `"https://dataverse.harvard.edu/api/access/datafile/10809807"` | – | – | 1 |
| `[sources]` | `sc_speeches` | – | `"https://dataverse.harvard.edu/api/access/datafile/10809805"` | – | – | 1 |
| `[sources]` | `twfy_https` | `"https://www.theyworkforyou.com/pwdata/scrapedxml"` | – | – | – | 1 |
| `[sources]` | `twfy_rsync` | `"data.theyworkforyou.com::parldata/scrapedxml"` | – | – | – | 1 |
| `[sources]` | `undocs` | – | `"https://undocs.org/en/"` | – | – | 1 |
| `[sources]` | `ungd_guestbook` | – | `{"institution": "Where They Stand", "position": "Project lead", "purpose": "Research"}` | – | – | 1 |
| `[sources]` | `votes_record` | – | `"https://digitallibrary.un.org/record/4060887"` | – | – | 1 |
| `[sync]` | `times` | `["07:15", "19:15"]` | – | – | – | 1 |
| `[topics]` | `enabled` | `true` | – | – | – | 1 |
| `[topics]` | `file` | `"topics.toml"` | – | – | – | 1 |
| `[topics]` | `max_per_run` | `4` | – | – | – | 1 |
| `[topics]` | `unchanged_overlap` | `0.8` | – | – | – | 1 |
| `[usage]` | `answer_cache_hours` | `168` | `168` | `168` | – | 3 (same value) |
| `[usage]` | `briefing_estimate_usd` | – | `0.1` | `0.15` | – | 2 |
| `[usage]` | `briefings_at_once` | – | `8` | `8` | – | 2 (same value) |
| `[usage]` | `briefings_at_once_per_visitor` | – | `2` | `2` | – | 2 (same value) |
| `[usage]` | `cache_write_multiplier` | `1.25` | `1.25` | `1.25` | – | 3 (same value) |
| `[usage]` | `daily_spend_cap_usd` | `10.0` | `3.0` | `3.0` | – | 3 |
| `[usage]` | `monthly_spend_cap_usd` | `150.0` | `50.0` | `50.0` | – | 3 |
| `[usage]` | `per_user_daily_questions` | `60` | – | – | – | 1 |
| `[usage]` | `per_visitor_daily_questions` | `40` | `40` | `30` | – | 3 |
| `[usage]` | `price_cache_read_per_mtok` | `0.2` | `0.2` | `0.2` | – | 3 (same value) |
| `[usage]` | `price_input_per_mtok` | `4.0` | `2.0` | `2.0` | – | 3 |
| `[usage]` | `price_output_per_mtok` | `20.0` | `10.0` | `10.0` | – | 3 |
| `[usage]` | `requests_per_minute` | `20` | `20` | `20` | – | 3 (same value) |
| `[usage]` | `support_reminder_every` | `10` | – | – | – | 1 |
| `[usage.models."claude-haiku-5-5"]` | `price_cache_read_per_mtok` | `0.01` | `0.01` | `0.01` | – | 3 (same value) |
| `[usage.models."claude-haiku-5-5"]` | `price_input_per_mtok` | `0.1` | `0.1` | `0.1` | – | 3 (same value) |
| `[usage.models."claude-haiku-5-5"]` | `price_output_per_mtok` | `0.5` | `0.5` | `0.5` | – | 3 (same value) |
| `[usage.models."claude-sonnet-5-5"]` | `price_cache_read_per_mtok` | `0.2` | – | – | – | 1 |
| `[usage.models."claude-sonnet-5-5"]` | `price_input_per_mtok` | `2.0` | – | – | – | 1 |
| `[usage.models."claude-sonnet-5-5"]` | `price_output_per_mtok` | `10.0` | – | – | – | 1 |

Other files in `config/`:

| Site | File | Shape (top level) | Read by |
|---|---|---|---|
| MPs | `topics.toml` (134 lines) | 16 `[[topic]]` tables: `slug`, `title`, `area`, `question`, `description` (the header also documents an optional `refresh_days`, default 7) | `hansard/topics.py:49-50` |
| Landlords | `sources.toml` (208) | `ignore` (list); 16 `[[file]]`: `source`, `role`, `period`, `publisher`, `licence`, `govuk`, `match`, `types`, `notes`, `optional`, `keep_page`, `page`, `links`; 2 `[[watch]]`: `govuk` | `fetch.py:64, 306` |
| Landlords | `scoring.toml` (85) | `[peer_groups]` (`types`, `size_bands`, `min_group`, `[merge_type_into]`), `[scoring]` (`stock_types`, `min_peers`, `min_share`, `band_edges`, `bands`), `[headline]` (`measure`, `label`), `[pillars.repairs|heard|neighbourhood]` (`label`, `measures`), `[measures.<code>]` ×21 (`label`, `better`, `unit`), `[building_safety]` (`[measures]` BS01–BS05, `complete_at`), `[survey_method.labels]` | `score.py:57` |
| Landlords | `reconciliation.toml` (122) | `[tsm."2023/24"|"2024/25"|"2025/26"]`, `[ombudsman."2024-25"|"2025-26"]`, `[stock."2025/26"]` | `checks.py:304` |
| Landlords | `rights.toml` (108) | `heading`, `intro`, `not_advice`; 5 `[[section]]`: `heading`, `text`, `sources`, `checked`, `recheck`, `list`, `note` | `site_pages.py:398`, `checks.py:274` |
| Landlords | `pages.toml` (271) | `[about]`, `[terms]`, `[accessibility]`, `[named]`, `[press]`, `[status]`, `[not_found]` | `site_pages.py:341, 376, 431, 482, 543`, `status.py:94` |
| Landlords | `wording.toml` (267) | 20 tables of page wording: `site`, `footer`, `card`, `types`, `council_link`, `method`, `grade`, `bands`, `method_note`, `ombudsman`, `safety`, `areas`, `sources`, `search`, `area`, `compare`, `downloads`, `corrections`, `privacy`, `statement` | `site.py:542`, `statements.py:284`, `status.py:158` |

These six Landlords files and MPs' `topics.toml` are the site's own content, not shared settings; they were read by
their parsed outline, not line by line.

### Dependencies

Standard library only: `os`, `tomllib` (Python 3.11+), `dataclasses`, `datetime`, `functools`, `pathlib`. No
`tomli-w` or `tomli` in any `pyproject.toml` or `uv.lock`; MPs writes TOML by hand. All four declare
`requires-python = ">=3.12"` (`pyproject.toml:7`) and build on `python:3.12.15-slim`.

### Tests

| Site | Test | What it asserts |
|---|---|---|
| MPs | `tests/test_sync.py:261` `test_bootstrap_choices_are_remembered_for_later_syncs` | two `save_local_settings` calls merge; `load_settings()` then gives `archive_start == 2025-01-01`, `embedding.enabled is False`, and keeps `embedding.dim` from the main file |
| MPs | `tests/test_float16.py:264` `test_the_command_saves_the_measured_settings` | `vectors-f16` saves `vector_nprobes` and `vector_refine_factor`, and a fresh `load_settings` reads them |
| MPs | `tests/conftest.py:45-49` fixture `settings` | uses `HANSARD_DATA_DIR` and keyword overrides (exercised by most tests) |
| Countries | `tests/conftest.py:10-14` fixture `settings` | `WCS_DATA_DIR` and overrides (including `live.gd_bundled=""`); no test of the loader itself |
| Councils | no test of the loader; `tests/test_update.py:63` uses `load_settings(**{"modgov.read_documents": False})` | – |
| Landlords | `tests/test_common.py:33` `test_the_server_can_set_the_address_and_the_launch_switch` | `LANDLORDS_SITE_URL` and `LANDLORDS_LAUNCHED=true/false` reach `[site]` |

Only MPs tests the local file (writing and layering). Nobody tests: `<PREFIX>CONFIG`, a relative `data_dir`, the
one-level merge, or what `save_local_settings` does with a list or a string containing a quote.

### What a shared implementation must take as parameters

- the settings prefix (`HANSARD`, `WCS`, `COUNCILS`, `LANDLORDS`) for `_CONFIG` and `_DATA_DIR`;
- the repository root (today `parents[2]` of the module: a package installed elsewhere cannot work it out this way);
- whether to layer `settings.local.toml` (three sites yes; Landlords no today), and the name used in the writer's
  header comment (`hansard bootstrap`);
- a hook for a site's own environment overrides (Landlords' two);
- each site's own accessors stay in the site (a subclass or mixin of a shared `Settings` base holding `raw`,
  `data_dir`, `config_path`, `overrides`, `section()`), including the state database's file name
  (`state.sqlite` for MPs, `state.db` for the others).

---

## 2. Backup and restore

### What it does

Copies the site's SQLite state database with SQLite's online backup (safe while the site runs), compresses the copy
into the backups folder under a dated name, makes it readable by its owner only, and deletes all but the newest
`keep` of this site's backups. MPs and Countries can put a backup back.

### Public names and signatures

| Site | Where | Signature |
|---|---|---|
| MPs | `hansard/backup.py:21` | `PREFIX = "where-they-stand-"` |
| MPs | `hansard/backup.py:24` | `make_backup(settings: Settings, dest: Path \| None = None, keep: int = 14, day: str \| None = None) -> Path` |
| MPs | `hansard/backup.py:54` | `restore_backup(settings: Settings, archive: Path) -> None` |
| Countries | `wcs/backup.py:18` | `PREFIX = "wcs-state-"` |
| Countries | `wcs/backup.py:21` | `make_backup(state_db: Path, dest: Path, keep: int = 14, day: str \| None = None) -> Path \| None` |
| Countries | `wcs/backup.py:48` | `restore_backup(archive: Path, state_db: Path) -> Path \| None` (note: argument order is the reverse of MPs') |
| Councils | `councils/backup.py:17` | `PREFIX = "councils-state-"` |
| Councils | `councils/backup.py:20` | `make_backup(state_db: Path, dest: Path, keep: int = 14, day: str \| None = None) -> Path \| None` |
| Councils | – | no restore |
| Landlords | `landlords/cli.py:250-289` | no module: the `backup` command does it inline; `PREFIX = "landlords-state-"` lives in `landlords/offsite.py:28` and the literal is repeated at `cli.py:265` and `:278`. No restore |

Countries' and Councils' `make_backup` are the same statements (`wcs/backup.py:21-45`, `councils/backup.py:20-44`);
they differ only in `PREFIX`, the docstring and the comment on `chmod`.

### Differences

| # | What | MPs | Countries | Councils | Landlords | Class; best |
|---|---|---|---|---|---|---|
| 1 | Archive name | `where-they-stand-YYYY-MM-DD.tar.gz` (`backup.py:28`) | `wcs-state-YYYY-MM-DD.sqlite.gz` (`:26`) | `councils-state-YYYY-MM-DD.sqlite.gz` (`:25`) | `landlords-state-YYYYMMDD-HHMMSS.sqlite.gz` (`cli.py:264-265, 272`) | (b). All dates are UTC. Landlords' has a time, so two runs in a day make two files; the others overwrite that day's file |
| 2 | Format | gzipped tar holding `state.sqlite` and, if it exists, `settings.local.toml` (`:42-46`) | the database file, gzipped (`:39-40`) | the same (`:38-39`) | the same (`cli.py:272-273`) | (b): MPs "also keeps the local settings" (ENGINE.md) |
| 3 | No state database yet | not checked: `sqlite3.connect` **creates an empty `state.sqlite`** in the data folder and an empty database is archived as a good backup (`:31`; confirmed by a small experiment: a 0-byte source file is created and the copy passes `integrity_check`) | returns `None` (`:23-24`) | returns `None` (`:22-23`) | prints and returns (`cli.py:260-262`) | (a). Countries/Councils best: nothing is created and the command says so |
| 4 | Checking the copy | `PRAGMA integrity_check` on the copy; `RuntimeError("the backup copy failed its integrity check: {ok}")` (`:35, 39-40`) | the same (`:32, 36-37`) | the same (`:31, 35-36`) | **no check** (`cli.py:270-271`) | (a). The three; Landlords lacks it |
| 5 | Writing safely | copy and archive are made in a `TemporaryDirectory(dir=dest)`, then `partial.replace(out)` (`:29, 41, 48`) | the same (`:27, 38, 42`) | the same (`:26, 37, 41`) | uncompressed copy written straight into the backups folder as `landlords-state-<stamp>.sqlite`, gzip written straight to its final name, then the copy unlinked (`cli.py:265-277`): a kill leaves a stray `.sqlite` or a half-written `.sqlite.gz` that counts as the newest backup | (a). The three |
| 6 | Closing connections | `try/finally` closes both (`:33-38`) | the same (`:30-35`) | the same (`:29-34`) | `with sqlite3.connect(...) as a, ... as b:` (`cli.py:270`), which commits but does not close | (a), minor. The three |
| 7 | Permissions | `partial.chmod(0o600)` before the rename (`:47`) | the same (`:41`) | the same (`:40`) | `os.umask(0o077)` around the copy and gzip, then `os.chmod(..., 0o600)` (`cli.py:268-276`) | (c): same result, 0600. Landlords' umask also protects the uncompressed copy, which the others protect by the temporary folder's 0700 |
| 8 | Folder argument | `dest` optional; default `settings.data_dir / "backups"` (`:25`) | required | required | required (`--to`) | (b)/(c) |
| 9 | Pruning | `sorted(dest.glob(f"{PREFIX}*.tar.gz"))[:-keep] if keep > 0 else []` (`:49-50`) | same with `*.sqlite.gz` (`:43-44`) | same (`:42-43`) | `copies[:-keep]` with no guard (`cli.py:278-280`): `keep=0` deletes nothing (as the others), but a **negative `keep` deletes the oldest `-keep` files** (`copies[:2]` for `-2`), where the others delete nothing | (a), minor. The three |
| 10 | Return value | `Path` | `Path \| None` | `Path \| None` | – | follows #3 |
| 11 | Takes | the whole `Settings` (needs `state_db`, `data_dir`) | two paths | two paths | – | (c). Paths are the better interface for a shared package |
| 12 | Restore exists | yes (`:54-71`) | yes (`:48-82`) | **no** | **no** (its DEPLOY.md:111 gives a shell line: remove `-wal`/`-shm`, `gunzip -c … > /data/state.db`) | (a) for Councils and Landlords |
| 13 | Restore: where it unpacks | `tempfile.TemporaryDirectory()` in the system temporary folder, then `db.replace(settings.state_db)` (`:56, 68`). `Path.replace` cannot cross file systems; in the container `/tmp` is the container's own layer and `/data` a volume, so this should fail with "Invalid cross-device link". **Not verified on the server**; the test passes because both are under one `tmp_path` | `TemporaryDirectory(dir=state_db.parent)` (`:54`): same file system, so the rename is atomic | – | – | (a). Countries |
| 14 | Restore: order of steps | integrity check, then **deletes `-wal` and `-shm`** (`:66-67`), then the rename. If the rename fails (see 13), the live database has already lost its write-ahead log | everything is unpacked and checked first; `-wal`, `-shm` and `-journal` are removed only just before the rename (`:78-81`) | – | – | (a). Countries |
| 15 | Restore: what is checked | `integrity_check` only; failure message has no detail (`:61-62`). A tar without `state.sqlite` makes `sqlite3.connect` create an empty database, which passes, and **the live database is replaced with an empty one** | unreadable archive → `RuntimeError("{name} could not be read: {exc}")` (`:57-61`); not SQLite → `"{name} is not a database: {exc}"` (`:66-67`); `integrity_check` with detail (`:70-71`); must have the tables `usage` and `briefings`, else `"{name} is not a backup of this site's state database"` (`:72-73`) | – | – | (a). Countries |
| 16 | Restore: the database replaced | overwritten, nothing kept | copied beside itself as `state.db.before-restore` with `shutil.copy2` and its path returned (`:74-77`) | – | – | (a). Countries |
| 17 | Restore: journal files removed | `-wal`, `-shm` (`:66`) | `-wal`, `-shm`, `-journal` (`:78`) | – | – | (a). Countries |
| 18 | Restore: permissions | not set (as extracted from the tar) | `db.chmod(0o600)` (`:80`) | – | – | (a). Countries |
| 19 | Restore: accepts | a tar (any compression `tarfile.open` detects), extracted with `filter="data"` (`:57`) | `.gz` by suffix, or an uncompressed database file otherwise (`:56`), so `state.db.before-restore` can itself be restored | – | – | (b) format; Countries' second form is a convenience |
| 20 | Restore: local settings | puts `settings.local.toml` back if the archive has one (`:69-71`) | – | – | – | (b) |

### What an operator or reader would notice

**File names and places** (the folder is `/backups` in the container, `./backups` beside each site's compose file):

| | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| Pattern | `where-they-stand-2026-11-12.tar.gz` | `wcs-state-2026-11-12.sqlite.gz` | `councils-state-2026-11-12.sqlite.gz` | `landlords-state-20261112-045200.sqlite.gz` |
| Inside | tar: `state.sqlite`, `settings.local.toml` | raw SQLite file | raw SQLite file | raw SQLite file |
| Source database | `<data>/state.sqlite` | `<data>/state.db` | `<data>/state.db` | `<data>/state.db` |
| Mode | 0600 | 0600 | 0600 | 0600 |
| Kept locally (CLI default / what the unit passes) | 14 / 14 | 14 / 14 | 14 / **7** | 14 / 14 |
| Other files in the folder | `offsite.json` (section 3); a `tmp…` folder while running | the same | the same | `offsite.json`; `landlords-state-<stamp>.sqlite` while running |
| Left beside the database after a restore | – | `state.db.before-restore` | – | – |

**Messages and exit codes of the `backup` commands** are in section 5. Functions raise:

- all three modules: `RuntimeError("the backup copy failed its integrity check: {ok}")`, uncaught by every CLI
  (a traceback and exit 1);
- MPs restore: `RuntimeError("the backup's database failed its integrity check")`; `tarfile` and `OSError` errors
  uncaught;
- Countries restore: the three `RuntimeError` texts in row 15 and
  `RuntimeError("the backup's database failed its integrity check: {ok}")`.

**If one copy replaced another:** MPs with Countries' code would lose `settings.local.toml` from backups, change the
file name (which `deploy/check.sh:174` globs as `backups/where-they-stand-*.tar.gz`, the B2 prefix and the admin
page's alerts depend on), and stop creating an empty `state.sqlite` on a new site. Countries or Councils with MPs' code
would back up nothing-yet as an empty database, and restore without the safety checks. Landlords with any module copy
would lose the time in its file names (and with it the "(N kept)" count in its message, section 5) unless the name is
a parameter.

### Dependencies

Standard library only: `sqlite3`, `tempfile`, `datetime` (`UTC`: 3.11+), `pathlib`; MPs adds `tarfile`
(`extractall(filter="data")`: 3.12, or a patched 3.11.4+); Countries and Councils `gzip`, `shutil`; Landlords `gzip`,
`os`, `shutil`. MPs imports `hansard.config.Settings` (`backup.py:19`); the others import nothing from their site.

### Tests

| Site | Test | What it asserts |
|---|---|---|
| MPs | `tests/test_sync.py:272` `test_backup_is_a_checked_copy_and_restores` | the tar's members are exactly `settings.local.toml` and `state.sqlite`; three days with `keep=2` leave the two newest names; after a change, `restore_backup` brings back the earlier value |
| Countries | `tests/test_backup.py:10` `test_backup_copies_the_state_database_and_keeps_the_newest` | names kept with `keep=2`; mode 0600; the gunzipped file is a database with the row |
| Countries | `:27` `test_a_new_site_has_nothing_to_back_up` | the command exits 0 and says "nothing to back up" |
| Countries | `:42` `test_restore_puts_a_backup_back_and_keeps_the_database_it_replaces` | restored content; the kept `.before-restore` holds the replaced content; a leftover `state.db-journal` is removed |
| Countries | `:55` `test_restore_refuses_a_damaged_or_foreign_file_and_changes_nothing` | "not a database", "could not be read" (truncated gzip), "not a backup of this site" (wrong tables); the live database is untouched |
| Countries | `:77` `test_the_restore_command` | `restore <file> --yes` exits 0 and restores; a missing file exits 1 with "Not restored" |
| Councils | `tests/test_backup.py:10` and `:28` | the same two as Countries' first two (with `COUNCILS_DATA_DIR` set by hand) |
| Landlords | `tests/test_offsite.py:103` `test_the_backup_can_be_read_by_its_owner_only` | the command exits 0; exactly one `landlords-state-*.sqlite.gz`, mode 0600; no `.sqlite` left |

Tested in one site only: the local settings in the archive (MPs); restore's refusals, the kept copy and the journal
(Countries); the new-site case (Countries, Councils); the stray uncompressed copy (Landlords). Not tested anywhere:
a failed integrity check, `keep=0`, two backups in one day, Landlords' pruning, MPs' restore from a different file
system, MPs' backup with no database.

### What a shared implementation must take as parameters

- the state database's path (`state.sqlite` or `state.db`) and the backups folder;
- the file-name prefix (`where-they-stand-`, `wcs-state-`, `councils-state-`, `landlords-state-`);
- the date stamp's format (`%Y-%m-%d`, or Landlords' `%Y%m%d-%H%M%S`);
- the format: gzip of the database, or MPs' tar with a list of extra files to include (`settings.local.toml`) and the
  member name of the database (`state.sqlite`); hence the suffix (`.sqlite.gz` or `.tar.gz`) used in globs;
- `keep` (14, 14, 7 by its unit, 14);
- for restore: the tables a backup must contain (Countries: `usage`, `briefings`; the other sites' were not read),
  and whether to keep the replaced database (`<name>.before-restore`).

---

## 3. Off-site copies to Backblaze B2

### What it does

Speaks B2's native HTTP API with `httpx` (no SDK). `send()` authorises with the key, uploads the archive with its
SHA-1, deletes all but the newest `keep` of **this site's** files (those whose names start with the site's `PREFIX`),
and records the outcome in `offsite.json` beside the archive. `check()` reports whether the key works and what is in
the bucket. `backup_alerts()` (not in Landlords) reads the backups folder and `offsite.json` and returns warnings.

### Public names and signatures

The same in all four, apart from line numbers (MPs' docstring is one line shorter, so Countries, Councils and
Landlords are one line later from line 9 on):

| Name | MPs `hansard/offsite.py` | Countries / Councils / Landlords |
|---|---|---|
| `AUTHORIZE = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"` | :31 | :32 |
| `KEEP = 60` | :32 | :33 |
| `class OffsiteError(RuntimeError)` | :35 | :36 |
| `configured(env: dict[str, str] \| None = None) -> dict[str, str] \| None` | :39-42 | :40-43 |
| `class B2: __init__(self, bucket: str, key_id: str, application_key: str, client: httpx.Client \| None = None)` | :45-61 | :46-62 |
| `B2.close() -> None` | :63 | :64 |
| `B2._call(name: str, body: dict[str, Any]) -> dict[str, Any]` | :67 | :68 |
| `B2._find_bucket() -> str` | :73 | :74 |
| `B2.upload(path: Path, tries: int = 3) -> dict[str, Any]` | :79-92 | :80-93 |
| `B2.backups() -> list[dict[str, Any]]` | :94-97 | :95-98 |
| `B2.prune(keep: int = KEEP) -> int` | :99-103 | :100-104 |
| `_status(dest: Path, status: dict[str, Any]) -> None` | :106-108 | :107-109 |
| `send(archive: Path, *, keep: int = KEEP, env: dict[str, str] \| None = None, client: httpx.Client \| None = None) -> dict[str, Any]` | :111-136 | :112-137 |
| `check(env: dict[str, str] \| None = None, client: httpx.Client \| None = None) -> dict[str, Any]` | :139-151 | :140-152 |
| `backup_alerts(folder: Path, env: dict[str, str] \| None = None, now: datetime \| None = None, stale_hours: int = 50) -> list[dict[str, str]]` | :154-181 | Countries :155-185; Councils :155-184; **Landlords: absent** |
| `PREFIX` | imported from `hansard.backup` (:27) | Countries, Councils: imported from their `backup` (:28); Landlords: defined here, `"landlords-state-"` (:28) |

### Differences

After making names and prefixes the same, everything from `AUTHORIZE` to the end of `check()` is identical in all four
(the helper's diff shows only the rows below).

| # | What | MPs | Countries | Councils | Landlords | Class; best |
|---|---|---|---|---|---|---|
| 1 | `backup_alerts` exists | yes `:154-181` | yes `:155-185` | yes `:155-184` | **no** | (a) for Landlords |
| 2 | Local glob in `backup_alerts` | `{PREFIX}*.tar.gz` `:162` | `{PREFIX}*.sqlite.gz` `:165` | `{PREFIX}*.sqlite.gz` `:165` | – | (b), follows the archive format |
| 3 | Alert wording | sentence case with a full stop | lower case, no full stop; the stale-backup text adds `: is wcs-backup.timer running?` `:169-170` | as MPs, word for word | – | (b): MPs' go on the admin page, Councils' are printed by `backup-check`, Countries' follow `warning: backup:` in the update report |
| 4 | Failed-copy text when `when` is not a string | `status.get('when', '')[:16]` `:177` (a number would raise `TypeError`) | `str(status.get('when', ''))[:16]` `:181` | as MPs `:180` | – | (a), small. Countries |
| 5 | Module docstring: "The charity's sites can share one bucket and key: each site's backups have their own name (``PREFIX``), and only its own old copies are deleted." | absent (`:9`) | present (`:9-10`) | present | present | (c), but worth porting: it is true of MPs' code too |
| 6 | Where `PREFIX` is defined | `backup.py` | `backup.py` | `backup.py` | `offsite.py:28`, with the literal repeated in `cli.py` | (c) |
| 7 | Who calls `backup_alerts` | the admin page: `GET /api/admin/usage` adds them to `alerts`, folder from `HANSARD_BACKUP_DIR`, default `/backups` (`api/app.py:1947-1951`). **Nothing emails them** | each `wcs update`: `update.py:490-499` sets `report.backups`, folder from `WCS_BACKUP_DIR` or `/backups`; an `error` level makes `needs_attention` true (`update.py:81-83`), the command exits 1 (`cli.py:192-193`) and the unit's failure is emailed; printed as `{level}: backup: {text}` (`cli.py:190-191`); kept out of `/api/status` | the `backup-check` command, daily by its own timer (`cli.py:217-236`; `deploy/councils-backup-check.*`), exit 1 on any `error` | – | (a) for MPs and Landlords: a stopped backup timer is emailed in Countries and Councils only. Councils' separate check is the cleanest (it does not depend on the update running, and the update's exit code keeps one meaning) |
| 8 | Empty `…_BACKUP_DIR` | `os.environ.get("HANSARD_BACKUP_DIR", "/backups")`: an empty value gives `Path("")`, the working folder (`api/app.py:1949`) | `os.environ.get("WCS_BACKUP_DIR") or "/backups"` (`update.py:497`) | no variable; `--in`, default `/backups` | – | (a), tiny. Countries |

### What an operator or reader would notice

Everything here is the same in all four unless a site is named.

**Environment variables:** `<PREFIX>B2_BUCKET`, `<PREFIX>B2_KEY_ID`, `<PREFIX>B2_APPLICATION_KEY`. Values are
stripped; all three must be non-empty or off-site copies are "not set up". (MPs' names are the legacy ones the other
sites copy from, per `family/OPERATIONS.md`.) Also `HANSARD_BACKUP_DIR` and `WCS_BACKUP_DIR` (row 7).

**Requests:** `GET` `AUTHORIZE` with basic auth; `POST {apiUrl}/b2api/v2/b2_list_buckets` (only when the key is not
limited to a bucket), `b2_get_upload_url`, `b2_list_file_names` (`prefix` = `PREFIX`, `maxFileCount` 1000, **one
page only**), `b2_delete_file_version`. Upload headers: `X-Bz-File-Name` (URL-quoted file name), `Content-Type:
application/gzip`, `X-Bz-Content-Sha1`. The whole archive is read into memory. Timeout 300 seconds when the module
makes its own client. Up to `tries=3` uploads, each with a fresh upload address.

**Retention:** `KEEP = 60` files with the site's prefix, oldest by name deleted first; `keep <= 0` deletes nothing.
No CLI passes `keep`, so 60 is fixed in all four. For Landlords 60 files is 60 runs, not 60 days.

**`offsite.json`** (in the archive's folder; written with default permissions; a write error is ignored):

- success: `{"ok": true, "when": "<UTC ISO, seconds, +00:00>", "file": "<archive name>", "bucket": "<bucket>", "stored": <files with the prefix after pruning>, "deleted": <number pruned>}`;
- failure: `{"ok": false, "when": "…", "error": "<first 300 characters>"}`;
- not written at all when off-site copies are not set up.

**Return values:** `send` → `{"offsite": "not set up"}` or the success status; `check` →
`{"ok": false, "error": "not set up: add <P>B2_BUCKET, <P>B2_KEY_ID and <P>B2_APPLICATION_KEY to deploy/.env"}` or
`{"ok": true, "bucket": …, "backups": <count>, "newest": <name or null>}`.

**Error texts** (`OffsiteError`):

- `Backblaze did not accept the key: check <P>B2_KEY_ID and <P>B2_APPLICATION_KEY` (authorise returns 401 or 403);
- `the key is for the bucket '<theirs>', not '<ours>'`;
- `there is no bucket called '<name>' that this key can see`;
- `<api call>: <status> <first 200 characters of the reply>`;
- `upload failed: <status> <first 200 characters>`.

`send` turns `OffsiteError` and `httpx.HTTPError` into `OffsiteError` after writing the failure status. A pruning
failure is only logged (`old off-site backups not deleted: %s`, at warning, logger `<package>.offsite`) and the copy
still counts as stored. **`check` catches nothing:** a wrong key or no network makes the `offsite` command end in a
traceback.

**Alert conditions** (`backup_alerts`; `stale_hours=50`; texts as in MPs and Councils, Countries' in brackets where
they differ beyond case and the full stop):

| Condition | Level | Text |
|---|---|---|
| the folder does not exist | – | no alerts at all |
| no local file matches the glob | warning | `No backups have been made yet.` |
| newest local file's modification time is over 50 hours old | error | `The last backup was made over two days ago (<name>).` (Countries: `the last backup was made over two days ago (<name>): is wcs-backup.timer running?`) |
| B2 not set up | warning | `Backups are kept on this server only: no off-site copy is set up.` Nothing further is checked |
| there are local backups but `offsite.json` is missing or unreadable | warning | `No off-site copy has been made yet; one is made with the next backup.` |
| `offsite.json` says `ok` false | error | `The last off-site copy failed (<when, first 16 characters>): <error>` (no full stop in any copy) |
| `offsite.json` `ok` and `when` over 50 hours old | error | `The last off-site copy was over two days ago (<when, first 10 characters>).` |

"Newest" is by file name, age by modification time. A status with `ok` true and no `when` raises `KeyError` in all
three copies; a `when` without a time zone raises `TypeError`.

### Dependencies

Third party: `httpx` only (declared `httpx>=0.27` in all four `pyproject.toml`, locked at 0.28.1 in all four
`uv.lock`; `httpcore` 1.0.9). Standard library: `contextlib`, `hashlib`, `json`, `logging`, `os`, `urllib.parse`,
`datetime`, `pathlib`. **No `b2sdk` or `boto3`** in any `pyproject.toml` or `uv.lock`. The only site import is
`PREFIX` from the site's `backup` module (not in Landlords).

### Tests

`tests/test_offsite.py` in each site, built on the same `FakeB2` (an `httpx.MockTransport`):

| Test | MPs | Countries | Councils | Landlords | Asserts |
|---|---|---|---|---|---|
| `test_not_set_up_does_nothing` | :59 | :57 | :59 | :57 | `configured({})` is `None`; `send` returns `{"offsite": "not set up"}`; `check` has `ok` false |
| `test_upload_retries_and_keeps_the_newest` | :65 | :63 | :65 | :63 | one failed upload is retried; with `keep=2` three days leave two; `stored == 2`, `deleted == 1`; `offsite.json` is `ok`; `check`'s exact result |
| `test_a_key_without_delete_rights_still_stores` | :77 | :75 | :77 | :75 | a 401 on delete still gives `stored == 2` |
| `test_failures_are_reported_and_recorded` | :84 | :82 | :84 | :82 | a wrong key raises "did not accept the key"; the status is `ok` false and never contains the key; a key for another bucket raises "bucket" |
| `test_sites_sharing_a_bucket_keep_their_own_backups` | **absent** | :93 | :95 | :93 | a `where-they-stand-…` file in the bucket is neither counted nor deleted |
| `test_admin_alerts` | :95 | – | – | – | missing folder → `[]`; "No backups"; a 3-day-old file with no B2 → "over two days ago" and "server only"; a failed status → error; a fresh good status → `[]` |
| `test_backup_alerts` | – | `tests/test_backup.py:86` (exact texts, with a fixed `now`; also the stale off-site copy and "no off-site copy has been made yet") | :105 (as MPs' plus the stale off-site copy and the "No off-site copy has been made yet" case) | – | – |
| `test_backup_check_command_exits_1_when_backups_are_stale` | – | – | :127 | – | missing folder → exit 1; a fresh backup with no B2 → exit 0 with "server only" (a warning); a 3-day-old backup → exit 1 with "over two days ago" |
| `test_a_stopped_backup_makes_the_update_need_attention_but_not_the_public_status` | – | `tests/test_backup.py:118` | – | – | a very old backup makes `report.needs_attention` true while `report.ok` stays true |
| `test_status_keeps_the_backups_private` | – | `tests/test_api.py:548` | – | – | `/api/status` shows neither the word `backups` nor the alert's text |

Cases one site tests and others do not: the shared bucket (missing from MPs, the upstream copy); the stale off-site
copy and the not-yet-made copy (Countries, Councils; not MPs); exact alert texts (Countries only). Not tested
anywhere: a bucket found by `b2_list_buckets`, more than 1,000 files, `check` with a bad key, an unwritable
`offsite.json`, MPs' admin endpoint including backup alerts.

### What a shared implementation must take as parameters

- the settings prefix (for the three variable names and the two error texts that name them);
- the file prefix (`PREFIX`) for listing and pruning in the bucket;
- for alerts: the local glob's suffix (`.tar.gz` or `.sqlite.gz`), `stale_hours`, and the wording (MPs/Councils'
  sentences, or Countries' lower-case ones with its timer's name: either a style switch or the caller formats);
- `keep` (60 everywhere today) and the content type (always `application/gzip`).

---

## 4. The thread-safe DuckDB wrapper

### What it does

`SharedConnection` holds one DuckDB connection and gives each thread its own cursor on it (kept in
`threading.local`), so views, tables and settings are shared while results and registered Arrow tables belong to
the thread. Any attribute not found on the wrapper is fetched from the calling thread's cursor, so it is used like a
connection. `shared(con)` wraps a connection, returns a `SharedConnection` unchanged, or opens a new in-memory
database.

### Public names and signatures

MPs `hansard/store/shared.py` and Countries `wcs/store/shared.py` are **identical, byte for byte after
normalising** (35 lines; the helper prints no difference):

- `class SharedConnection` :11; `__init__(self, con: duckdb.DuckDBPyConnection | None = None)` :19-21;
  `cursor_for_thread(self) -> duckdb.DuckDBPyConnection` :23-27; `__getattr__(self, name: str) -> Any` :29-30;
- `shared(con: duckdb.DuckDBPyConnection | SharedConnection | None = None) -> SharedConnection` :33-35.

Who uses it:

| Site | Callers |
|---|---|
| MPs | `engine.py:148` (then `SET enable_object_cache = true` through it, :149), `votes.py:37` (`shared(con)`), `reference/profiles.py:217` (`shared(con)`), `vote_types.py:206`, `debates.py:87`, `week.py:41`, `trends.py:74`, `people.py:83` |
| Countries | `votes.py:42` only (`VoteFinder`, one per site, used by every request's thread) |
| Councils | no `store/shared.py`. DuckDB is used with a **new connection each time**: `api/data.py:198` (`_build_directory`, run under `threading.Lock`, `:165, 180`) and `:266` (`vote_ids`); `pilot.py:55, 123` (command line). `store/parquet.py:132-140` `attach(con, root)` makes a view per table. Per-council reads use PyArrow, not DuckDB (`store/parquet.py:127-129`). Results are cached in Python, so no connection is shared between threads |
| Landlords | no DuckDB in `src/` at all (it reads and writes Parquet with PyArrow and state with `sqlite3`). `duckdb>=1.1` is still a declared dependency (`pyproject.toml:9`) and is used only by `tests/test_data.py:48-57` (`duckdb.sql`) |

MPs and Countries also open plain one-off connections where no sharing is needed (for example MPs
`store/parquet.py:130`, `cli.py:544`; Countries `api/app.py:313`, `update.py:103`, `sources/votes.py:95`).

### Differences

None between the two copies. Nothing to port between them.

### What an operator or reader would notice

Nothing visible. For a reader of the code: cursors are never closed (one per thread for the life of the process);
`register()` on the wrapper registers for the calling thread only (the test asserts this); wrapping an existing
connection does not protect code that still uses that connection directly.

### Dependencies

`duckdb` only (plus `threading`, `typing`). Declared `duckdb>=1.1` in all four `pyproject.toml` (MPs :11, Countries
:10, Councils :10, Landlords :9). **Locked versions differ: MPs 1.5.6; Countries, Councils and Landlords 2.0.0**
(`uv.lock`). The wrapper uses only `duckdb.connect()` and `connection.cursor()`. The test also needs `pyarrow`
(locked 26.0.0 in MPs, Countries and Councils; 26.0.1 in Landlords).

### Tests

| Site | Test | What it asserts |
|---|---|---|
| MPs | `tests/test_shared_connection.py:6` `test_threads_get_their_own_results` | six threads each run a parameterised query 20 times on one wrapper and always get their own answer |
| MPs | `:27` `test_views_and_settings_are_shared_registrations_are_not` | a view made in one thread is seen in another; an Arrow table registered in one is not; `shared(con) is con` for a wrapper |
| Countries | no test of the module. Indirectly `tests/test_rag.py:115` `test_votes` (lines 135-141): one `VoteFinder` queried 64 times from 8 threads gives the same result each time | – |

MPs' two tests have no counterpart in Countries.

### What a shared implementation must take as parameters

Nothing: it has no site-specific input. The package must settle one DuckDB major version (1.x in MPs, 2.x elsewhere),
or allow both.

---

## 5. How they are invoked: commands, units, timers

### Commands

Logging differs and changes what a warning looks like: MPs' commands call `_setup_logging()` (INFO, format
`%(asctime)s %(levelname)s %(name)s: %(message)s`, `cli.py:56-60`); the other three set WARNING with
`%(levelname)s %(message)s` in the app callback, INFO with `--verbose`/`-v` (`wcs/cli.py:39-41`,
`councils/cli.py:34-36`, `landlords/cli.py:34-36`). MPs has no `--verbose`.

**`backup`**

| | MPs `hansard/cli.py:717-733` | Countries `wcs/cli.py:196-217` | Councils `councils/cli.py:171-192` | Landlords `landlords/cli.py:250-289` |
|---|---|---|---|---|
| Options | `--to PATH` (optional; help "folder for backups (default: <data>/backups)"), `--keep INT` = 14 ("how many daily backups to keep") | `--to TEXT` (required; "folder for the backups"), `--keep` = 14 ("how many to keep") | as Countries | `--to PATH` (required; "folder for the copies"), `--keep` = 14 (no help) |
| No database | (creates an empty one and backs it up) | `nothing to back up yet (no state database)`, exit 0 | the same | `No state database yet: nothing to back up.`, exit 0 |
| Success line | `Backed up to <path>` | `backup: <path>` | `backup: <path>` | `Backed up to <path>.gz (<n> kept)` |
| Off-site, stored | `Off-site copy: stored in <bucket> (<stored> kept there)` | the same | the same | `Off-site copy: stored in <bucket>` |
| Off-site, not set up | `Off-site copy: not set up` | the same | the same | the same |
| Off-site, failed | `The off-site copy failed: <error>` on **stderr**, exit 1 | the same | the same | `Off-site copy failed: <error>` on **stdout**, exit 1 |
| Integrity failure | traceback, exit 1 | traceback, exit 1 | traceback, exit 1 | not checked |

The local backup exists even when the off-site copy fails and the command exits 1.

**`restore`**

| | MPs `hansard/cli.py:745-754` | Countries `wcs/cli.py:220-238` |
|---|---|---|
| Argument | `ARCHIVE` as a path that must exist and be a file (Typer's own error and exit 2 otherwise) | `ARCHIVE` as text (help "a backup: /backups/wcs-state-YYYY-MM-DD.sqlite.gz") |
| `--yes` | "do not ask for confirmation" | "don't ask first" |
| Question | `This replaces the current saved briefings, reports and usage records. Continue?`; "no" prints Typer's `Aborted.` and exits 1 | `Replace <state_db> with <archive>? Stop the site first.`; "no" exits 1 silently |
| Success | `Restored. Start the site again.` | `restored <state_db> from <archive>` and, if a database was replaced, `; the database it replaced is <path>` |
| Failure | traceback | `Not restored: <reason>` on stderr, exit 1 (`OSError` and `RuntimeError`) |

Councils and Landlords have no `restore` command.

**`offsite`** (MPs `cli.py:736-742`; Countries `:241-246`; Councils `:348-353`; Landlords `:292-297`): prints
`json.dumps(check(), indent=2)`. Exit 0 even when not set up (`"ok": false`); a traceback if Backblaze refuses the
key or cannot be reached. Docstrings: MPs "…how many backups are stored there."; the others "…how many of this
site's backups are there."

**`backup-check`** (Councils only, `councils/cli.py:217-236`): `--in TEXT` = `/backups` ("the folder the backups are
written to"). No folder: `error: there is no backup folder at <path>` on stderr, exit 1. Otherwise one line per alert,
`<level>: <text>` (errors on stderr, warnings on stdout); `Backups are up to date.` when there are none; exit 1 if any
alert is an error.

**Settings commands** (MPs only; no site has a general "settings" command):

- `hansard bootstrap` (`cli.py:651-663`): `--from` and `--keyword-only` are remembered in `settings.local.toml`
  (`bootstrap.py:78-85`); `--sample` writes the demo file (`bootstrap.py:66-68`).
- `hansard reindex-vectors` (`cli.py:243-270`) and `hansard vectors-f16` (`:331-397`) save the measured
  `ranking.vector_nprobes` and `ranking.vector_refine_factor` (`_save_vector_settings`, `:278-283`), report the file
  as `"settings_file"` in their JSON, and print `RESTART_NOTE` (`:274-275`): "Restart the app to search with the new
  index settings: in /opt/hansardgpt/deploy, docker compose restart app".
- `hansard set-key` (`cli.py:669-699`) saves the Anthropic key to a file in the data folder (mode 0600); it does not
  touch settings files and was not studied further.

### Units, timers and scripts

All backup units: `Type=oneshot`, `After=` and `Requires=docker.service`, `OnFailure=alert@%n.service`, `Nice=10`,
run from the site's `deploy/` folder. `alert@.service` and `alert.sh` live in MPs' `deploy/` and email at most once in
six hours per unit (`deploy/alert.sh:15`).

| | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| Service | `deploy/hansard-backup.service` | `deploy/wcs-backup.service` | `deploy/councils-backup.service` | `deploy/landlords-backup.service` |
| `Description=` | `Where MPs Stand daily backup (saved briefings, reports, usage)` | `Where Countries Stand: back up the state database` | `Where Councils Stand: back up the state database` | `Where Landlords Stand: back up the state database` |
| `WorkingDirectory=` | `/opt/hansardgpt/deploy` | `/opt/wherecountriesstand/deploy` | `/opt/wherecouncilsstand/deploy` | `/opt/wherelandlordsstand/deploy` |
| `ExecStart=` | `/usr/bin/docker compose run --rm -T app hansard backup --to /backups --keep 14` (:10) | `… app wcs backup --to /backups --keep 14` (:13) | `… app councils backup --to /backups --keep 7` (:14) | `… app landlords backup --to /backups --keep 14` (:13) |
| `TimeoutStartSec=` | `30min` | `30min` | `30min` | `10min` |
| Timer | `hansard-backup.timer` | `wcs-backup.timer` | `councils-backup.timer` | `landlords-backup.timer` |
| `OnCalendar=` | `*-*-* 03:30:00 Europe/London` | `*-*-* 04:20:00 UTC` | `*-*-* 04:30:00 UTC` | `*-*-* 04:52:00 UTC` |
| `RandomizedDelaySec=` | `300` | none | none | none |
| `Persistent=` | `true` | `true` | `true` | `true` |
| Backups folder | `./backups:/backups` (`docker-compose.yml:22`) | the same (:25) | the same (:25) | the same (:25) |
| Installed by | `deploy/update.sh:25-36` and `deploy/provision.sh:113-121` (which also makes `backups/`) | `deploy/update.sh:23-25` (`mkdir -p backups` :28) | `deploy/update.sh:23-26` (:29) | `deploy/update.sh:23-25` (:28) |
| Kept locally | 14 | 14 | 7 | 14 |
| Kept in B2 | 60 | 60 | 60 | 60 |
| Stopped-backup check | none emailed; the admin page shows alerts | each update (twice a day) exits 1 on an error-level alert | `councils-backup-check.service` / `.timer`: `docker compose run --rm --no-deps -T app councils backup-check --in /backups`, `*-*-* 11:47:00 UTC`, `Persistent=true`, `TimeoutStartSec=10min` | none |
| Other scripts that know the names | `deploy/check.sh:167` (the two timers), `:174` (`ls -1t backups/where-they-stand-*.tar.gz`), `:175` ("no backups yet (the first runs at 3.30am)") | none | none | none |

Every `update.sh` hands `/data` and `/backups` to user 10001 if anything there is owned by someone else (MPs
`:59-65`; Countries `:32-38`; Councils `:33-39`; Landlords `:32-38`), which is what lets the non-root container write
backups. No unit or script runs `restore` or `offsite`; they are run by hand (MPs `docs/HOSTING.md:723`:
`docker compose run --rm -T app hansard restore /backups/where-they-stand-2026-10-11.tar.gz --yes`).

`.env.example` in each `deploy/` lists the three B2 variables (MPs :21-23; Countries :18-20; Councils :9-11;
Landlords :19-21); the three later sites say to copy them from MPs' settings.

### Tests of the commands and deploy files

Covered above where they exist (Countries' `backup` and `restore` commands; Councils' `backup` and `backup-check`;
Landlords' `backup`). MPs has **no test of its `backup`, `restore` or `offsite` commands** (only of the functions).
No site tests its `offsite` command. Deploy files: MPs `tests/test_watchdog.py:200` `test_deploy_scripts_parse` and
Landlords `tests/test_mail.py:94` `test_the_server_scripts_parse` run `bash -n` on every `deploy/*.sh`; Countries and
Councils have no such test. No site tests its unit or timer files.

### What a shared implementation must take as parameters

The command name and help texts, the site's messages (four wordings of each line above), where errors go (stderr or
stdout), and for units: the folder under `/opt`, the command, `--keep`, the time and its time zone, the timeout. A
shared package can supply the functions and perhaps a Typer sub-app; unit files stay in each site.

---

## 6. Ports worth making now

Fixes present in one copy and missing from another. Source first, then destination.

1. **Safe restore.** `wcs/backup.py:48-82` (unpack beside the database, check before touching anything, required
   tables, keep `.before-restore`, remove `-journal` too, mode 0600, readable errors) and `wcs/cli.py:220-238` →
   MPs `hansard/backup.py:54-71` and `hansard/cli.py:745-754`, keeping MPs' tar format and its `settings.local.toml`.
   Tests to bring: Countries `tests/test_backup.py:42, 55, 77`.
2. **A restore at all.** The same source → Councils (`councils/backup.py`, after :44; a command beside
   `councils/cli.py:171`) and Landlords (`landlords/cli.py`, after :289), each with its own required tables.
3. **Nothing to back up on a new site.** `wcs/backup.py:23-24` (and the message, `wcs/cli.py:207-209`) →
   MPs `hansard/backup.py:24-31` and `hansard/cli.py:725-726`. Test: Countries `tests/test_backup.py:27`.
4. **Landlords' backup made as the others'.** `councils/backup.py:26-43` (temporary folder, integrity check, atomic
   rename, closed connections, guarded pruning) → `landlords/cli.py:263-280`, keeping its file-name pattern.
5. **Backup alerts for Landlords.** `councils/offsite.py:155-184` → end of `landlords/offsite.py` (after :152), with
   the `backup-check` command (`councils/cli.py:217-236`) and its unit and timer
   (`deploy/councils-backup-check.service`, `.timer`; `deploy/update.sh:23-26`) → Landlords' `cli.py` and `deploy/`.
   Tests: Councils `tests/test_offsite.py:105, 127`.
6. **An emailed stopped-backup check for MPs.** The same `backup-check` command and units → `hansard/cli.py` (beside
   :736) and MPs' `deploy/` (installed at `deploy/update.sh:25-36`). Today MPs' alerts are seen only by someone who
   opens the admin page (`hansard/api/app.py:1947-1951`).
7. **`str()` around `when`.** `wcs/offsite.py:181` → `hansard/offsite.py:177` and `councils/offsite.py:180`.
8. **The shared-bucket test and sentence.** Countries `tests/test_offsite.py:93-100` → MPs `tests/test_offsite.py`
   (after :92); docstring `wcs/offsite.py:9-10` → `hansard/offsite.py:9`.
9. **The stale off-site copy cases in MPs' alert test.** Councils `tests/test_offsite.py:105-124` →
   MPs `tests/test_offsite.py:95-108`.
10. **The wrapper's tests.** MPs `tests/test_shared_connection.py` → Countries `tests/` (it has none of its own).
11. **Empty `HANSARD_BACKUP_DIR`.** `wcs/update.py:497` (`… or "/backups"`) → `hansard/api/app.py:1949`.
12. **`family/ENGINE.md`:** correct the two rows named at the top of this page, and consider Countries as upstream
    for restore.

## 7. Open questions

1. **Does MPs' `restore` work on the server?** It unpacks in the system temporary folder and renames into `/data`
   (`hansard/backup.py:56, 68`). If those are different file systems in the container, as the compose file suggests,
   the rename fails after `-wal` and `-shm` have been deleted. Not tested here; worth one trial on a copy.
2. **Which tables must each site's backup contain** for a restore to accept it? Countries checks `usage` and
   `briefings`. MPs', Councils' and Landlords' state schemas were not read.
3. **Should the other sites' backups carry `settings.local.toml`?** Countries and Councils read the file but nothing
   on the server writes it; if a shared package brings `save_local_settings` to them, their gzip-of-a-database format
   has no room for it.
4. **Landlords' file names carry a time** (`%Y%m%d-%H%M%S`), so `--keep 14` and B2's 60 count runs, not days. Keep
   that, or move to one a day like the others (which changes names in the bucket and in its DEPLOY.md)?
5. **Councils keeps 7 locally** by its unit, while the command's default and its docstring's "newest `keep`" say 14;
   `family/OPERATIONS.md` agrees with 7. Deliberate (its database is larger?) or drift? The code does not say.
6. **Three wordings of the alerts.** Are Countries' lower-case texts and its "is wcs-backup.timer running?" to be
   kept exactly? Its tests assert them word for word (`tests/test_backup.py:98-99, 110-111`).
7. **Should `offsite` exit non-zero** when not set up or when the key is refused? Today it exits 0 for the first and
   ends in a traceback for the second, in all four.
8. **B2 lists one page of 1,000 files.** At 60 kept per site this is never reached, but nothing checks.
9. **Does Landlords need the local-settings layer and keyword overrides,** or should a shared loader make them
   optional? Nothing in Landlords uses either today.
10. **`load_toml` ignores `LANDLORDS_CONFIG`** while MPs' `topics.toml` follows `HANSARD_CONFIG`. Which rule should a
    shared "sibling file in config/" helper follow?
11. **DuckDB 1.5.6 (MPs) and 2.0.0 (the rest).** The wrapper's two calls exist in both, but the package and its
    tests need one answer. Landlords declares DuckDB and uses it only in a test.
12. **`REPO_ROOT` is found from the module's own path.** A shared package installed outside the repository needs the
    site to say where its root is; how (an argument, an environment variable) is a design choice.
13. **MPs' backup runs at 03:30 UK time, the others in UTC**, and all name files by the UTC date; around midnight
    UTC nothing runs, so no clash was found, but the mixed clocks are worth knowing.

## 8. What was not read

- The state database modules (`hansard/store/state.py`, `wcs/api/usage.py`, `councils/api/state.py`,
  `landlords/api.py`): only their paths and how the CLI opens them.
- Each site's `Dockerfile` beyond the `FROM` and `USER` lines; `deploy/mail.sh`, `watchdog.sh`, `cloudflare.sh`,
  `caddy-local.sh`, `disk-*.sh`, `housekeeping.sh`, `swap.sh`, most of `provision.sh` and `check.sh` in MPs;
  `deploy/send-mail.sh` in Landlords (searched for "backup", "B2", "offsite": no matches).
- The sites' `docs/` (searched for "restore" and `settings.local` only). Councils' DEPLOY.md had no match for
  "restore", "gunzip" or "zcat", so how Councils is meant to restore was not found.
- `family/tools/drift.py` and its baseline.
- MPs' `topics.toml` and Landlords' six content files beyond their parsed outline.
- No test suite was run, and nothing was tried against Backblaze or Docker.
