from gdocout.pacing import OK, THROTTLE, TRANSIENT, Pacer


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def pacer(**kw):
    clock = Clock()
    args = dict(start=2, maximum=8, ramp_every=3, first_pause=30, max_pause=900, give_up_after=6, min_gap=0, clock=clock, sleep_cap=0.001)
    args.update(kw)
    return Pacer(**args), clock


def test_ramps_up_after_clean_answers_to_the_ceiling():
    p, _ = pacer()
    for _ in range(100):
        s = p.acquire()
        p.release(s, OK)
    assert p.allowed == 8 and p.stats.peak_workers == 8


def test_throttle_halves_and_pauses():
    p, clock = pacer(start=8)
    s = p.acquire()
    p.release(s, THROTTLE)
    assert p.allowed == 4 and p.paused and p.stats.pauses == 1
    clock.t += 31
    assert not p.paused


def test_retry_after_is_honoured():
    p, clock = pacer()
    s = p.acquire()
    p.release(s, THROTTLE, retry_after=120)
    clock.t += 100
    assert p.paused
    clock.t += 21
    assert not p.paused


def test_a_burst_of_throttles_counts_once():
    p, clock = pacer(start=8)
    starts = [p.acquire() for _ in range(8)]
    for s in starts:
        p.release(s, THROTTLE)
    assert p.allowed == 4 and p.stats.pauses == 1


def test_pauses_double_and_success_resets():
    p, clock = pacer()
    pauses = []
    for _ in range(3):
        clock.t = p.paused_until + 1
        s = p.acquire()
        p.release(s, THROTTLE)
        pauses.append(p.paused_until - clock.t)
    assert pauses == [30, 60, 120]
    clock.t = p.paused_until + 1
    s = p.acquire()
    p.release(s, OK)
    clock.t += 1
    s = p.acquire()
    p.release(s, THROTTLE)
    assert p.paused_until - clock.t == 30


def test_gives_up_after_long_refusal():
    p, clock = pacer(give_up_after=3)
    for _ in range(4):
        clock.t = p.paused_until + 1
        s = p.acquire()
        assert s is not None
        p.release(s, THROTTLE)
    assert p.stopped and "half an hour" in p.stop_reason
    assert p.acquire() is None


def test_transient_errors_do_not_pause():
    p, _ = pacer()
    s = p.acquire()
    p.release(s, TRANSIENT)
    assert not p.paused and p.allowed == 2
