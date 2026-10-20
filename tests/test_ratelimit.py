from olist_assistant.api.ratelimit import RateLimiter


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_batas_tercapai_lalu_pulih_setelah_jendela():
    clock = Clock()
    limiter = RateLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.check("a") is None
    assert limiter.check("a") is None
    assert limiter.check("a") == 60.0
    clock.now = 30
    assert limiter.check("a") == 30.0
    clock.now = 61
    assert limiter.check("a") is None


def test_kunci_berbeda_dihitung_terpisah():
    limiter = RateLimiter(limit=1, clock=Clock())
    assert limiter.check("sesi-a") is None
    assert limiter.check("sesi-b") is None
    assert limiter.check("sesi-a") is not None
