from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import server


OUTPUT = server.STATIC_DIR / "data.json"


def limit_history() -> dict[str, list[dict]]:
    with server.connect() as db:
        rows = db.execute(
            "SELECT * FROM limit_events ORDER BY fund_code, effective_from DESC, id DESC"
        ).fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        result.setdefault(row["fund_code"], []).append(dict(row))
    return result


def merge_previous(funds: list[dict], previous_path: Path) -> list[dict]:
    if not previous_path.exists():
        return funds
    previous = {
        item["code"]: item
        for item in json.loads(previous_path.read_text(encoding="utf-8")).get("funds", [])
    }
    for fund in funds:
        old = previous.get(fund["code"])
        if not old:
            continue
        for key in ("latest_nav", "nav_date", "ytd", "ytd_source", "ytd_base_date"):
            if fund.get(key) is None:
                fund[key] = old.get(key)
    return funds


def refresh() -> tuple[int, dict[str, str]]:
    codes = server.sync_sales_catalog()
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(server.refresh_fund, code): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                future.result()
            except (OSError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                errors[code] = str(exc)
    return len(codes), errors


def export(output: Path = OUTPUT) -> dict:
    funds = merge_previous(server.list_funds(), output)
    payload = {
        "as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
        "funds": funds,
        "limits": limit_history(),
    }
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(output)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    server.init_db()
    discovered, errors = (refresh() if args.refresh else (0, {}))
    payload = export()
    print(json.dumps({"discovered": discovered, "funds": len(payload["funds"]), "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
