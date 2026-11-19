"""Pruebas de ``app.cache``: vigencia, tope y uso desde varios hilos."""

from concurrent.futures import ThreadPoolExecutor

from app.cache import AnswerCache, normalize_question


def test_answers_expire_with_the_ttl_and_the_oldest_leaves_when_full(clock):
    cache = AnswerCache(300, 2, clock)
    first = normalize_question("¿Qué puesto tiene EMP-0005?")

    cache.put(first, "respuesta 1")
    clock.advance(299)
    still_valid = cache.get(normalize_question("¿qué  PUESTO tiene emp-0005?"))
    clock.advance(2)
    expired = cache.get(first)
    cache.put("a", "A")
    cache.put("b", "B")
    cache.put("c", "C")

    assert still_valid == "respuesta 1"
    assert expired is None
    assert cache.get("a") is None
    assert (cache.get("b"), cache.get("c")) == ("B", "C")


def test_twenty_threads_share_the_cache_without_errors_or_overflow(clock):
    cache = AnswerCache(300, 10, clock)

    def work(thread):
        for index in range(50):
            key = f"t{thread}-q{index}"
            cache.put(key, key)
            cache.get(key)
        return thread

    with ThreadPoolExecutor(max_workers=20) as pool:
        finished = list(pool.map(work, range(20)))

    stored = [
        f"t{thread}-q{index}"
        for thread in range(20)
        for index in range(50)
        if cache.get(f"t{thread}-q{index}") is not None
    ]
    assert finished == list(range(20))
    assert 0 < len(stored) <= 10
