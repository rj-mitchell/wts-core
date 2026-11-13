"""What makes Where Parks Stand this site and no other: its name and prefix, its settings, every word a reader can
be shown, its word lists, its limits for the right of reply, what its backups are called, and its tables.

A newcomer reads this file first. The package (``wts-core``) holds none of it: no limit, no price and no wording
there has a default, so everything here is passed in where it is needed (docs/adr/0004-how-sites-plug-in.md).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from wts_core import Messages, Settings, Site, load_settings, observe, replies, usage
from wts_core.checks import COMMON_HONORIFICS, COMMON_LOADED_WORDS, EVIDENCE_NOTES_STRICT, LoadedWords, Verifier
from wts_core.ops import AlertWording, BackupSpec
from wts_core.ports import SYSTEM_CLOCK, SYSTEM_RANDOM, Clock, Random
from wts_core.replies import Item, Refused, Replies, ReplyMessages, ReplyRules
from wts_core.settings import EnvSetting, require
from wts_core.state import Import, Migration, StateDB
from wts_core.usage import BriefingArchive, PriceTable, SavedBriefings, token_id

from parks import __version__

ROOT = Path(__file__).resolve().parents[2]  # the site's root: config/, data_static/ and eval/ sit under it

# ---- the site ----------------------------------------------------------------------------------------------------

SITE = Site(
    name="Where Parks Stand",
    package="parks",
    env_prefix="PARKS",  # PARKS_DATA_DIR, PARKS_CONFIG, PARKS_ANTHROPIC_API_KEY, PARKS_CHECK_TOKEN, PARKS_B2_BUCKET…
    root=ROOT,
    hosts=("whereparksstand.example", "www.whereparksstand.example"),
    state_file="state.db",
    version=__version__,
    # Raise this whenever INSTRUCTIONS in parks/pipeline.py change: it is part of the answer cache's key, so a
    # briefing written under the old instructions is never served as if written under the new.
    instructions_version="2026-11-13",
    # settings an environment variable may override: PARKS_PROVIDER sets [answer] provider, and so on
    env_settings=(
        EnvSetting("PROVIDER", "answer", "provider"),
        EnvSetting("BEHIND_PROXY", "server", "behind_proxy", "flag"),
    ),
)


class ParksSettings(Settings):
    """The package's settings, with this site's own accessors. ``Settings`` is the one class of the package a site
    may subclass."""

    @property
    def minutes_file(self) -> Path:
        """The record itself: the minutes this site's briefings are drawn from."""
        path = Path(self.section("record")["minutes"])
        return path if path.is_absolute() else self.site.root / path

    @property
    def recordings_dir(self) -> Path:
        return self.site.root / "data_static" / "recordings"

    @property
    def ranking(self) -> dict[str, Any]:
        return self.section("ranking")

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


# Every key the site reads itself. The limits, prices and figures of the briefing flow under [usage] are read by the
# package, which checks them when the site's desk is built (wts_core.briefing.desk_parts): these are the site's.
REQUIRED: Mapping[str, tuple[str, ...]] = {
    "record": ("minutes",),
    "ranking": ("word_weight", "meaning_floor", "meaning_ceiling", "max_per_park"),
    "embedding": ("backend", "dim"),
    "answer": ("provider", "recording", "model", "query_parse_model", "summary_sources", "comprehensive_sources",
               "summary_effort", "comprehensive_effort", "query_parse_effort", "max_tokens", "use_fallbacks"),
    "server": ("behind_proxy", "trust_forwarded_first"),
    "logs": ("max_bytes", "keep", "days"),
    "eval": ("thresholds",),
}


def load(config_path: str | Path | None = None, env: Mapping[str, str] | None = None,
         **overrides: Any) -> ParksSettings:
    """The site's settings, with the keys the site reads itself checked: a missing one stops the site here, naming
    it and the file."""
    settings = load_settings(ParksSettings, SITE, config_path, env, **overrides)
    for section, keys in REQUIRED.items():
        require(settings, section, keys)
    return settings


def prices(settings: ParksSettings) -> PriceTable:
    """The site's prices, for the owner's commands that work out a cost."""
    return PriceTable.from_settings(settings.usage, file=settings.config_path)


