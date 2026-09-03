from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from queue import Empty, Queue
from pathlib import Path
from threading import Event, Lock
from typing import Any

from postgres_storage import save_product_raw_samples_if_enabled, save_product_snapshots_if_enabled

from ..services.categories import load_or_refresh_leaf_categories
from ..api.client import OwnerclanGraphQLError, OwnerclanHttpError
from ..api.rate_limiter import RateLimiter
from ..config import OwnerclanConfig, find_project_root, load_config
from .discover_products import make_client
from ..services.logging_config import configure_logging
from ..services.normalization import extract_connection_items, normalize_item
from ..api.queries import all_items_query
from ..persistence.storage import clear_state, load_state, save_state
from ..services.time_utils import now_iso


LOGGER = logging.getLogger("ownerclan_API.workflows.collect_by_categories")
MAX_PARALLEL_CATEGORY_FAILURES = 3


def collect_by_categories(
    project_root: Path,
    config: OwnerclanConfig,
    *,
    category_limit: int | None = None,
    page_limit: int | None = None,
    item_limit: int | None = None,
    refresh_categories: bool = False,
    dry_run: bool = False,
    client: Any | None = None,
) -> dict[str, int]:
    client = client or make_client(project_root, config)
    categories = load_or_refresh_leaf_categories(project_root, config, refresh=refresh_categories, client=client)
    if category_limit is not None:
        categories = categories[:category_limit]

    collected_at = now_iso(config.timezone)
    state_path = config.output.state_dir / "category-collection-state.json"
    state = load_state(state_path)
    if isinstance(state.get("runCollectedAt"), str):
        collected_at = str(state["runCollectedAt"])
    resume_category_key = str(state.get("categoryKey") or "") or None
    resume_after = str(state.get("after") or "") or None
    failures: list[dict[str, Any]] = []
    rate_limit_failures = 0
    category_pages = 0
    success_count = 0

    start_index = _category_start_index(categories, resume_category_key)
    with ThreadPoolExecutor(max_workers=1) as save_executor:
        pending_save: Future[None] | None = None
        for category_index, category in enumerate(categories[start_index:], start=start_index):
            category_key = str(category.get("key") or "")
            if not category_key:
                continue
            after: str | None = resume_after if resume_category_key == category_key else None
            seen_cursors: set[str] = set()
            while True:
                try:
                    try:
                        data = client.graphql(
                            all_items_query(first=config.incremental.page_size, category=category_key, after=after)
                        )
                    except OwnerclanGraphQLError as exc:
                        if not exc.looks_like_unknown_field() or "allitems" in str(exc).lower():
                            raise
                        data = client.graphql(
                            all_items_query(
                                first=config.incremental.page_size,
                                category=category_key,
                                after=after,
                                minimal=True,
                            )
                        )
                    items, page_info = extract_connection_items(data, "allItems")
                    category_pages += 1
                except Exception as exc:
                    if pending_save is not None:
                        pending_save.result()
                        pending_save = None
                    if not dry_run:
                        save_state(
                            state_path,
                            {"runCollectedAt": collected_at, "categoryKey": category_key, "after": after},
                        )
                    if _is_rate_limit_exception(exc):
                        rate_limit_failures += 1
                    failures.append({"categoryKey": category_key, "error": str(exc)})
                    LOGGER.error("failed ownerclan category collection category=%s error=%s", category_key, exc)
                    return {
                        "categoryCount": len(categories),
                        "pageCount": category_pages,
                        "successCount": success_count,
                        "trackedCount": 0,
                        "failureCount": len(failures),
                        "rateLimitFailureCount": rate_limit_failures,
                    }

                if pending_save is not None:
                    pending_save.result()
                    pending_save = None

                page_products_by_key: dict[str, dict[str, Any]] = {}
                for item in items:
                    product_key = str(item.get("key") or "")
                    if not product_key:
                        continue
                    product = normalize_item(item, collected_at)
                    page_products_by_key[product_key] = product
                    if item_limit is not None and success_count + len(page_products_by_key) >= item_limit:
                        break

                next_cursor = page_info.get("endCursor")
                should_stop = False
                state_after_save: dict[str, Any] | None = None

                if item_limit is not None and success_count + len(page_products_by_key) >= item_limit:
                    state_after_save = {"runCollectedAt": collected_at, "categoryKey": category_key, "after": after}
                    should_stop = True
                elif not page_info.get("hasNextPage") or not next_cursor:
                    next_category = _next_category_key(categories, category_index)
                    if next_category:
                        state_after_save = {
                            "runCollectedAt": collected_at,
                            "categoryKey": next_category,
                            "after": None,
                        }
                    should_stop = True
                elif page_limit is not None and category_pages >= page_limit:
                    state_after_save = {
                        "runCollectedAt": collected_at,
                        "categoryKey": category_key,
                        "after": str(next_cursor),
                    }
                    should_stop = True
                elif str(next_cursor) in seen_cursors or next_cursor == after:
                    LOGGER.warning("stopping ownerclan item pagination due to repeated cursor category=%s cursor=%s", category_key, next_cursor)
                    state_after_save = {"runCollectedAt": collected_at, "categoryKey": category_key, "after": after}
                    should_stop = True
                else:
                    state_after_save = {
                        "runCollectedAt": collected_at,
                        "categoryKey": category_key,
                        "after": str(next_cursor),
                    }

                if not dry_run:
                    pending_save = save_executor.submit(
                        _save_ownerclan_category_page_and_state,
                        project_root=project_root,
                        config=config,
                        collected_at=collected_at,
                        products=page_products_by_key,
                        state_path=state_path,
                        state=state_after_save,
                    )
                success_count += len(page_products_by_key)

                if should_stop:
                    if pending_save is not None:
                        pending_save.result()
                        pending_save = None
                    break

                seen_cursors.add(str(next_cursor))
                after = str(next_cursor)

            resume_category_key = None
            resume_after = None
            if item_limit is not None and success_count >= item_limit:
                break
            if page_limit is not None and category_pages >= page_limit:
                break

        if pending_save is not None:
            pending_save.result()

    if not dry_run and not failures and item_limit is None and page_limit is None:
        clear_state(state_path)

    return {
        "categoryCount": len(categories),
        "pageCount": category_pages,
        "successCount": success_count,
        "trackedCount": 0,
        "failureCount": len(failures),
        "rateLimitFailureCount": rate_limit_failures,
    }


