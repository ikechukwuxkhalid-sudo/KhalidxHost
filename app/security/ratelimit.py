import time
from collections import defaultdict, deque

_hits: dict[str, deque] = defaultdict(deque)


def hit(key: str, limit: int, window: int) -> bool:
    """Sliding window. True = allowed, False = rate limited."""
    now = time.time()
    q = _hits[key]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    if len(_hits) > 20000:  # keep memory bounded
        for k in [k for k, v in _hits.items() if not v][:5000]:
            _hits.pop(k, None)
    return True
