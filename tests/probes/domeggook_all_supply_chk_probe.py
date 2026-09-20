from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


SSL_API_URL = "https://www.domeggook.com/ssl/api/"
PRODUCT_SEARCH_URL = "https://product.domeggook.com/api/v1/product/_search"
OUTPUT_DIR = Path("tests/tmp/domeggook_all_supply_chk")
TIMEOUT_SECONDS = 25
KST = timezone(timedelta(hours=9))

SECRET_PARAM_KEYS = {"aid", "id", "pw", "sId", "sid", "Authorization"}
STATUS_ALL = "OPEN_RESTART_CLOSE_SOLDOUT_DEL_AMT_OPTAMT_OPTSOLDOUT_OPTRESTART"
STATUS_PRICE = "AMT"
STATUS_OPTION_PRICE = "OPTAMT"
STATUS_STOCK = "RESTART_SOLDOUT_OPTRESTART_OPTSOLDOUT"


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only probe for Domeggook getAllSupplyChk v1.1.")
    parser.add_argument("--days", type=int, default=7, help="Date-window days to sample, including today.")
    parser.add_argument("--ic", default="20")
    parser.add_argument("--pg", default="1")
    parser.add_argument("--item-no", action="append", default=[], help="Specific product number to test with sc=no.")
    args = parser.parse_args()

    root = find_project_root(Path.cwd())
    load_dotenv(root / ".env", override=False)
    out_dir = root / OUTPUT_DIR / datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    api_keys = candidate_api_keys()
    member_id = env_first("DOMEGGOOK_ID", "DOMEGGOOK_MEMBER_ID")
    password = env_first("DOMEGGOOK_PASSWORD", "DOMEGGOOK_PW")
    if not api_keys or not member_id or not password:
        print("Missing required env: DOMEGGOOK API key, DOMEGGOOK_ID, DOMEGGOOK_PASSWORD")
        return 2

    session = requests.Session()
    login = login_with_first_working_key(session, api_keys, member_id, password, out_dir)
    if not login["sid"]:
        print("login=failed")
        print("last_login_summary=", json.dumps(sanitize(login["payload"], member_id), ensure_ascii=False))
        return 1

    api_key = login["api_key"]
    sid = login["sid"]
    print("login=success")
    print(f"output_dir={out_dir}")

    results: dict[str, Any] = {"generatedAt": datetime.now(KST).isoformat(), "calls": []}

    # Authentication/role probes.
    base_params = supply_params(api_key, member_id, sid, status=STATUS_PRICE, ic="1", pg="1")
    results["auth"] = {
        "valid": call_supply(session, base_params, member_id),
        "missing_sId": call_supply(session, {k: v for k, v in base_params.items() if k != "sId"}, member_id),
        "invalid_sId": call_supply(session, {**base_params, "sId": "invalid-session"}, member_id),
    }

    dates = [(datetime.now(KST) - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(max(args.days, 1))]
    status_plan = [
        ("amt_no_date", STATUS_PRICE, None),
        ("optamt_no_date", STATUS_OPTION_PRICE, None),
        ("stock_no_date", STATUS_STOCK, None),
        ("all_no_date", STATUS_ALL, None),
    ]
    for date in dates:
        status_plan.extend(
            [
                (f"amt_{date}", STATUS_PRICE, date),
                (f"optamt_{date}", STATUS_OPTION_PRICE, date),
                (f"stock_{date}", STATUS_STOCK, date),
                (f"all_{date}", STATUS_ALL, date),
            ]
        )

    supply_calls: dict[str, Any] = {}
    for label, status, date in status_plan:
        params = supply_params(api_key, member_id, sid, status=status, ic=args.ic, pg=args.pg, date=date)
        result = call_supply(session, params, member_id)
        supply_calls[label] = summarize_supply_result(result)
        write_json(out_dir / f"{label}.json", sanitize(result, member_id))
        print_supply_line(label, result)

    results["getAllSupplyChk"] = supply_calls

    event_items = unique_items_from_results(supply_calls)
    explicit_item_nos = [str(no) for no in args.item_no if str(no).strip()]
    sample_item_nos = explicit_item_nos + [item["no"] for item in event_items[:20] if item.get("no")]
    sample_item_nos = list(dict.fromkeys(sample_item_nos))

    if sample_item_nos:
        detail = call_item_view_es(session, api_key, sample_item_nos[:100], member_id, sid)
        sync = call_product_sync_by_nos(session, api_key, sample_item_nos[:100], member_id)
        results["detailByEventIds"] = {
            "requestedNos": sample_item_nos[:100],
            "getItemViewES": summarize_detail(detail),
            "productSync": summarize_product_sync(sync),
        }
        write_json(out_dir / "detail_getItemViewES.json", sanitize(detail, member_id))
        write_json(out_dir / "detail_product_sync.json", sanitize(sync, member_id))

    scope = run_scope_probes(session, api_key, member_id, sid, out_dir)
    results["scope"] = scope

    pagination = run_pagination_probes(session, api_key, member_id, sid, out_dir)
    results["pagination"] = pagination

    write_json(out_dir / "summary.json", sanitize(results, member_id))
    print("\nsummary=", json.dumps(sanitize(results, member_id), ensure_ascii=False, indent=2))
    return 0


def candidate_api_keys() -> list[tuple[str, str]]:
    names = [
        "DOMEGGOOK_PRIVATE_API_KEY",
        "DOMEGGOOK_PrivateAPI_KEY_2",
        "DOMEGGOOK_API_KEY_1",
        "DOMEGGOOK_API_KEY",
    ]
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for name in names:
        value = os.getenv(name)
        if value and value not in seen:
            seen.add(value)
            result.append((name, value))
    return result


def login_with_first_working_key(
    session: requests.Session,
    api_keys: list[tuple[str, str]],
    member_id: str,
    password: str,
    out_dir: Path,
) -> dict[str, Any]:
    last: dict[str, Any] = {}
    client_ip = os.getenv("DOMEGGOOK_LOGIN_IP") or resolve_public_ip(session)
    for label, api_key in api_keys:
        params = {
            "ver": "4.1",
            "mode": "setLogin",
            "aid": api_key,
            "id": member_id,
            "pw": password,
            "om": "json",
            "loginKeep": "off",
            "userAgent": "product-data-collector-getAllSupplyChk-probe/1.0",
            "ip": client_ip,
            "device": "Third Party",
        }
        try:
            payload = post_form(session, params, SSL_API_URL)
        except requests.RequestException as exc:
            payload = {"request_error": exc.__class__.__name__}
        write_json(out_dir / f"setLogin_{label}.json", sanitize(payload, member_id))
        root = domeggook_root(payload)
        sid = first_value(root, "sId", "sid")
        if sid:
            return {"api_label": label, "api_key": api_key, "sid": sid, "payload": payload}
        last = {"api_label": label, "api_key": api_key, "sid": None, "payload": payload}
    return last or {"sid": None, "payload": {}}


def supply_params(
    api_key: str,
    member_id: str,
    sid: str,
    *,
    status: str,
    ic: str,
    pg: str,
    date: str | None = None,
    sc: str | None = None,
    sw: str | None = None,
) -> dict[str, str]:
    params = {
        "ver": "1.1",
        "mode": "getAllSupplyChk",
        "aid": api_key,
        "id": member_id,
        "sId": sid,
        "type": "all",
        "om": "json",
        "status": status,
        "ic": str(ic),
        "pg": str(pg),
    }
    if date:
        params["date"] = date
    if sc:
        params["sc"] = sc
    if sw:
        params["sw"] = sw
    return params


def call_supply(session: requests.Session, params: dict[str, str], member_id: str) -> dict[str, Any]:
    try:
        payload = post_form(session, params, SSL_API_URL)
        ok = True
        error = None
    except requests.RequestException as exc:
        payload = {"request_error": exc.__class__.__name__, "message": str(exc)}
        ok = False
        error = exc.__class__.__name__
    root = domeggook_root(payload)
    return {
        "ok": ok,
        "error": error,
        "request": mask_mapping(params, member_id),
        "header": root.get("header") if isinstance(root, dict) else None,
        "items": extract_items(root),
        "payload": payload,
    }


def call_item_view_es(
    session: requests.Session,
    api_key: str,
    item_nos: list[str],
    member_id: str,
    sid: str,
) -> dict[str, Any]:
    params = {
        "ver": "4.0",
        "mode": "getItemViewES",
        "aid": api_key,
        "no": ",".join(item_nos),
        "allItem": "true",
        "sellerId": member_id,
        "sId": sid,
        "om": "json",
    }
    try:
        response = session.get(SSL_API_URL, params=params, timeout=TIMEOUT_SECONDS)
        payload = response.json()
        return {"httpStatus": response.status_code, "request": mask_mapping(params, member_id), "payload": payload}
    except (requests.RequestException, ValueError) as exc:
        return {"request": mask_mapping(params, member_id), "request_error": exc.__class__.__name__}


def call_product_sync_by_nos(session: requests.Session, api_key: str, item_nos: list[str], member_id: str) -> dict[str, Any]:
    body = {
        "size": min(len(item_nos), 100),
        "track_total_hits": True,
        "query": {"bool": {"filter": [{"terms": {"no": item_nos}}]}},
        "sort": [{"no": {"order": "asc"}}],
    }
    return post_product_sync(session, api_key, body, member_id)


def post_product_sync(session: requests.Session, api_key: str, body: dict[str, Any], member_id: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        response = session.post(PRODUCT_SEARCH_URL, headers=headers, json=body, timeout=TIMEOUT_SECONDS)
        payload = response.json()
        return {
            "httpStatus": response.status_code,
            "requestBody": body,
            "payload": payload,
        }
    except (requests.RequestException, ValueError) as exc:
        return {"requestBody": body, "request_error": exc.__class__.__name__}


def run_scope_probes(
    session: requests.Session,
    api_key: str,
    member_id: str,
    sid: str,
    out_dir: Path,
) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    queries = {
        "own_supply_recent_modified": {
            "size": 10,
            "track_total_hits": True,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"seller.id": member_id}},
                        {"term": {"channel.supply": True}},
                    ]
                }
            },
            "sort": [{"dateModify": {"order": "desc"}}, {"no": {"order": "desc"}}],
        },
        "any_supply_recent_modified": {
            "size": 10,
            "track_total_hits": True,
            "query": {"bool": {"filter": [{"term": {"channel.supply": True}}]}},
            "sort": [{"dateModify": {"order": "desc"}}, {"no": {"order": "desc"}}],
        },
        "any_dome_recent_modified": {
            "size": 10,
            "track_total_hits": True,
            "query": {"bool": {"filter": [{"term": {"channel.dome": True}}]}},
            "sort": [{"dateModify": {"order": "desc"}}, {"no": {"order": "desc"}}],
        },
        "both_channels_recent_modified": {
            "size": 10,
            "track_total_hits": True,
            "query": {"bool": {"filter": [{"term": {"channel.dome": True}}, {"term": {"channel.supply": True}}]}},
            "sort": [{"dateModify": {"order": "desc"}}, {"no": {"order": "desc"}}],
        },
    }
    for label, body in queries.items():
        result = post_product_sync(session, api_key, body, member_id)
        write_json(out_dir / f"scope_product_sync_{label}.json", sanitize(result, member_id))
        scope[label] = summarize_product_sync(result)

    candidates: list[str] = []
    for value in scope.values():
        for no in value.get("sampleNos", []):
            candidates.append(no)
    candidates = list(dict.fromkeys(candidates))[:20]
    if candidates:
        params = supply_params(api_key, member_id, sid, status=STATUS_ALL, ic="20", pg="1", sc="no", sw=",".join(candidates))
        result = call_supply(session, params, member_id)
        write_json(out_dir / "scope_getAllSupplyChk_sc_no_candidates.json", sanitize(result, member_id))
        scope["getAllSupplyChk_sc_no_candidates"] = summarize_supply_result(result)
    return scope


