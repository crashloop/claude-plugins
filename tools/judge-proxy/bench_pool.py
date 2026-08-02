"""Measure the warm pool against the spec's acceptance criteria.

Judges two rounds of N concurrent requests. The first round is cold by
construction (the pool starts with one spare), so only the second is scored.
That mirrors hoolint, where rules run concurrently and files within a rule run
serially, so only the first file of each rule pays a boot.

Usage: python bench_pool.py [N]      (default 4, matching hoolint's max_workers)
"""
import asyncio
import json
import statistics
import sys
import time
import urllib.request

URL = "http://localhost:11435/v1/chat/completions"
SPANS = [
    "`assert mock.called` in a test.",
    "`# increment the counter by one` above `count += 1`.",
    "`assert response.status_code == 200` in a test.",
    "`# TODO: fix later` above a bare except.",
]


def _post(i: int) -> tuple[float, bool]:
    """Judge one span. Returns (seconds, served_from_a_spare)."""
    body = json.dumps({
        "model": "qwen3:4b", "reasoning_effort": "none",
        "messages": [{"role": "user",
                      "content": f"Judge item {i + 1}: {SPANS[i % len(SPANS)]}"}],
    }).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"content-type": "application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=300) as r:
        payload = json.load(r)
    return time.monotonic() - t0, payload["x_judge_proxy"]["warm"]


async def _round(n: int) -> list[tuple[float, bool]]:
    loop = asyncio.get_running_loop()
    return await asyncio.gather(*(loop.run_in_executor(None, _post, i)
                                  for i in range(n)))


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4

    baseline = (await _round(1))[0][0]
    print(f"N=1 warm baseline:  {baseline:5.1f}s")

    await asyncio.sleep(8)
    cold = await _round(n)
    print(f"round 1 (cold):     {[f'{s:.1f}s' for s, _ in cold]}  "
          f"warm={[w for _, w in cold]}")

    await asyncio.sleep(8)
    hot = await _round(n)
    lat = [s for s, _ in hot]
    warm = [w for _, w in hot]
    median = statistics.median(lat)
    print(f"round 2 (scored):   {[f'{s:.1f}s' for s in lat]}  warm={warm}")
    print(f"\nall warm:           {all(warm)}            (pass: True)")
    print(f"median / baseline:  {median / baseline:.2f}x       (pass: <= 1.50)")


asyncio.run(main())
