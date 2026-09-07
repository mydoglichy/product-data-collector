from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from pathlib import Path
from typing import Any

from postgres_storage import save_discovered_product_ids_if_enabled, save_search_ranks_if_enabled

from ..api.client import DomeggookApiError, DomeggookClient, ListRequest, create_domeggook_client
from ..config import DomeggookConfig, find_project_root, load_api_keys, load_config
from ..persistence.storage import FileLock, atomic_write_json, clear_state, load_state, save_state
from ..services.categories import Category, load_or_refresh_categories
from ..services.logging_config import configure_logging
from ..services.parsing import parse_list_header, parse_list_items, parse_product_id
from ..services.time_utils import now_iso
from .collect_product_details import collect_details
from .run_budget import RunBudget


LOGGER = logging.getLogger("domeggook_API.workflows.fixed_categories")
DEFAULT_CATEGORY_FILE = "fixed-leaf-categories-50.json"
RANKED_SORTS = {"ha", "rd"}


def save_fixed_leaf_categories(
    project_root: Path,
    config: DomeggookConfig,
    *,
    output_path: Path,
    count: int = 50,
    selection: str = "spread",
    seed: int = 20260907,
    dry_run: bool = False,
    client: DomeggookClient | None = None,
) -> dict[str, int | str]:
    if client is None:
        client = create_domeggook_client(load_api_keys(project_root), config)

    data_dir = project_root / "domeggook_API" / "data"
    categories = load_or_refresh_categories(data_dir / "state" / "categories.json", client, dry_run=dry_run)
    selected = _select_categories(categories, count=count, selection=selection, seed=seed)
    payload = {
        "generatedAt": now_iso(config.timezone),
        "source": "domeggook",
        "selection": selection,
        "seed": seed if selection == "random" else None,
        "requestedCount": count,
        "categoryCount": len(selected),
        "categories": [category.to_json() for category in selected],
    }
    if not dry_run:
        atomic_write_json(output_path, payload)
    return {
        "availableCategoryCount": len(categories),
        "savedCategoryCount": len(selected),
        "outputPath": str(output_path),
    }


def collect_fixed_category_products(
    project_root: Path,
    config: DomeggookConfig,
    *,
    category_path: Path,
    markets: tuple[str, ...] | None = None,
    sort_code: str = "rd",
    per_category_product_limit: int | None = None,
    product_limit: int | None = None,
    page_limit: int | None = None,
    max_runtime_seconds: float | None = None,
    max_api_calls: int | None = None,
    discovery_only: bool = False,
    dry_run: bool = False,
    client: DomeggookClient | None = None,
) -> dict[str, dict[str, int]]:
    if client is None:
        client = create_domeggook_client(load_api_keys(project_root), config)
    if per_category_product_limit is not None and per_category_product_limit < 1:
        raise ValueError("per_category_product_limit must be greater than zero")

    selected_categories = _load_fixed_categories(category_path)
    selected_markets = markets or config.discovery.markets
    deadline_monotonic = None
    if max_runtime_seconds is not None and max_runtime_seconds > 0:
        deadline_monotonic = time.monotonic() + max_runtime_seconds
    run_budget = RunBudget(max_api_calls if max_api_calls is not None else config.request.max_requests_per_day)
    data_dir = project_root / "domeggook_API" / "data"

    with FileLock(data_dir / "logs" / "fixed-category-collector.lock"):
        discovery = _discover_fixed_category_product_ids(
            project_root,
            config,
            categories=selected_categories,
            markets=selected_markets,
            sort_code=sort_code,
            per_category_product_limit=per_category_product_limit,
            page_limit=page_limit,
            deadline_monotonic=deadline_monotonic,
            run_budget=run_budget,
            dry_run=dry_run,
            client=client,
        )
        if (
            int(discovery.get("failureCount") or 0)
            or int(discovery.get("runtimeLimitReached") or 0)
            or int(discovery.get("dailyRequestLimitReached") or 0)
            or discovery_only
        ):
            return {"discovery": discovery, "details": _empty_details(discovery)}

        product_ids = [str(product_id) for product_id in discovery.pop("_productIds")]
        details = collect_details(
            project_root,
            config,
            product_ids=product_ids,
            product_limit=product_limit,
            state_filename=_detail_state_filename(sort_code, per_category_product_limit),
            deadline_monotonic=deadline_monotonic,
            run_budget=run_budget,
            dry_run=dry_run,
            client=client,
        )
    return {"discovery": discovery, "details": details}


