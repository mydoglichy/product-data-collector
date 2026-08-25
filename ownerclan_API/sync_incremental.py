from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .client import OwnerclanGraphQLError
from .config import OwnerclanConfig, find_project_root, load_config
from .discover_products import make_client
from .logging_config import configure_logging
from .normalization import extract_connection_items, normalize_item
from .queries import all_items_query, item_histories_query
from .storage import (
    load_state,
    merge_discovered_product,
    merge_product_snapshots,
    save_failures,
    save_state,
    save_tracked_products,
    load_tracked_products,
    update_latest_and_history,
)
from .time_utils import now_iso, output_file_stamp, to_unix_millis


LOGGER = logging.getLogger("ownerclan_API.sync_incremental")


def sync_incremental(
    project_root: Path,
    config: OwnerclanConfig,
    *,
    page_limit: int | None = None,
    item_limit: int | None = None,
    dry_run: bool = False,
    client: Any | None = None,
) -> dict[str, int]:
    client = client or make_client(project_root, config)
    collected_at = now_iso(config.timezone)
    state_path = config.output.state_dir / "incremental-state.json"
    state = load_state(state_path)
    date_to_iso = collected_at
    date_from_iso = _incremental_from(state.get("lastSuccessfulItemSyncAt"), config)
    date_from = to_unix_millis(date_from_iso)
    date_to = to_unix_millis(date_to_iso)

    products: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, Any]] = set()
    after: str | None = None
    seen_cursors: set[str] = set()
    pages = 0
    completed = False

    try:
        while True:
            query = all_items_query(
                first=config.incremental.page_size,
                sort_by="dateAsc",
                after=after,
                date_from=date_from,
                date_to=date_to,
            )
            try:
                data = client.graphql(query)
            except OwnerclanGraphQLError as exc:
                if not exc.looks_like_unknown_field() or "allitems" in str(exc).lower():
                    raise
                data = client.graphql(
                    all_items_query(
                        first=config.incremental.page_size,
                        sort_by="dateAsc",
                        after=after,
                        date_from=date_from,
                        date_to=date_to,
                        minimal=True,
                    )
                )
            items, page_info = extract_connection_items(data, "allItems")
            pages += 1
            for item in items:
                key = str(item.get("key") or "")
                dedupe_key = (key, item.get("updatedAt"))
                if key and dedupe_key not in seen_keys:
                    seen_keys.add(dedupe_key)
                    products.append(normalize_item(item, collected_at))
                    if item_limit is not None and len(products) >= item_limit:
                        LOGGER.info("stopping ownerclan incremental sync at item_limit=%d", item_limit)
                        completed = True
                        break
            if completed:
                break
            next_cursor = page_info.get("endCursor")
            if not page_info.get("hasNextPage") or not next_cursor:
                completed = True
                break
            if page_limit is not None and pages >= page_limit:
                LOGGER.info("stopping ownerclan incremental sync at page_limit=%d", page_limit)
                completed = True
                break
            if str(next_cursor) in seen_cursors or next_cursor == after:
                LOGGER.warning("stopping ownerclan incremental pagination due to repeated cursor=%s", next_cursor)
                completed = True
                break
            seen_cursors.add(str(next_cursor))
            after = str(next_cursor)
    except Exception as exc:
        failures.append({"error": str(exc), "stage": "allItems", "dateFrom": date_from, "dateTo": date_to})
        LOGGER.error("ownerclan incremental sync failed error=%s", exc)

    histories = []
    if completed and config.incremental.include_item_histories:
        try:
            histories = fetch_item_histories(client, config, date_from, date_to)
        except Exception as exc:
            failures.append({"error": str(exc), "stage": "itemHistories", "dateFrom": date_from, "dateTo": date_to})
            LOGGER.error("ownerclan itemHistories sync failed error=%s", exc)

    if not dry_run:
        tracked = load_tracked_products(config.output.tracked_products_path)
        for product in products:
            key = str(product.get("productId") or "")
            if key:
                merge_discovered_product(tracked, key, "incremental", "updated_date_range", collected_at)
        save_tracked_products(config.output.tracked_products_path, tracked)
        output_dir = config.output.output_dir
        data_dir = output_dir.parent
        file_stamp = output_file_stamp("ownerclan", config.timezone)
        merge_product_snapshots(
            output_dir / f"{file_stamp}_product-snapshots.json",
            collected_at,
            products,
            failures,
        )
        update_latest_and_history(
            latest_path=config.output.state_dir / "latest-products.json",
            history_path=data_dir / "history" / f"{file_stamp}_product-history.json",
            collected_at=collected_at,
            products=products,
            raw_retention_per_product=config.output.raw_retention_per_product,
        )
        if histories:
            save_state(data_dir / "history" / f"{file_stamp}_item-histories.json", {"collectedAt": collected_at, "histories": histories})
        if failures:
            save_failures(data_dir / "summaries" / f"{file_stamp}_failures.json", collected_at, failures)
        if completed and not failures:
            state["lastSuccessfulItemSyncAt"] = date_to_iso
            save_state(state_path, state)

    return {
        "pageCount": pages,
        "successCount": len(products),
        "historyCount": len(histories),
        "failureCount": len(failures),
        "stateUpdated": 1 if completed and not failures and not dry_run else 0,
    }


def fetch_item_histories(client: Any, config: OwnerclanConfig, date_from: int, date_to: int) -> list[dict[str, Any]]:
    histories: list[dict[str, Any]] = []
    after: str | None = None
    seen_cursors: set[str] = set()
    while True:
        data = client.graphql(item_histories_query(first=config.incremental.page_size, after=after, date_from=date_from, date_to=date_to))
        items, page_info = extract_connection_items(data, "itemHistories")
        histories.extend(items)
        next_cursor = page_info.get("endCursor")
        if not page_info.get("hasNextPage") or not next_cursor:
            break
        if str(next_cursor) in seen_cursors or next_cursor == after:
            break
        seen_cursors.add(str(next_cursor))
        after = str(next_cursor)
    return histories


def _incremental_from(last_success: Any, config: OwnerclanConfig) -> str:
    tz = ZoneInfo(config.timezone)
    if isinstance(last_success, str) and last_success:
        base = datetime.fromisoformat(last_success)
    else:
        base = datetime.now(tz) - timedelta(minutes=config.incremental.overlap_minutes)
    return (base - timedelta(minutes=config.incremental.overlap_minutes)).replace(microsecond=0).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Ownerclan products changed by updatedAt range.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--page-limit", type=int, default=None, help="Limit pages for a small real API test run.")
    parser.add_argument("--item-limit", type=int, default=None, help="Limit changed items for a small real API test run.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write state/output files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    config = load_config(Path(args.config) if args.config else project_root / "ownerclan_API" / "config.yaml", project_root)
    configure_logging(config.output.log_dir)
    result = sync_incremental(project_root, config, page_limit=args.page_limit, item_limit=args.item_limit, dry_run=args.dry_run)
    print(result)
    return 1 if result["failureCount"] else 0


if __name__ == "__main__":
    sys.exit(main())