def collect_by_categories_parallel(
    project_root: Path,
    config: OwnerclanConfig,
    *,
    category_workers: int,
    refresh_categories: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    if category_workers <= 1:
        return collect_by_categories(project_root, config, refresh_categories=refresh_categories, dry_run=dry_run)

    shared_rate_limiter = RateLimiter(config.request.interval_seconds)
    categories = load_or_refresh_leaf_categories(
        project_root,
        config,
        refresh=refresh_categories,
        client=make_client(project_root, config, rate_limiter=shared_rate_limiter),
    )
    collected_at = now_iso(config.timezone)
    state_path = config.output.state_dir / "category-collection-state.json"
    progress_path = config.output.state_dir / "category-collection-progress.json"
    legacy_state = load_state(state_path)
    progress = load_state(progress_path)

    if isinstance(progress.get("runCollectedAt"), str):
        collected_at = str(progress["runCollectedAt"])
    elif isinstance(legacy_state.get("runCollectedAt"), str):
        collected_at = str(legacy_state["runCollectedAt"])

    completed = set(_string_list(progress.get("completedCategoryKeys")))
    in_progress = progress.get("inProgress")
    in_progress = in_progress if isinstance(in_progress, dict) else {}
    legacy_category_key = str(legacy_state.get("categoryKey") or "") or None
    legacy_after = str(legacy_state.get("after") or "") or None
    start_index = _category_start_index(categories, legacy_category_key) if not completed else 0

    task_queue: Queue[tuple[int, dict[str, Any], str | None]] = Queue()
    for category_index, category in enumerate(categories[start_index:], start=start_index):
        category_key = str(category.get("key") or "")
        if not category_key or category_key in completed:
            continue
        after = None
        category_progress = in_progress.get(category_key)
        if isinstance(category_progress, dict):
            stored_after = category_progress.get("after")
            after = str(stored_after) if stored_after not in (None, "") else None
        elif legacy_category_key == category_key:
            after = legacy_after
        task_queue.put((category_index, category, after))

    progress_lock = Lock()
    counters_lock = Lock()
    counters = {
        "pageCount": 0,
        "successCount": 0,
        "failureCount": 0,
        "rateLimitFailureCount": 0,
    }
    failures_by_category: dict[str, int] = {}
    stop_requested = Event()

    def save_progress() -> None:
        save_state(
            progress_path,
            {
                "runCollectedAt": collected_at,
                "completedCategoryKeys": sorted(completed),
                "inProgress": in_progress,
            },
        )

    def mark_progress(category_key: str, after: str | None, *, completed_category: bool) -> None:
        if dry_run:
            return
        with progress_lock:
            if completed_category:
                completed.add(category_key)
                in_progress.pop(category_key, None)
            else:
                in_progress[category_key] = {"after": after}
            save_progress()

    def worker(worker_index: int) -> None:
        worker_client = make_client(project_root, config, rate_limiter=shared_rate_limiter)
        with ThreadPoolExecutor(max_workers=1) as save_executor:
            pending_save_ref: list[Future[None] | None] = [None]
            while True:
                if stop_requested.is_set():
                    break
                try:
                    category_index, category, initial_after = task_queue.get_nowait()
                except Empty:
                    break
                category_key = str(category.get("key") or "")
                try:
                    page_count, item_count = _collect_parallel_category(
                        project_root=project_root,
                        config=config,
                        client=worker_client,
                        collected_at=collected_at,
                        category_key=category_key,
                        initial_after=initial_after,
                        dry_run=dry_run,
                        mark_progress=mark_progress,
                        save_executor=save_executor,
                        pending_save_ref=pending_save_ref,
                    )
                    with counters_lock:
                        counters["pageCount"] += page_count
                        counters["successCount"] += item_count
                except Exception as exc:
                    if pending_save_ref[0] is not None:
                        pending_save_ref[0].result()
                        pending_save_ref[0] = None
                    is_rate_limit = _is_rate_limit_exception(exc)
                    failure_count = failures_by_category.get(category_key, 0) + 1
                    failures_by_category[category_key] = failure_count
                    LOGGER.error(
                        "failed ownerclan parallel category collection worker=%d category=%s failureCount=%d error=%s",
                        worker_index,
                        category_key,
                        failure_count,
                        exc,
                    )
                    if is_rate_limit:
                        stop_requested.set()
                        with counters_lock:
                            counters["failureCount"] += 1
                            counters["rateLimitFailureCount"] += 1
                    elif failure_count >= MAX_PARALLEL_CATEGORY_FAILURES:
                        with counters_lock:
                            counters["failureCount"] += 1
                    else:
                        stored = in_progress.get(category_key)
                        retry_after = stored.get("after") if isinstance(stored, dict) else initial_after
                        task_queue.put((category_index, category, str(retry_after) if retry_after not in (None, "") else None))
                finally:
                    task_queue.task_done()
            if pending_save_ref[0] is not None:
                pending_save_ref[0].result()

    with ThreadPoolExecutor(max_workers=category_workers) as executor:
        futures = [executor.submit(worker, index + 1) for index in range(category_workers)]
        for future in futures:
            future.result()

    if not dry_run and counters["failureCount"] == 0:
        clear_state(progress_path)
        clear_state(state_path)

    return {
        "categoryCount": len(categories),
        "pageCount": counters["pageCount"],
        "successCount": counters["successCount"],
        "trackedCount": 0,
        "failureCount": counters["failureCount"],
        "rateLimitFailureCount": counters["rateLimitFailureCount"],
    }


def _collect_parallel_category(
    *,
    project_root: Path,
    config: OwnerclanConfig,
    client: Any,
    collected_at: str,
    category_key: str,
    initial_after: str | None,
    dry_run: bool,
    mark_progress: Any,
    save_executor: ThreadPoolExecutor,
    pending_save_ref: list[Future[None] | None],
) -> tuple[int, int]:
    after = initial_after
    seen_cursors: set[str] = set()
    page_count = 0
    item_count = 0
    while True:
        try:
            data = client.graphql(all_items_query(first=config.incremental.page_size, category=category_key, after=after))
        except OwnerclanGraphQLError as exc:
            if not exc.looks_like_unknown_field() or "allitems" in str(exc).lower():
                raise
            data = client.graphql(
                all_items_query(
                    first=config.incremental.page_size,
                    category=category_key,
                    after=after,
                    minimal=True,
                )
            )
        items, page_info = extract_connection_items(data, "allItems")
        page_count += 1

        pending_save = pending_save_ref[0]
        if pending_save is not None:
            pending_save.result()
            pending_save_ref[0] = None

        page_products_by_key: dict[str, dict[str, Any]] = {}
        for item in items:
            product_key = str(item.get("key") or "")
            if not product_key:
                continue
            page_products_by_key[product_key] = normalize_item(item, collected_at)

        next_cursor = page_info.get("endCursor")
        completed_category = not page_info.get("hasNextPage") or not next_cursor
        state_after = None if completed_category else str(next_cursor)
        if not dry_run:
            pending_save_ref[0] = save_executor.submit(
                _save_ownerclan_category_page_and_progress,
                project_root=project_root,
                config=config,
                collected_at=collected_at,
                products=page_products_by_key,
                category_key=category_key,
                after=state_after,
                completed_category=completed_category,
                mark_progress=mark_progress,
            )
        item_count += len(page_products_by_key)

        if completed_category:
            pending_save = pending_save_ref[0]
            if pending_save is not None:
                pending_save.result()
                pending_save_ref[0] = None
            break
        if str(next_cursor) in seen_cursors or next_cursor == after:
            LOGGER.warning("stopping ownerclan item pagination due to repeated cursor category=%s cursor=%s", category_key, next_cursor)
            pending_save = pending_save_ref[0]
            if pending_save is not None:
                pending_save.result()
                pending_save_ref[0] = None
            break
        seen_cursors.add(str(next_cursor))
        after = str(next_cursor)
    return page_count, item_count


def _save_ownerclan_category_page_and_progress(
    *,
    project_root: Path,
    config: OwnerclanConfig,
    collected_at: str,
    products: dict[str, dict[str, Any]],
    category_key: str,
    after: str | None,
    completed_category: bool,
    mark_progress: Any,
) -> None:
    _save_ownerclan_category_page(
        project_root=project_root,
        config=config,
        collected_at=collected_at,
        products=products,
    )
    mark_progress(category_key, after, completed_category=completed_category)


def _save_ownerclan_category_page_and_state(
    *,
    project_root: Path,
    config: OwnerclanConfig,
    collected_at: str,
    products: dict[str, dict[str, Any]],
    state_path: Path,
    state: dict[str, Any] | None,
) -> None:
    _save_ownerclan_category_page(
        project_root=project_root,
        config=config,
        collected_at=collected_at,
        products=products,
    )
    if state is not None:
        save_state(state_path, state)


def _save_ownerclan_category_page(
    *,
    project_root: Path,
    config: OwnerclanConfig,
    collected_at: str,
    products: dict[str, dict[str, Any]],
) -> None:
    save_product_raw_samples_if_enabled(
        project_root=project_root,
        platform="ownerclan",
        collected_at=collected_at,
        products=products.values(),
        limit=config.output.raw_sample_limit,
        logger=LOGGER,
    )
    save_product_snapshots_if_enabled(
        project_root=project_root,
        platform="ownerclan",
        collected_at=collected_at,
        products=(_without_raw(product) for product in products.values()),
        logger=LOGGER,
    )


def _category_start_index(categories: list[dict[str, Any]], category_key: str | None) -> int:
    if not category_key:
        return 0
    for index, category in enumerate(categories):
        if str(category.get("key") or "") == category_key:
            return index
    return 0


def _next_category_key(categories: list[dict[str, Any]], index: int) -> str | None:
    if index + 1 >= len(categories):
        return None
    key = categories[index + 1].get("key")
    return str(key) if key not in (None, "") else None


def _without_raw(product: dict[str, Any]) -> dict[str, Any]:
    result = dict(product)
    result.pop("raw", None)
    return result


def _is_rate_limit_exception(exc: Exception) -> bool:
    if isinstance(exc, OwnerclanHttpError) and exc.status_code == 429:
        return True
    if isinstance(exc, OwnerclanGraphQLError) and exc.is_retryable_rate_limit():
        return True
    text = str(exc).lower()
    return any(term in text for term in ("http 429", "too many requests", "rate limit", "quota"))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Ownerclan products by cached leaf categories.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--category-limit", type=int, default=None, help="Limit categories for a small real API run.")
    parser.add_argument("--page-limit", type=int, default=None, help="Limit allItems pages for a small real API run.")
    parser.add_argument("--item-limit", type=int, default=None, help="Limit unique items for a small real API run.")
    parser.add_argument("--refresh-categories", action="store_true", help="Refresh the leaf category cache before collecting.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write state/output files.")
    parser.add_argument("--category-workers", type=int, default=1, help="Collect different categories concurrently.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    config = load_config(
        Path(args.config) if args.config else project_root / "ownerclan_API" / "config" / "config.yaml",
        project_root,
    )
    configure_logging(config.output.log_dir)
    if args.category_workers > 1 and any(value is not None for value in (args.category_limit, args.page_limit, args.item_limit)):
        raise ValueError("--category-workers cannot be combined with --category-limit, --page-limit, or --item-limit")
    if args.category_workers > 1:
        result = collect_by_categories_parallel(
            project_root,
            config,
            category_workers=args.category_workers,
            refresh_categories=args.refresh_categories,
            dry_run=args.dry_run,
        )
    else:
        result = collect_by_categories(
            project_root,
            config,
            category_limit=args.category_limit,
            page_limit=args.page_limit,
            item_limit=args.item_limit,
            refresh_categories=args.refresh_categories,
            dry_run=args.dry_run,
        )
    print(result)
    return 1 if result["failureCount"] and not result["successCount"] else 0


if __name__ == "__main__":
    sys.exit(main())
