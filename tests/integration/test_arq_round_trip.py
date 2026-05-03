"""Integration — ARQ pool round-trip + cron timezone audit.

* The ARQ pool dep boots cleanly under the lifespan (tested via the
  client fixture).
* Every registered cron job's UTC hour matches the documented KG mapping
  in :data:`app.workers.settings.KG_TO_UTC_HOUR_MAPPING`. If a future
  edit changes one without the other, this test fails loudly — exactly
  the silent-fail mode the cron-timezone-discipline DECISION_LOG
  entry exists to prevent.
"""

from __future__ import annotations

import pytest

from app.workers.settings import KG_TO_UTC_HOUR_MAPPING, WorkerSettings

pytestmark = pytest.mark.integration


def _cron_minute_set(minute_attr: object) -> int | set[int]:
    """``arq.cron`` stores ``minute`` as either an int or a set."""
    if isinstance(minute_attr, set):
        return minute_attr
    if isinstance(minute_attr, int):
        return minute_attr
    # ARQ's CronJob may store a frozenset depending on version; collapse.
    return set(minute_attr)  # type: ignore[arg-type]


def test_every_registered_cron_matches_documented_kg_mapping() -> None:
    """Walk WorkerSettings.cron_jobs; for each, assert the UTC hour
    matches what KG_TO_UTC_HOUR_MAPPING says.

    The cron's ``coroutine.__name__`` is the function name; we look it
    up in the mapping.
    """
    seen: set[str] = set()
    for cron_job in WorkerSettings.cron_jobs:
        # ARQ exposes the underlying coro on ``coroutine`` (modern) or
        # via ``name`` — handle both shapes.
        coro = getattr(cron_job, "coroutine", None) or getattr(cron_job, "fn", None)
        if coro is None:
            pytest.fail(f"Could not extract coroutine from cron_job={cron_job!r}")
        name = coro.__name__
        seen.add(name)
        assert name in KG_TO_UTC_HOUR_MAPPING, (
            f"Cron {name!r} registered but missing from KG_TO_UTC_HOUR_MAPPING — "
            "add it (or remove the cron) so future-you doesn't lose the mapping."
        )
        expected_hour, expected_minute = KG_TO_UTC_HOUR_MAPPING[name]

        # ARQ stores hour/minute on the cron object. For "every hour" /
        # "every minute" jobs, ARQ uses ``None`` to mean "all". Our
        # mapping uses 0 to mean "every hour" too — normalise both.
        actual_hour = getattr(cron_job, "hour", None)
        actual_minute = getattr(cron_job, "minute", None)

        # Hour: int, set, or None ("every hour"). Treat None and 0 as
        # equivalent only when minute is a set (recurring sub-hourly job).
        if isinstance(expected_minute, set):
            # Sub-hourly recurring → hour can be None ("every hour") or a set
            assert actual_hour is None or actual_hour in (
                0,
                expected_hour,
            ), f"{name}: expected hour={expected_hour} or None, got {actual_hour}"
        else:
            assert (
                actual_hour == expected_hour
            ), f"{name}: expected UTC hour={expected_hour}, got {actual_hour}"

        # Minute comparison.
        assert _cron_minute_set(actual_minute) == _cron_minute_set(
            expected_minute
        ), f"{name}: expected minute={expected_minute}, got {actual_minute}"

    # Every documented mapping should also be registered.
    documented = set(KG_TO_UTC_HOUR_MAPPING.keys())
    missing_from_settings = documented - seen
    assert (
        not missing_from_settings
    ), f"Documented in KG_TO_UTC_HOUR_MAPPING but not registered: {missing_from_settings}"


async def test_arq_pool_lifespan_boots_and_shuts_down() -> None:
    """Smoke — the ARQ pool boots cleanly when the lifespan runs.

    httpx's ASGITransport doesn't fire lifespan events by default, so
    we drive the lifespan context manager directly. This guarantees the
    startup hook actually ran and stashed the pool.
    """
    from app.main import app, lifespan

    async with lifespan(app):
        pool = getattr(app.state, "arq_pool", None)
        assert pool is not None, "lifespan should have stashed the ARQ pool on app.state"