# Two figures the package's commands take when they are built, before any settings are read, so they are fixed here
# and not in settings.toml. What one evaluation run may spend, in US dollars, unless --max-cost says otherwise:
EVAL_MAX_COST_USD = 1.0
# How alike two questions must be to count as one theme in the statistics (cosine similarity). It belongs to the
# embedding model, so it changes when [embedding] does.
THEME_SIMILARITY = 0.5

# ---- every word of the briefing flow that a reader can be shown --------------------------------------------------

MESSAGES = Messages(
    too_many_requests="Too many requests. Please wait a minute and try again.",
    visitor_daily_limit="You have asked a lot of questions today, so new briefings are paused until tomorrow.",
    daily_cap="The site has reached its budget for new briefings today. They start again tomorrow.",
    monthly_cap="The site has reached its budget for new briefings this month. They start again next month.",
    busy_visitor="Two of your briefings are still being written. Please wait for one to finish.",
    busy_site="A lot of briefings are being written just now. Please try again in a minute.",
    sources_follow="{reason} The minutes found are shown below.",
    sources_only="These are the minutes found for your question. No briefing was written.",
    briefing_failed="Something went wrong while this briefing was being written. Please try again.",
    model_declined="The model declined to answer this question.",
)
# said by the site's own pipeline, so not among the package's messages
NO_MODEL = "Showing the minutes only: no model is set up to write a briefing."

# ---- the checks: what is this site's own -------------------------------------------------------------------------

# The words a "no records" answer opens with. The instructions tell the model to use them; the verifier looks for
# them.
NO_RECORDS = "The minutes hold no record of this."

# The family's common list, and two words of this site's own: judgements on the state of a park, which a briefing
# may quote from the minutes but never say in its own voice.
LOADED_WORDS = LoadedWords(re.compile(rf"\b({COMMON_LOADED_WORDS}|eyesore|neglected)\b", re.IGNORECASE))

VERIFIER = Verifier(
    no_records=NO_RECORDS,
    # the strict form of the "note about the evidence" rule: a new site has no reason to take the wider one
    evidence_notes=EVIDENCE_NOTES_STRICT,
    # minutes write "Cllr. Okafor": the full stop ends no sentence
    honorifics=(*COMMON_HONORIFICS, "Cllr"),
)

# ---- reports and the right of reply ------------------------------------------------------------------------------

REPLY_RULES = ReplyRules(
    min_words=1,
    max_chars=1500,
    name_max=120,
    role_max=160,
    link_max=500,
    email_max=254,
    daily_statements=3,
    daily_reports=10,
    about_required=False,  # a statement sits beside a briefing, which is about no one person
    report_kinds={"error": "error", "takedown": replies.TAKEDOWN, "other": "other"},
    report_kind_required=True,
    report_min=10,
    report_max=4000,
    page_max=300,
    contact_max=254,
)

REPLY_MESSAGES = ReplyMessages(
    too_few_words="Please write your statement.",
    too_many_words="A statement may be up to {max} words. Yours has {n}.",
    too_many_chars="A statement may be up to {words} words and {max} characters. Yours has {n} characters.",
    name_missing="Please give your name.",
    name_too_long="A name may be up to {max} characters. Yours has {n}.",
    role_missing="Please say who you are speaking for, or your role.",
    role_too_long="A role may be up to {max} characters. Yours has {n}.",
    bad_link="The link must be a full web address, starting with https://.",
    link_too_long="A link may be up to {max} characters. Yours has {n}.",
    bad_email="Please give an email address, so that we can confirm the statement is yours.",
    item_not_shown="There is nothing at that address for a statement to sit beside.",
    daily_statements="You have sent several statements today. Please try again tomorrow, or write to us.",
    daily_reports="You have sent several reports today. Please try again tomorrow, or write to us.",
    report_kind="Please say what kind of problem this is.",
    report_too_short="Please say a little more about the problem.",
    report_too_long="A report may be up to {max} characters. Yours has {n}.",
    contact_too_long="Contact details may be up to {max} characters. Yours have {n}.",
    lapsed="No decision was made in time; please send it again.",
    # the family glossary's heading and disclaimer
    heading="Statement from {name}, {date}",
    disclaimer="In their own words. Not checked or endorsed by {site}.",
    record_link="Their link to the record",
    site=SITE.name,
)

