"""
engine/refresh.py
=================
Safety check for re-scoring on a server (refresh on visit, the hourly live
loop). A new run only replaces the stored results when it scored every company
that was scored before and the news search answered. Otherwise the previous
results stay up: a failed download must never make a company look safer.
"""

GOOGLE_LOSS_LIMIT = 3     # companies allowed to lose all Google News results in one run


def _google(company: dict) -> int:
    return ((company.get("news") or {}).get("providers") or {}).get("google", 0)


def check_refresh(new: dict, old: dict | None, tracked: set) -> None:
    """Raise RuntimeError, with a reason for the dashboard, if `new` looks incomplete compared with `old`."""
    if not old or not old.get("companies"):
        return
    have = {c["symbol"] for c in new.get("companies", [])}
    missing = sorted(c["symbol"] for c in old["companies"] if c["symbol"] in tracked and c["symbol"] not in have)
    if missing:
        raise RuntimeError(f"{len(missing)} of the companies could not be re-scored ({', '.join(missing[:5])}); "
                           "kept the previous results")
    if new.get("asOf", "") < old.get("asOf", ""):
        raise RuntimeError(f"the price data went back to {new.get('asOf')}; kept the previous results")
    before = {c["symbol"]: _google(c) for c in old["companies"]}
    lost = [c["symbol"] for c in new["companies"] if before.get(c["symbol"], 0) > 0 and _google(c) == 0]
    if len(lost) > GOOGLE_LOSS_LIMIT:
        raise RuntimeError(f"Google News did not answer for {len(lost)} companies; kept the previous results")
