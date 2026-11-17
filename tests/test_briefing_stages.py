"""Stage timings: how long each step of a briefing took, marked by the desk and by the site's own pipeline."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from wts_core.briefing import Stages, current_stages, sse
from wts_core.briefing.stages import STAGES, marking
from wts_core.testing import FixedClock


def test_a_stage_is_marked_in_milliseconds_from_the_start():
    clock = FixedClock()
    stages = Stages(clock)
    clock.advance(0.25)
    stages.mark("parsed")
    clock.advance(1.2341)
    stages.mark("searched")
    assert (stages.at("parsed"), stages.at("searched"), stages.at("ranked")) == (250, 1484, None)
    assert stages.elapsed() == 1484 and stages.last == "searched"


def test_the_first_mark_of_a_stage_stands():
    clock = FixedClock()
    stages = Stages(clock)
    clock.advance(0.1)
    stages.mark("sources_sent")
    clock.advance(5)
    stages.mark("sources_sent")
    assert stages.at("sources_sent") == 100


def test_the_furthest_stage_is_by_the_order_of_a_briefing_not_of_marking():
    stages = Stages(FixedClock())
    assert stages.last is None
    stages.mark("first_token")
    stages.mark("parsed")
    assert stages.last == "first_token"
    assert STAGES == ("parsed", "searched", "ranked", "sources_sent", "first_token", "written", "checked")


def test_an_unknown_stage_is_a_mistake_in_the_site():
    with pytest.raises(ValueError, match="not a stage"):
        Stages(FixedClock()).mark("embedded")  # type: ignore[arg-type]


def test_outside_a_desk_marking_does_nothing():
    current_stages().mark("searched")  # no error, and nowhere to look for it
    assert current_stages().at("searched") is None


def pipeline(clock: FixedClock):
    """A site's pipeline marking its own stages, handed nothing."""
    clock.advance(0.3)
    current_stages().mark("searched")
    yield {"type": "sources"}
    clock.advance(0.2)
    current_stages().mark("ranked")
    yield {"type": "text"}


def test_a_pipeline_marks_the_stages_of_the_briefing_it_is_run_for():
    clock = FixedClock()
    stages = Stages(clock)
    assert [e["type"] for e in marking(stages, pipeline(clock))] == ["sources", "text"]
    assert (stages.at("searched"), stages.at("ranked")) == (300, 500)
    assert current_stages() is not stages  # put back afterwards


def test_two_briefings_at_once_each_mark_their_own():
    clock = FixedClock()
    one, two = Stages(clock), Stages(clock)
    first, second = marking(one, pipeline(clock)), marking(two, pipeline(clock))
    next(first)  # 300 ms in: the first has searched
    next(second)  # 600 ms in: the second has
    next(first)
    next(second)
    assert (one.at("searched"), one.at("ranked")) == (300, 800)
    assert (two.at("searched"), two.at("ranked")) == (600, 1000)


def test_the_stages_reach_a_pipeline_whose_every_step_is_taken_in_another_thread():
    """A web framework's own thread pool takes each event in whichever thread is free, each with a fresh copy of
    the request's context: something set once at the start would be lost."""
    clock = FixedClock()
    stages = Stages(clock)
    events = marking(stages, pipeline(clock))
    with ThreadPoolExecutor(max_workers=1) as a, ThreadPoolExecutor(max_workers=1) as b:
        assert a.submit(next, events).result()["type"] == "sources"
        assert b.submit(next, events).result()["type"] == "text"
    assert (stages.at("searched"), stages.at("ranked")) == (300, 500)


def test_the_stages_reach_a_pipeline_run_by_the_streamer():
    clock = FixedClock()
    stages = Stages(clock)
    threads: list[str] = []

    def events():
        threads.append(threading.current_thread().name)
        yield from pipeline(clock)

    assert len(list(sse(marking(stages, events()), keep_alive=1))) == 2
    assert threads == ["sse"] and (stages.at("searched"), stages.at("ranked")) == (300, 500)


def test_closing_closes_the_pipeline_which_may_still_mark_a_stage():
    clock = FixedClock()
    stages = Stages(clock)
    closed: list[bool] = []

    def events():
        try:
            yield {"type": "text"}
            yield {"type": "text"}
        finally:
            current_stages().mark("written")
            closed.append(True)

    running = marking(stages, events())
    next(running)
    clock.advance(2)
    running.close()
    assert closed == [True] and stages.at("written") == 2000