def run_pagination_probes(
    session: requests.Session,
    api_key: str,
    member_id: str,
    sid: str,
    out_dir: Path,
) -> dict[str, Any]:
    today = datetime.now(KST).strftime("%Y%m%d")
    probes = {
        "ic_1_pg_1": supply_params(api_key, member_id, sid, status=STATUS_ALL, ic="1", pg="1", date=today),
        "ic_1_pg_2": supply_params(api_key, member_id, sid, status=STATUS_ALL, ic="1", pg="2", date=today),
        "ic_100_pg_1": supply_params(api_key, member_id, sid, status=STATUS_ALL, ic="100", pg="1", date=today),
        "ic_500_pg_1": supply_params(api_key, member_id, sid, status=STATUS_ALL, ic="500", pg="1", date=today),
    }
    results: dict[str, Any] = {}
    for label, params in probes.items():
        result = call_supply(session, params, member_id)
        write_json(out_dir / f"pagination_{label}.json", sanitize(result, member_id))
        results[label] = summarize_supply_result(result)
    first = results.get("ic_1_pg_1", {}).get("sampleEvents", [])
    second = results.get("ic_1_pg_2", {}).get("sampleEvents", [])
    results["ic_1_pg_1_2_overlap"] = sorted(set(event_key(item) for item in first) & set(event_key(item) for item in second))
    return results