_BRIEFING_ADDRESS = re.compile(r"/b/([A-Za-z0-9_-]{6,40})/?")


class ParksItems:
    """Where a statement may sit on this site (``replies.Items``): beside a saved briefing, at ``/b/<id>``."""

    def __init__(self, briefings: SavedBriefings) -> None:
        self._briefings = briefings

    def resolve(self, pasted: str) -> Item:
        """The briefing at what someone pasted: a full address on one of the site's hosts, or the path alone."""
        parts = urlsplit((pasted or "").strip())
        if parts.hostname and parts.hostname not in SITE.hosts:
            raise Refused("That address is not on this site. Please paste the address of a briefing.", "bad_item")
        match = _BRIEFING_ADDRESS.fullmatch(parts.path if parts.path.startswith("/") else "/" + parts.path)
        if match is None:
            raise Refused("Please paste the address of a briefing: it looks like /b/ and then some letters.",
                          "bad_item")
        return Item(address=f"/b/{match.group(1)}")

    def shown(self, item: Item) -> bool:
        saved = self._briefings.get(item.address.removeprefix("/b/"))
        return saved is not None and saved.withdrawn_at is None


# ---- backups -----------------------------------------------------------------------------------------------------

BACKUPS = BackupSpec(
    prefix="parks-state-",  # parks-state-2026-11-13.sqlite.gz: what marks a backup, here and off site, as this site's
    keep=14,  # how many stay on the server; `parks backup --keep` says otherwise for one run
    required_tables=("wts_schema", "wts_spending", "wts_briefings", "wts_reports", "wts_statements"),
)

# How many nightly copies are kept off site (the package's figure: wts_core.ops.send_offsite), and so about how
# many days a deleted address can remain in a backup. Nothing else that holds old data may be kept longer.
BACKUPS_KEPT_DAYS = 60

BACKUP_ALERTS = AlertWording(
    no_backups="No backups have been made yet.",
    backup_stale="The last backup was made over two days ago ({name}).",
    server_only="Backups are kept on this server only: no off-site copy is set up.",
    no_offsite_yet="No off-site copy has been made yet; one is made with the next backup.",
    offsite_failed="The last off-site copy failed ({when}): {error}",
    offsite_stale="The last off-site copy was over two days ago ({day}).",
)

# ---- the state database ------------------------------------------------------------------------------------------


def migrations() -> tuple[Migration, ...]:
    """The tables of every part of the package this site uses. Each module names its own; the site joins them."""
    return (*usage.migrations(), *replies.migrations(), *observe.migrations())


# A site's one-off copy of rows from tables it had before it took the package. This site was born on the package
# and never had any, so this is here to show the shape: had it once kept its briefings in a table of its own
# called ``briefings``, this would bring them across, once, the first time the site starts with that table there.
# The old table is left exactly as it was.
IMPORTS = (
    Import(
        name="parks-briefings",
        statements=(
            "INSERT OR IGNORE INTO wts_briefings (id, created_at, question, options, events) "
            "SELECT id, created_at, question, '{}', events FROM briefings",
        ),
        needs=("briefings",),
    ),
)


def open_state(settings: ParksSettings, clock: Clock = SYSTEM_CLOCK) -> StateDB:
    """The site's state database, with the package's tables made (and any import run) on the way in."""
    return StateDB(settings.state_db, migrations=migrations(), imports=IMPORTS, clock=clock)


def new_briefing_id(chance: Random) -> str:
    """A saved briefing's id, which is its address: /b/ and eleven characters nobody could guess."""
    return token_id(8, random=chance)


def open_archive(db: StateDB, clock: Clock = SYSTEM_CLOCK, random: Random = SYSTEM_RANDOM) -> BriefingArchive:
    """Saved briefings, for the parts of the site that only read them (the web app's own come with its desk)."""
    return BriefingArchive(db, new_id=lambda: new_briefing_id(random), clock=clock)


def open_replies(db: StateDB, clock: Clock = SYSTEM_CLOCK) -> Replies:
    """Reports and statements, for the routes and for the owner's commands alike."""
    return Replies(db, items=ParksItems(open_archive(db, clock)), rules=REPLY_RULES, messages=REPLY_MESSAGES,
                   clock=clock)
