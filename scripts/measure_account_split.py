"""What the totals kept for signed-in accounts still give away: the attack an independent review of 0.3.0 made,
run on the package as it is now.

    uv run python scripts/measure_account_split.py [trials] [narrow|wide]

It makes a site's day as the review's probe did: so many signed-in accounts and so many visitors, each asking one
to four briefings (a question read by a small model and a briefing written by a large one), with token counts drawn
at random. Then it does what the night does (``usage.forget_earlier_days``) and tries, with only what is left in
the file, to say which account each briefing was for (``testing.split_by_account_totals``). It knows who really
asked, and counts what the attack got right and wrong. A record is "given to" an account when it is in every set
of the month's records that could make up the account's kept total. The costs are drawn one of two ways:
"narrow" (the first review's: every briefing costs much the same) and "wide" (the second's, nearer to a real
site: sources sent uncached, and some briefings several times the length of others). Two settings:

* a month that is one day old: the database holds one day, so each account's month so far is that day's total.
  This is the worst case for one copy of the database, and it is also the most that two copies from consecutive
  nights can give (the difference between an account's month in each is that day's total, less exactly);
* a month of twenty days, one copy taken at its end.

docs/adr/0012 ("What is kept about spending, and what can be promised") summarises the numbers. No model is
called: the "briefings" are rows.
"""

from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

from wts_core import observe, usage
from wts_core.observe import SqliteBriefingLog
from wts_core.ports import BriefingRecord, Price, Usage
from wts_core.state import StateDB
from wts_core.testing import FixedClock, assert_briefings_tied_to_no_one, split_by_account_totals
from wts_core.usage import PriceTable, Spending, forget_earlier_days

SETTINGS = ((1, 30), (3, 40), (6, 40), (9, 60))  # signed-in accounts, among so many visitors a day: the review's
QUIET = ((1, 0), (1, 2), (1, 5), (1, 10), (3, 5), (3, 10))  # and a site on which few ask: what is not promised
SIGNED_IN = ((2, 0), (3, 0), (6, 0), (9, 0))  # and one on which everyone signs in: no public to be lost among
WIDE = False  # how the costs are drawn: set from the command line


def a_day(rng: random.Random, clock: FixedClock, spending: Spending, log: SqliteBriefingLog, accounts: int,
          visitors: int, truth: dict[str, int | None], day: int) -> None:
    """One day's briefings, in a shuffled order through the day: each asker one to four (an account) or one to
    three (a visitor)."""
    askers: list[int | str] = [n for n in range(1, accounts + 1) for _ in range(rng.randint(1, 4))]
    askers += [f"code{day}-{n}" for n in range(visitors) for _ in range(rng.randint(1, 3))]
    rng.shuffle(askers)
    for n, who in enumerate(askers):
        clock.advance(seconds=rng.randint(20, 500))
        whose = {"account": who, "visitor": f"code{day}-a{who}"} if isinstance(who, int) else {"visitor": who}
        if WIDE:
            long = rng.random() < 0.15
            read = Usage(input_uncached=rng.randint(900, 2500), output=rng.randint(40, 200))
            written = Usage(input_uncached=rng.randint(15000, 60000),
                            output=rng.randint(3000, 8000) if long else rng.randint(600, 3000))
        else:
            read = Usage(input_uncached=rng.randint(600, 900), output=rng.randint(40, 120))
            written = Usage(input_uncached=rng.randint(200, 800), cache_read=rng.randint(8000, 30000),
                            output=rng.randint(350, 1400))
        cost = spending.add("parse", "small", read, **whose) + spending.add("answer", "big", written, **whose)
        counts = (read + written).as_stored()
        record = f"d{day:02d}r{n:04d}"
        log.write(BriefingRecord(id=record, at=clock.now().isoformat(), outcome="completed", question=f"question {n}",
                                 input_tokens=counts["input_tokens"], cache_read_tokens=counts["cache_read_tokens"],
                                 output_tokens=counts["output_tokens"], cost_usd=round(cost, 6)))
        truth[record] = who if isinstance(who, int) else None


def trial(seed: int, accounts: int, visitors: int, days: int, path: Path) -> tuple[int, int, int, int]:
    """One database of so many days: how many briefings were accounts', how many the attack gave to an account,
    how many of those rightly, and how many of the accounts' totals the attack could not settle."""
    for old in path.parent.glob(path.name + "*"):
        old.unlink()
    rng = random.Random(seed)
    clock = FixedClock("2026-11-01T06:00:00+00:00")
    db = StateDB(path, migrations=(*usage.migrations(), *observe.migrations()), clock=clock)
    prices = (PriceTable(base=Price(2.0, 10.0, 0.2), models=(("small", Price(0.1, 0.5, 0.01)),)) if WIDE
              else PriceTable(base=Price(3.0, 15.0, 0.3), models=(("small", Price(1.0, 5.0, 0.1)),)))
    spending, log = Spending(db, prices, clock=clock), SqliteBriefingLog(db, clock=clock)
    truth: dict[str, int | None] = {}
    for day in range(days):
        clock.set(f"2026-11-{day + 1:02d}T06:00:00+00:00")
        a_day(rng, clock, spending, log, accounts, visitors, truth, day)
    clock.set(f"2026-11-{days + 1:02d}T03:00:00+00:00")
    forget_earlier_days(db, clock=clock)
    db.compact()
    unsettled: list[tuple[str, int]] = []
    given = split_by_account_totals(db, clock=clock, unsettled=unsettled)
    try:
        assert_briefings_tied_to_no_one(db, clock=clock)
        assert not given
    except AssertionError:
        assert given  # the check fails for the records the attack gave to an account, and for nothing else
    return (sum(1 for who in truth.values() if who is not None), len(given),
            sum(1 for record, account in given.items() if truth[record] == account), len(unsettled))


def main() -> None:
    global WIDE
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    WIDE = len(sys.argv) > 2 and sys.argv[2] == "wide"
    print(f"Costs drawn the {'wide' if WIDE else 'narrow'} way.")
    with tempfile.TemporaryDirectory() as folder:
        for title, days, settings in (("A month that is one day old", 1, SETTINGS),
                                      ("A month of twenty days, one copy at its end", 20, SETTINGS),
                                      ("A quiet site, a month that is one day old", 1, QUIET),
                                      ("A quiet site, a month of twenty days", 20, QUIET),
                                      ("Everyone signs in, a month that is one day old", 1, SIGNED_IN),
                                      ("Everyone signs in, a month of twenty days", 20, SIGNED_IN)):
            runs = trials if days == 1 else max(1, trials // 5)
            print(f"\n{title} ({runs} trials of each):")
            for accounts, visitors in settings:
                asked = given = right = unsettled = 0
                for seed in range(runs):
                    a, g, r, u = trial(seed, accounts, visitors, days, Path(folder) / "state.db")
                    asked, given, right, unsettled = asked + a, given + g, right + r, unsettled + u
                print(f"  {accounts} accounts among {visitors} visitors a day: {asked:5d} briefings were an "
                      f"account's; given to one account: {given:4d} ({right} rightly, {given - right} wrongly)"
                      + (f"; {unsettled} of the accounts' totals not settled" if unsettled else ""))


if __name__ == "__main__":
    main()