def summarize_supply_result(result: dict[str, Any]) -> dict[str, Any]:
    header = result.get("header") if isinstance(result.get("header"), dict) else {}
    items = result.get("items") if isinstance(result.get("items"), list) else []
    return {
        "ok": result.get("ok"),
        "error": result.get("error"),
        "request": result.get("request"),
        "header": header,
        "itemCountCurrentPage": len(items),
        "sampleEvents": [
            {
                "no": str(item.get("no")) if item.get("no") is not None else None,
                "status": item.get("status"),
                "date": item.get("date"),
                "qty": item.get("qty"),
                "price": item.get("price"),
                "sellerHash": stable_hash(item.get("seller")),
            }
            for item in items[:10]
        ],
        "statusCountsCurrentPage": counts(item.get("status") for item in items),
        "ownSellerItemsCurrentPage": sum(1 for item in items if str(item.get("seller")) == str(os.getenv("DOMEGGOOK_ID", ""))),
    }


def summarize_detail(result: dict[str, Any]) -> dict[str, Any]:
    root = domeggook_root(result.get("payload"))
    items = detail_candidates(root)
    return {
        "httpStatus": result.get("httpStatus"),
        "request": result.get("request"),
        "itemCount": len(items),
        "samples": [summarize_detail_item(item) for item in items[:10] if isinstance(item, dict)],
        "error": extract_error(root),
    }


