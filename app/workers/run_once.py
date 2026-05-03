"""CLI helper — force-run a single ARQ job by name (no Redis polling).

    python -m app.workers.run_once <job_name>

Used by ``make worker-once`` and the Phase 11 smoke recipe to verify
each scheduled job produces the expected output without waiting for
the next cron tick.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from app.workers import images, imports, scheduled, sms

# Job-name → callable. Same names as the WorkerSettings registry.
_JOBS: dict[str, Callable[..., Awaitable[Any]]] = {
    "send_sms": sms.send_sms,
    "process_image_upload": images.process_image_upload,
    "process_product_import": imports.process_product_import,
    "near_expiry_report": scheduled.near_expiry_report,
    "low_stock_report": scheduled.low_stock_report,
    "expire_batches": scheduled.expire_batches,
    "reconcile_stock_cache": scheduled.reconcile_stock_cache,
    "cleanup_otps": scheduled.cleanup_otps,
    "cleanup_carts": scheduled.cleanup_carts,
    "release_pending_orders": scheduled.release_pending_orders,
    "payment_reconcile": scheduled.payment_reconcile,
}


_USAGE_ARGV_LEN = 2


def main() -> int:
    if len(sys.argv) < _USAGE_ARGV_LEN:
        print("Usage: python -m app.workers.run_once <job_name>", file=sys.stderr)
        print(f"Available: {', '.join(sorted(_JOBS))}", file=sys.stderr)
        return 2
    name = sys.argv[1]
    fn = _JOBS.get(name)
    if fn is None:
        print(f"Unknown job: {name!r}", file=sys.stderr)
        print(f"Available: {', '.join(sorted(_JOBS))}", file=sys.stderr)
        return 2
    # Cron jobs take only ctx; on-demand jobs need additional kwargs we
    # don't have at the CLI. Surface that explicitly.
    if name in {"send_sms", "process_image_upload", "process_product_import"}:
        print(
            f"{name} is an on-demand job — enqueue from a route or test, "
            "not from this CLI helper.",
            file=sys.stderr,
        )
        return 2

    async def _runner() -> Any:
        return await fn({})

    result: Any = asyncio.run(_runner())
    print(f"{name} → {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
