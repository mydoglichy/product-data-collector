from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from ..api.client import DomeggookApiError, DomeggookClient, ListRequest, create_domeggook_client
from ..services.categories import load_or_refresh_categories
from ..config import DomeggookConfig, find_project_root, load_api_keys, load_config
from ..services.logging_config import configure_logging
from ..services.parsing import parse_list_header, parse_list_items, parse_product_id
from ..persistence.storage import clear_state, load_state, save_state
from ..services.time_utils import now_iso
from postgres_storage import save_discovered_product_ids_if_enabled, save_search_ranks_if_enabled
from .run_budget import RunBudget


LOGGER = logging.getLogger("domeggook_API.workflows.discover_products")
RANKED_SORTS = {"ha", "rd"}


def discover(
    project_root: Path,
    config: DomeggookConfig,
    *,
    keyword_limit: int | None = None,
    page_limit: int | None = None,
    deadline_monotonic: float | None = None,
    run_budget: RunBudget | None = None,
    dry_run: bool = False,
    client: DomeggookClient | None = None,
) -> dict[str, int]:
    if client is None:
        api_keys = load_api_keys(project_root)
        client = create_domeggook_client(api_keys, config)

    data_dir = project_root / "domeggook_API" / "data"
    categories = load_or_refresh_categories(data_dir / "state" / "categories.json", client, dry_run=dry_run)
    if keyword_limit is not None:
        categories = categories[:keyword_limit]

    state_path = data_dir / "state" / "discovery-state.json"
    state = load_state(state_path)
    run_collected_at = str(state.get("runCollectedAt") or now_iso(config.timezone))
    discovered = 0
    new_products = 0
    seen_product_ids: set[str] = set()
    failures = 0
    stopped_on_failure = False
    page_count = 0
    stopped_on_limit = False
    stopped_on_runtime_limit = False
    stopped_on_daily_request_limit = False

    positions = _discovery_positions(categories, config)
    start_index = _discovery_start_index(positions, state)
    for position_index, (category, market, reason, sort_code) in enumerate(positions[start_index:], start=start_index):
        page = _state_page(state) if position_index == start_index else 1
        while True:
            if _deadline_reached(deadline_monotonic):
                stopped_on_runtime_limit = True
                if not dry_run:
                    _save_next_discovery_state(state_path, run_collected_at, positions, position_index, page)
                break
            if run_budget is not None and not run_budget.can_call():
                stopped_on_daily_request_limit = True
                if not dry_run:
                    _save_next_discovery_state(state_path, run_collected_at, positions, position_index, page)
                break
            collected_at = run_collected_at
            try:
                payload = client.get_item_list(
                    ListRequest(
                        market=market,
                        sort=sort_code,
                        size=config.discovery.items_per_keyword,
                        page=page,
                        category_code=category.code,
                    )
                )
                if run_budget is not None:
                    run_budget.record_call()
                items = parse_list_items(payload)
                header = parse_list_header(payload)
                page_count += 1
            except DomeggookApiError as exc:
                failures += 1
                stopped_on_failure = True
                LOGGER.error(
                    "failed list category=%s category_name=%r market=%s sort=%s page=%d error=%s",
                    category.code,
                    category.name,
                    market,
                    sort_code,
                    page,
                    exc,
                )
                break

            if not items:
                if not dry_run:
                    _save_next_discovery_state(state_path, collected_at, positions, position_index, None)
                break

            effective_sort = _text_or_none(header.get("sort")) or sort_code
            current_page = _positive_int(header.get("currentPage")) or page
            items_per_page = _positive_int(header.get("itemsPerPage")) or config.discovery.items_per_keyword
            should_save_rank = effective_sort in RANKED_SORTS
            search_rank_records: list[dict[str, object]] = []
            discovery_target_records: list[dict[str, object]] = []

            for index, item in enumerate(items, start=1):
                rank = _global_rank(current_page, items_per_page, index)
                product_id = parse_product_id(item)
                if not product_id:
                    LOGGER.warning(
                        "list item missing product id category=%s category_name=%r market=%s sort=%s page=%d rank=%d",
                        category.code,
                        category.name,
                        market,
                        sort_code,
                        page,
                        rank,
                    )
                    continue
                discovered += 1
                if product_id not in seen_product_ids:
                    seen_product_ids.add(product_id)
                    new_products += 1
                discovery_target_records.append(
                    {
                        "collectedAt": collected_at,
                        "keyword": category.name,
                        "categoryCode": category.code,
                        "categoryName": category.name,
                        "categoryPath": list(category.path),
                        "market": market,
                        "sort": effective_sort,
                        "requestedSort": sort_code,
                        "reason": reason,
                        "productId": product_id,
                    }
                )
                if should_save_rank:
                    search_rank_records.append(
                        {
                            "collectedAt": collected_at,
                            "keyword": category.name,
                            "categoryCode": category.code,
                            "categoryName": category.name,
                            "categoryPath": list(category.path),
                            "market": market,
                            "sort": effective_sort,
                            "requestedSort": sort_code,
                            "reason": reason,
                            "productId": product_id,
                            "rank": rank,
                        }
                    )

            if not dry_run:
                save_discovered_product_ids_if_enabled(
                    project_root=project_root,
                    platform="domeggook",
                    records=discovery_target_records,
                    logger=LOGGER,
                )
                save_search_ranks_if_enabled(
                    project_root=project_root,
                    platform="domeggook",
                    records=search_rank_records,
                    logger=LOGGER,
                )

            if len(items) < items_per_page:
                if not dry_run:
                    _save_next_discovery_state(state_path, collected_at, positions, position_index, None)
                break
            if page_limit is not None and page_count >= page_limit:
                stopped_on_limit = True
                if not dry_run:
                    _save_next_discovery_state(state_path, collected_at, positions, position_index, page + 1)
                break
            page += 1
            if not dry_run:
                _save_next_discovery_state(state_path, collected_at, positions, position_index, page)
        if stopped_on_failure or stopped_on_limit or stopped_on_runtime_limit or stopped_on_daily_request_limit:
            break
    if (
        not dry_run
        and not stopped_on_failure
        and not stopped_on_limit
        and not stopped_on_runtime_limit
        and not stopped_on_daily_request_limit
    ):
        clear_state(state_path)

    return {
        "categoryCount": len(categories),
        "pageCount": page_count,
        "discoveredCount": discovered,
        "newProductCount": new_products,
        "trackedCount": 0,
        "failureCount": failures,
        "runtimeLimitReached": int(stopped_on_runtime_limit),
        "dailyRequestLimitReached": int(stopped_on_daily_request_limit),
    }