def summarize_detail_item(item: dict[str, Any]) -> dict[str, Any]:
    basis = item.get("basis") if isinstance(item.get("basis"), dict) else {}
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    qty = item.get("qty") if isinstance(item.get("qty"), dict) else {}
    options = parse_select_opt(item.get("selectOpt"))
    return {
        "no": str(basis.get("no") or item.get("no") or item.get("itemNo")),
        "status": basis.get("status") or item.get("status"),
        "price.dome": price.get("dome"),
        "price.supply": price.get("supply"),
        "qty.inventory": qty.get("inventory"),
        "optionSample": options[:5],
    }


def summarize_product_sync(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rows = data.get("list") if isinstance(data.get("list"), list) else []
    return {
        "httpStatus": result.get("httpStatus"),
        "requestError": result.get("request_error"),
        "result": payload.get("result"),
        "totalCount": data.get("totalCount"),
        "searchAfter": data.get("searchAfter"),
        "returnedCount": len(rows),
        "sampleNos": [str(row.get("no")) for row in rows[:10] if row.get("no") is not None],
        "samples": [summarize_sync_item(row) for row in rows[:5] if isinstance(row, dict)],
        "error": payload.get("error") or payload.get("message") or payload.get("msg"),
    }


def summarize_sync_item(item: dict[str, Any]) -> dict[str, Any]:
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    qty = item.get("qty") if isinstance(item.get("qty"), dict) else {}
    channel = item.get("channel") if isinstance(item.get("channel"), dict) else {}
    seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}
    return {
        "no": str(item.get("no")),
        "status": item.get("status"),
        "dateModify": item.get("dateModify"),
        "channel.dome": channel.get("dome"),
        "channel.supply": channel.get("supply"),
        "sellerHash": stable_hash(seller.get("id")),
        "price.dome": price.get("dome"),
        "price.supply": price.get("supply"),
        "qty.inventory": qty.get("inventory"),
        "selectOptPresent": bool(item.get("selectOpt")),
    }


