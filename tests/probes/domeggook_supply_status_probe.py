from __future__ import annotations

import argparse
import json
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


BASE_URL = "https://www.domeggook.com/ssl/api/"
LEGACY_BASE_URL = "https://domeggook.com/ssl/api/"
OUTPUT_DIR = Path("tests/tmp/domeggook_supply_status")
TIMEOUT_SECONDS = 20


SECRET_KEYS = {"aid", "id", "pw", "sId", "sid", "cId", "cid"}
STATUS_LABELS = {
    "SOLDOUT": "sold out",
    "OPTSOLDOUT": "option sold out",
    "RESTART": "restocked",
    "OPTRESTART": "option restocked",
    "CLOSE": "sale closed",
    "DEL": "deleted",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe Domeggook getAllSupplyChk v1.1 with official setLogin sId."
    )
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--ic", default="10")
    parser.add_argument("--pg", default="1")
    args = parser.parse_args()

    project_root = find_project_root(Path.cwd())
    load_dotenv(project_root / ".env", override=False)

    api_key = env_first("DOMEGGOOK_API_KEY", "DOMEGGOOK_API_KEY_1")
    member_id = env_first("DOMEGGOOK_ID", "DOMEGGOOK_MEMBER_ID")
    password = env_first("DOMEGGOOK_PASSWORD", "DOMEGGOOK_PW")

    print("Checking official login API availability")
    print("Login API: POST https://www.domeggook.com/ssl/api/ mode=setLogin ver=4.1")
    print("Supply status API: POST https://www.domeggook.com/ssl/api/ mode=getAllSupplyChk ver=1.1")

    missing = [
        name
        for name, value in (
            ("DOMEGGOOK_API_KEY or DOMEGGOOK_API_KEY_1", api_key),
            ("DOMEGGOOK_ID", member_id),
            ("DOMEGGOOK_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        print("Required environment variables for the official login API are missing.")
        print("Missing:", ", ".join(missing))
        print("sId issued: failed")
        print("getAllSupplyChk call: failed")
        return 2

    output_dir = project_root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    client_ip = os.getenv("DOMEGGOOK_LOGIN_IP") or resolve_public_ip(session)
    login_params = {
        "ver": "4.1",
        "mode": "setLogin",
        "aid": api_key,
        "id": member_id,
        "pw": password,
        "om": "json",
        "loginKeep": "off",
        "userAgent": "product-data-collector-domeggook-supply-status-probe/1.0",
        "ip": client_ip,
        "device": "Third Party",
    }
    print("Login request params:", json.dumps(mask_mapping(login_params), ensure_ascii=False))

    login_payload, login_root, sid = login(session, login_params, output_dir)

    if not sid:
        print("sId issued: failed")
        print("Login response summary:", json.dumps(mask_mapping(login_root), ensure_ascii=False))
        print("getAllSupplyChk call: failed")
        return 1

    print("sId issued: success")

    base_supply_params = {
        "ver": "1.1",
        "mode": "getAllSupplyChk",
        "aid": api_key,
        "id": member_id,
        "sId": sid,
        "type": "all",
        "om": "json",
        "status": "SOLDOUT",
        "ic": str(args.ic),
        "pg": str(args.pg),
    }
    with_date_params = {**base_supply_params, "date": args.date}
    without_date_params = dict(base_supply_params)

    print("\n[with date] Request params:", json.dumps(mask_mapping(with_date_params), ensure_ascii=False))
    with_date = call_supply_status(session, with_date_params, output_dir / f"getAllSupplyChk_SOLDOUT_{args.date}.json")

    print("\n[without date] Request params:", json.dumps(mask_mapping(without_date_params), ensure_ascii=False))
    without_date = call_supply_status(session, without_date_params, output_dir / "getAllSupplyChk_SOLDOUT_no_date.json")

    print("\nStatus labels:")
    for status, label in STATUS_LABELS.items():
        print(f"- {status}: {label}")

    print("\nResult comparison:")
    print_comparison(with_date, without_date)
    return 0 if with_date["ok"] and without_date["ok"] else 1


def login(
    session: requests.Session,
    params: dict[str, str],
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    attempts = [
        ("4.1", BASE_URL, output_dir / "setLogin_v4_1_response.json"),
        ("1.1", LEGACY_BASE_URL, output_dir / "setLogin_v1_1_response.json"),
    ]
    last_payload: dict[str, Any] = {}
    last_root: dict[str, Any] = {}

    for version, url, output_path in attempts:
        request_params = {**params, "ver": version}
        if version == "1.1":
            print("No sId from setLogin v4.1; checking deprecated v1.1.")
            print("Login request params:", json.dumps(mask_mapping(request_params), ensure_ascii=False))
        try:
            payload = post_form(session, request_params, url=url)
        except requests.RequestException as exc:
            last_payload = {"request_error": exc.__class__.__name__}
            last_root = last_payload
            continue
        write_json(output_path, payload)
        root = domeggook_root(payload)
        sid = first_value(root, "sId", "sid")
        if sid:
            print(f"sId API version: {version}")
            return payload, root, sid
        last_payload = payload
        last_root = root

    return last_payload, last_root, None


def call_supply_status(session: requests.Session, params: dict[str, str], output_path: Path) -> dict[str, Any]:
    try:
        payload = post_form(session, params, url=BASE_URL)
    except requests.RequestException as exc:
        print(f"getAllSupplyChk call: failed ({exc.__class__.__name__})")
        return {"ok": False, "error": exc.__class__.__name__, "params": params, "header": {}, "items": []}

    write_json(output_path, payload)
    root = domeggook_root(payload)
    header = root.get("header") if isinstance(root, dict) else {}
    items = extract_items(root)

    print("getAllSupplyChk call: success")
    print(f"Raw response JSON saved to {output_path}")
    print_summary(header if isinstance(header, dict) else {}, items)
    return {"ok": True, "params": params, "payload": payload, "header": header, "items": items}


def post_form(session: requests.Session, params: dict[str, str], *, url: str) -> dict[str, Any]:
    response = session.post(url, data=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def print_summary(header: dict[str, Any], items: list[dict[str, Any]]) -> None:
    total = header.get("numberOfItems", len(items))
    pages = header.get("numberOfPages", "")
    current_page = header.get("currentPage", "")
    print(f"Total items: {total}")
    if pages != "":
        print(f"Page: {current_page}/{pages}")
    print(f"Items on current page: {len(items)}")
    print("Sold-out item sample:")
    for item in items[:5]:
        print(
            json.dumps(
                {
                    "no": item.get("no"),
                    "title": item.get("title"),
                    "status": item.get("status"),
                    "qty": item.get("qty"),
                    "date": item.get("date"),
                    "seller": item.get("seller"),
                },
                ensure_ascii=False,
            )
        )
    if not items:
        print("(no items)")


def print_comparison(with_date: dict[str, Any], without_date: dict[str, Any]) -> None:
    with_header = with_date.get("header") if isinstance(with_date.get("header"), dict) else {}
    without_header = without_date.get("header") if isinstance(without_date.get("header"), dict) else {}
    with_items = with_date.get("items") or []
    without_items = without_date.get("items") or []

    with_total = parse_int(with_header.get("numberOfItems"), len(with_items))
    without_total = parse_int(without_header.get("numberOfItems"), len(without_items))
    with_pages = parse_int(with_header.get("numberOfPages"), 1)
    without_pages = parse_int(without_header.get("numberOfPages"), 1)
    with_dates = sorted({str(item.get("date")) for item in with_items if item.get("date") is not None})
    without_dates = sorted({str(item.get("date")) for item in without_items if item.get("date") is not None})
    with_statuses = sorted({str(item.get("status")) for item in with_items if item.get("status") is not None})
    without_statuses = sorted({str(item.get("status")) for item in without_items if item.get("status") is not None})

    print(f"- with date response items: {with_total}")
    print(f"- without date response items: {without_total}")
    print(f"- with date current-page item dates: {', '.join(with_dates) if with_dates else '(none)'}")
    print(f"- without date current-page item dates: {', '.join(without_dates) if without_dates else '(none)'}")
    print(f"- with date current-page statuses: {', '.join(with_statuses) if with_statuses else '(none)'}")
    print(f"- without date current-page statuses: {', '.join(without_statuses) if without_statuses else '(none)'}")
    print(f"- with date pagination needed: {'yes' if with_pages > 1 else 'no'}")
    print(f"- without date pagination needed: {'yes' if without_pages > 1 else 'no'}")

    if with_total < without_total and with_dates:
        print("- Interpretation: date appears to narrow results to items changed on the requested day.")
    elif with_total == without_total:
        print("- Interpretation: the current response does not show a date filter difference.")
    else:
        print("- Interpretation: the first page alone is not enough to infer the date filter behavior.")

    if without_dates:
        print("- Conclusion: returned item dates suggest this endpoint is a status-change listing.")
    else:
        print("- Conclusion: no items were returned, so endpoint semantics cannot be confirmed from this run.")


def extract_items(root: Any) -> list[dict[str, Any]]:
    if not isinstance(root, dict):
        return []
    items_container = root.get("items")
    if not isinstance(items_container, dict):
        return []
    item = items_container.get("item")
    if isinstance(item, list):
        return [value for value in item if isinstance(value, dict)]
    if isinstance(item, dict):
        return [item]
    return []


def domeggook_root(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("domeggook"), dict):
        return payload["domeggook"]
    return payload if isinstance(payload, dict) else {}


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


def mask_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: mask(value) if key in SECRET_KEYS else value for key, value in mapping.items()}


def mask(value: Any) -> str:
    text = str(value)
    if len(text) <= 4:
        return "****"
    return f"{text[:2]}****{text[-2:]}"


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


def parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