def _discover_fixed_category_product_ids(
    project_root: Path,
    config: DomeggookConfig,
    *,
    categories: list[Category],
    markets: tuple[str, ...],
    sort_code: str,
    per_category_product_limit: int | None,
    page_limit: int | None,
    deadline_monotonic: float | None,
    run_budget: RunBudget,
    dry_run: bool,
    client: DomeggookClient,
) -> dict[str, Any]:
    data_dir = project_root / "domeggook_API" / "data"
    state_path = data_dir / "state" / _discovery_state_filename(sort_code, per_category_product_limit)
    state = load_state(state_path)
    collected_at = str(state.get("runCollectedAt") or now_iso(config.timezone))
    positions = [(category, market) for category in categories for market in markets]
    start_index = _start_index(positions, state)

    discovered = 0
    inserted_target_count = 0
    page_count = 0
    failures = 0
    stopped_on_runtime_limit = False
    stopped_on_daily_request_limit = False
    stopped_on_page_limit = False
    product_ids: dict[str, None] = {str(product_id): None for product_id in _state_product_ids(state)}
    category_product_ids = _state_category_product_ids(state)

    for position_index, (category, market) in enumerate(positions[start_index:], start=start_index):
        category_ids = category_product_ids.setdefault(category.code, {})
        if _category_limit_reached(category_ids, per_category_product_limit):
            if not dry_run:
                _save_next_state(
                    state_path,
                    collected_at,
                    positions,
                    position_index,
                    None,
                    product_ids=list(product_ids),
                    category_product_ids=category_product_ids,
                )
            continue
        page = _state_page(state) if position_index == start_index else 1
        while True:
            if _deadline_reached(deadline_monotonic):
                stopped_on_runtime_limit = True
                if not dry_run:
                    _save_next_state(
                        state_path,
                        collected_at,
                        positions,
                        position_index,
                        page,
                        product_ids=list(product_ids),
                        category_product_ids=category_product_ids,
                    )
                break
            if not run_budget.can_call():
                stopped_on_daily_request_limit = True
                if not dry_run:
                    _save_next_state(
                        state_path,
                        collected_at,
                        positions,
                        position_index,
                        page,
                        product_ids=list(product_ids),
                        category_product_ids=category_product_ids,
                    )
                break
            try:
                payload = client.get_item_list(
                    ListRequest(
                        market=market,
                        sort=sort_code,
                        size=config.discovery.list_page_size,
                        page=page,
                        category_code=category.code,
                    )
                )
                run_budget.record_call()
            except DomeggookApiError as exc:
                failures += 1
                LOGGER.error(
                    "failed fixed list category=%s category_name=%r market=%s sort=%s page=%d error=%s",
                    category.code,
                    category.name,
                    market,
                    sort_code,
                    page,
                    exc,
                )
                break

            items = parse_list_items(payload)
            header = parse_list_header(payload)
            page_count += 1
            if not items:
                if not dry_run:
                    _save_next_state(
                        state_path,
                        collected_at,
                        positions,
                        position_index,
                        None,
                        product_ids=list(product_ids),
                        category_product_ids=category_product_ids,
                    )
                break

            current_page = _positive_int(header.get("currentPage")) or page
            items_per_page = _positive_int(header.get("itemsPerPage")) or config.discovery.list_page_size
            effective_sort = str(header.get("sort") or sort_code)
            discovery_target_records: list[dict[str, object]] = []
            search_rank_records: list[dict[str, object]] = []

            for index, item in enumerate(items, start=1):
                if _category_limit_reached(category_ids, per_category_product_limit):
                    break
                product_id = parse_product_id(item)
                if not product_id:
                    continue
                discovered += 1
                product_ids.setdefault(str(product_id), None)
                category_ids.setdefault(str(product_id), None)
                rank = (current_page - 1) * items_per_page + index
                record = {
                    "collectedAt": collected_at,
                    "keyword": category.name,
                    "categoryCode": category.code,
                    "categoryName": category.name,
                    "categoryPath": list(category.path),
                    "market": market,
                    "sort": effective_sort,
                    "requestedSort": sort_code,
                    "reason": _discovery_reason(per_category_product_limit),
                    "productId": product_id,
                    "rank": rank,
                }
                discovery_target_records.append(record)
                if effective_sort in RANKED_SORTS:
                    search_rank_records.append(record)

            if not dry_run:
                inserted_target_count += save_discovered_product_ids_if_enabled(
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

            if _category_limit_reached(category_ids, per_category_product_limit):
                if not dry_run:
                    _save_next_state(
                        state_path,
                        collected_at,
                        positions,
                        position_index,
                        None,
                        product_ids=list(product_ids),
                        category_product_ids=category_product_ids,
                    )
                break
            if len(items) < items_per_page:
                if not dry_run:
                    _save_next_state(
                        state_path,
                        collected_at,
                        positions,
                        position_index,
                        None,
                        product_ids=list(product_ids),
                        category_product_ids=category_product_ids,
                    )
                break
            if page_limit is not None and page_count >= page_limit:
                stopped_on_page_limit = True
                if not dry_run:
                    _save_next_state(
                        state_path,
                        collected_at,
                        positions,
                        position_index,
                        page + 1,
                        product_ids=list(product_ids),
                        category_product_ids=category_product_ids,
                    )
                break
            page += 1
            if not dry_run:
                _save_next_state(
                    state_path,
                    collected_at,
                    positions,
                    position_index,
                    page,
                    product_ids=list(product_ids),
                    category_product_ids=category_product_ids,
                )
        if failures or stopped_on_runtime_limit or stopped_on_daily_request_limit or stopped_on_page_limit:
            break

    if not dry_run and not failures and not stopped_on_runtime_limit and not stopped_on_daily_request_limit and not stopped_on_page_limit:
        clear_state(state_path)

    return {
        "categoryCount": len(categories),
        "marketCount": len(markets),
        "pageCount": page_count,
        "discoveredCount": discovered,
        "uniqueProductCount": len(product_ids),
        "perCategoryProductLimit": per_category_product_limit or 0,
        "insertedTargetCount": inserted_target_count,
        "failureCount": failures,
        "runtimeLimitReached": int(stopped_on_runtime_limit),
        "dailyRequestLimitReached": int(stopped_on_daily_request_limit),
        "pageLimitReached": int(stopped_on_page_limit),
        "_productIds": list(product_ids),
    }


def _select_categories(categories: list[Category], *, count: int, selection: str, seed: int) -> list[Category]:
    if count < 1:
        raise ValueError("count must be greater than zero")
    if len(categories) <= count:
        return list(categories)
    if selection == "first":
        return categories[:count]
    if selection == "random":
        rng = random.Random(seed)
        return sorted(rng.sample(categories, count), key=lambda category: categories.index(category))
    if selection == "spread":
        if count == 1:
            return [categories[0]]
        last_index = len(categories) - 1
        indexes = [round(index * last_index / (count - 1)) for index in range(count)]
        return [categories[index] for index in indexes]
    raise ValueError(f"unsupported selection: {selection}")


def _load_fixed_categories(path: Path) -> list[Category]:
    payload = load_state(path)
    raw_categories = payload.get("categories")
    if not isinstance(raw_categories, list) or not raw_categories:
        raise ValueError(f"fixed category file must contain categories: {path}")
    categories: list[Category] = []
    for item in raw_categories:
        if not isinstance(item, dict):
            continue
        code = _text_or_none(item.get("code"))
        name = _text_or_none(item.get("name"))
        depth = item.get("depth")
        if not code or not name or not isinstance(depth, int):
            continue
        raw_path = item.get("path")
        categories.append(
            Category(
                code=code,
                name=name,
                depth=depth,
                path=tuple(str(value) for value in raw_path) if isinstance(raw_path, list) else (name,),
                int_code=_int_or_none(item.get("intCode")),
                locked=_text_or_none(item.get("locked")),
            )
        )
    if not categories:
        raise ValueError(f"fixed category file does not contain valid categories: {path}")
    return categories


def _start_index(positions: list[tuple[Category, str]], state: dict[str, object]) -> int:
    category_code = state.get("categoryCode")
    market = state.get("market")
    if not category_code or not market:
        return 0
    for index, (category, candidate_market) in enumerate(positions):
        if category.code == category_code and candidate_market == market:
            return index
    return 0


def _state_page(state: dict[str, object]) -> int:
    try:
        return max(int(state.get("nextPage", 1)), 1)
    except (TypeError, ValueError):
        return 1


def _state_product_ids(state: dict[str, object]) -> list[str]:
    raw_product_ids = state.get("productIds")
    if not isinstance(raw_product_ids, list):
        return []
    return [str(product_id) for product_id in raw_product_ids if product_id not in (None, "")]


def _state_category_product_ids(state: dict[str, object]) -> dict[str, dict[str, None]]:
    raw_category_product_ids = state.get("categoryProductIds")
    if not isinstance(raw_category_product_ids, dict):
        return {}
    result: dict[str, dict[str, None]] = {}
    for category_code, raw_product_ids in raw_category_product_ids.items():
        if not isinstance(raw_product_ids, list):
            continue
        result[str(category_code)] = {
            str(product_id): None for product_id in raw_product_ids if product_id not in (None, "")
        }
    return result


def _category_limit_reached(product_ids: dict[str, None], limit: int | None) -> bool:
    return limit is not None and len(product_ids) >= limit


def _discovery_state_filename(sort_code: str, per_category_product_limit: int | None) -> str:
    safe_sort = _safe_state_part(sort_code)
    if per_category_product_limit is None:
        return f"fixed-category-discovery-{safe_sort}-state.json"
    return f"fixed-category-discovery-{safe_sort}-limit-{per_category_product_limit}-state.json"


def _detail_state_filename(sort_code: str, per_category_product_limit: int | None) -> str:
    safe_sort = _safe_state_part(sort_code)
    if per_category_product_limit is None:
        return f"fixed-category-detail-{safe_sort}-state.json"
    return f"fixed-category-detail-{safe_sort}-limit-{per_category_product_limit}-state.json"


def _safe_state_part(value: str) -> str:
    safe = "".join(ch for ch in value.lower() if ch.isalnum() or ch in ("-", "_"))
    return safe or "default"


def _discovery_reason(per_category_product_limit: int | None) -> str:
    if per_category_product_limit is None:
        return "fixed_category_full"
    return "fixed_category_sample"


def _save_next_state(
    state_path: Path,
    collected_at: str,
    positions: list[tuple[Category, str]],
    index: int,
    next_page: int | None,
    *,
    product_ids: list[str],
    category_product_ids: dict[str, dict[str, None]],
) -> None:
    if next_page is None:
        if index + 1 >= len(positions):
            clear_state(state_path)
            return
        index += 1
        next_page = 1
    category, market = positions[index]
    save_state(
        state_path,
        {
            "runCollectedAt": collected_at,
            "categoryCode": category.code,
            "market": market,
            "nextPage": next_page,
            "productIds": product_ids,
            "categoryProductIds": {
                category_code: list(ids)
                for category_code, ids in sorted(category_product_ids.items())
            },
        },
    )


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _deadline_reached(deadline_monotonic: float | None) -> bool:
    return deadline_monotonic is not None and time.monotonic() >= deadline_monotonic


def _empty_details(discovery: dict[str, int]) -> dict[str, int]:
    return {
        "trackedCount": 0,
        "successCount": 0,
        "failureCount": int(discovery.get("failureCount") or 0),
        "runtimeLimitReached": int(discovery.get("runtimeLimitReached") or 0),
        "dailyRequestLimitReached": int(discovery.get("dailyRequestLimitReached") or 0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Save and collect a fixed set of Domeggook leaf categories.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    save_parser = subparsers.add_parser("save-categories", help="Save a fixed leaf category list.")
    save_parser.add_argument("--config", default=None)
    save_parser.add_argument("--output", default=None)
    save_parser.add_argument("--count", type=int, default=50)
    save_parser.add_argument("--selection", choices=("spread", "first", "random"), default="spread")
    save_parser.add_argument("--seed", type=int, default=20260907)
    save_parser.add_argument("--dry-run", action="store_true")

    collect_parser = subparsers.add_parser("collect", help="Collect all products for the fixed category list.")
    collect_parser.add_argument("--config", default=None)
    collect_parser.add_argument("--categories", default=None)
    collect_parser.add_argument("--market", action="append", choices=("dome", "supply"), help="Repeat to select markets. Default: config markets.")
    collect_parser.add_argument("--sort", default="rd")
    collect_parser.add_argument(
        "--per-category-product-limit",
        type=int,
        default=None,
        help="Stop discovery after this many unique products per fixed category. Uses a separate resume state.",
    )
    collect_parser.add_argument("--product-limit", type=int, default=None)
    collect_parser.add_argument("--page-limit", type=int, default=None)
    collect_parser.add_argument("--max-runtime-hours", type=float, default=None)
    collect_parser.add_argument("--max-api-calls", type=int, default=None)
    collect_parser.add_argument("--discovery-only", action="store_true", help="Save discovered product ids/ranks only; skip detail snapshots.")
    collect_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    project_root = find_project_root(Path.cwd())
    configure_logging(project_root / "domeggook_API" / "data" / "logs")
    config_path = Path(args.config) if args.config else project_root / "domeggook_API" / "config" / "config.yaml"
    config = load_config(config_path)

    if args.command == "save-categories":
        output_path = Path(args.output) if args.output else project_root / "domeggook_API" / "data" / "state" / DEFAULT_CATEGORY_FILE
        result = save_fixed_leaf_categories(
            project_root,
            config,
            output_path=output_path,
            count=args.count,
            selection=args.selection,
            seed=args.seed,
            dry_run=args.dry_run,
        )
        print(result)
        return 0

    category_path = Path(args.categories) if args.categories else project_root / "domeggook_API" / "data" / "state" / DEFAULT_CATEGORY_FILE
    max_runtime_seconds = args.max_runtime_hours * 3600 if args.max_runtime_hours is not None else None
    result = collect_fixed_category_products(
        project_root,
        config,
        category_path=category_path,
        markets=tuple(args.market) if args.market else None,
        sort_code=args.sort,
        per_category_product_limit=args.per_category_product_limit,
        product_limit=args.product_limit,
        page_limit=args.page_limit,
        max_runtime_seconds=max_runtime_seconds,
        max_api_calls=args.max_api_calls,
        discovery_only=args.discovery_only,
        dry_run=args.dry_run,
    )
    print("Domeggook fixed category collection summary")
    print(f"discovery={result['discovery']}")
    print(f"details={result['details']}")
    return 1 if result["discovery"]["failureCount"] or result["details"]["failureCount"] else 0


if __name__ == "__main__":
    sys.exit(main())