def _global_rank(current_page: int, items_per_page: int, index: int) -> int:
    return (current_page - 1) * items_per_page + index


def _discovery_positions(categories: list[object], config: DomeggookConfig) -> list[tuple[object, str, str, str]]:
    return [
        (category, market, reason, sort_code)
        for category in categories
        for market in config.discovery.markets
        for reason, sort_code in config.discovery.sorts.items()
    ]


def _discovery_start_index(positions: list[tuple[object, str, str, str]], state: dict[str, object]) -> int:
    category_code = state.get("categoryCode")
    market = state.get("market")
    sort = state.get("sort")
    reason = state.get("reason")
    if not category_code or not market or not sort:
        return 0
    for index, (category, candidate_market, candidate_reason, candidate_sort) in enumerate(positions):
        if (
            getattr(category, "code", None) == category_code
            and candidate_market == market
            and candidate_sort == sort
            and (not reason or candidate_reason == reason)
        ):
            return index
    return 0


def _state_page(state: dict[str, object]) -> int:
    try:
        return max(int(state.get("nextPage", 1)), 1)
    except (TypeError, ValueError):
        return 1


def _save_next_discovery_state(
    state_path: Path,
    collected_at: str,
    positions: list[tuple[object, str, str, str]],
    index: int,
    next_page: int | None,
) -> None:
    if next_page is not None:
        category, market, reason, sort_code = positions[index]
        save_state(
            state_path,
            {
                "runCollectedAt": collected_at,
                "categoryCode": getattr(category, "code", None),
                "market": market,
                "reason": reason,
                "sort": sort_code,
                "nextPage": next_page,
            },
        )
        return
    if index + 1 >= len(positions):
        clear_state(state_path)
        return
    category, market, reason, sort_code = positions[index + 1]
    save_state(
        state_path,
        {
            "runCollectedAt": collected_at,
            "categoryCode": getattr(category, "code", None),
            "market": market,
            "reason": reason,
            "sort": sort_code,
            "nextPage": 1,
        },
    )


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _text_or_none(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _deadline_reached(deadline_monotonic: float | None) -> bool:
    return deadline_monotonic is not None and time.monotonic() >= deadline_monotonic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover Domeggook/Domeme product ids from category searches.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit categories for a small real API run.")
    parser.add_argument("--page-limit", type=int, default=None, help="Limit list pages for a small real API run.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write data files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    configure_logging(project_root / "domeggook_API" / "data" / "logs")
    config = load_config(Path(args.config) if args.config else project_root / "domeggook_API" / "config" / "config.yaml")
    result = discover(project_root, config, keyword_limit=args.limit, page_limit=args.page_limit, dry_run=args.dry_run)
    print(result)
    return 1 if result["failureCount"] and not result["discoveredCount"] else 0


if __name__ == "__main__":
    sys.exit(main())