def print_supply_line(label: str, result: dict[str, Any]) -> None:
    summary = summarize_supply_result(result)
    header = summary.get("header") or {}
    print(
        f"{label}: ok={summary['ok']} total={header.get('numberOfItems')} "
        f"page={header.get('currentPage')}/{header.get('numberOfPages')} "
        f"items={summary['itemCountCurrentPage']} statuses={summary['statusCountsCurrentPage']}"
    )


def unique_items_from_results(results: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for result in results.values():
        for item in result.get("sampleEvents", []):
            key = event_key(item)
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def extract_items(root: Any) -> list[dict[str, Any]]:
    if not isinstance(root, dict):
        return []
    container = root.get("items")
    if isinstance(container, dict):
        item = container.get("item")
    else:
        item = root.get("item")
    if isinstance(item, list):
        return [value for value in item if isinstance(value, dict)]
    if isinstance(item, dict):
        return [item]
    return []


def detail_candidates(root: Any) -> list[Any]:
    if not isinstance(root, dict):
        return []
    for key in ("item", "items", "itemView", "data"):
        value = root.get(key)
        if value is None:
            continue
        if isinstance(value, dict) and any(child in value for child in ("item", "items")):
            nested = value.get("item", value.get("items"))
            return nested if isinstance(nested, list) else [nested]
        return value if isinstance(value, list) else [value]
    return [root]


def parse_select_opt(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
        return []
    rows = []
    for key, option in value["data"].items():
        if not isinstance(option, dict):
            continue
        rows.append(
            {
                "key": str(key),
                "name": option.get("name"),
                "domPrice": option.get("domPrice"),
                "supPrice": option.get("supPrice"),
                "qty": option.get("qty"),
            }
        )
    return rows


def post_form(session: requests.Session, params: dict[str, str], url: str) -> dict[str, Any]:
    response = session.post(url, data=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def domeggook_root(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("domeggook"), dict):
        return payload["domeggook"]
    return payload if isinstance(payload, dict) else {}


def extract_error(root: Any) -> Any:
    if not isinstance(root, dict):
        return None
    return root.get("error") or root.get("message") or root.get("msg")


def first_value(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value:
            return str(value)
    return None


def env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def resolve_public_ip(session: requests.Session) -> str:
    try:
        response = session.get("https://api.ipify.org", timeout=5)
        response.raise_for_status()
        text = response.text.strip()
        if text:
            return text
    except requests.RequestException:
        pass
    return socket.gethostbyname(socket.gethostname())


def sanitize(value: Any, member_id: str | None = None) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            if key in SECRET_PARAM_KEYS or key.lower() in {"password", "passwd"}:
                sanitized[key] = mask(child)
            elif key in {"seller", "sellerId", "id"} and isinstance(child, str):
                sanitized[key] = stable_hash(child)
            else:
                sanitized[key] = sanitize(child, member_id)
        return sanitized
    if isinstance(value, list):
        return [sanitize(child, member_id) for child in value]
    if member_id and isinstance(value, str) and value == member_id:
        return stable_hash(value)
    return value


def mask_mapping(mapping: dict[str, Any], member_id: str | None = None) -> dict[str, Any]:
    return {
        key: mask(value) if key in SECRET_PARAM_KEYS else (stable_hash(value) if member_id and value == member_id else value)
        for key, value in mapping.items()
    }


def mask(value: Any) -> str:
    text = str(value)
    if len(text) <= 4:
        return "****"
    return f"{text[:2]}****{text[-2:]}"


def stable_hash(value: Any) -> str | None:
    if value in (None, ""):
        return None
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"


def counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return result


def event_key(item: dict[str, Any]) -> str:
    return "|".join(str(item.get(key)) for key in ("no", "status", "date"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".env").exists() and (candidate / "domeggook_API").is_dir():
            return candidate
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    raise SystemExit(main())
