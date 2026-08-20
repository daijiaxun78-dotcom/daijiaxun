from __future__ import annotations

import base64
import hmac
import json
import html
import mimetypes
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DB_PATH = ROOT / "funds.db"

FUNDS = [
    ("007721", "天弘标普500发起(QDII)A", "S&P 500", "A", "CNY", "天弘基金", "2019-09-24"),
    ("007722", "天弘标普500发起(QDII)C", "S&P 500", "C", "CNY", "天弘基金", "2019-09-24"),
    ("017028", "国泰标普500ETF发起联接(QDII)A人民币", "S&P 500", "A", "CNY", "国泰基金", "2022-11-02"),
    ("017030", "国泰标普500ETF发起联接(QDII)C人民币", "S&P 500", "C", "CNY", "国泰基金", "2022-11-02"),
    ("017641", "摩根标普500指数(QDII)人民币A", "S&P 500", "A", "CNY", "摩根基金", "2023-04-06"),
    ("019305", "摩根标普500指数(QDII)人民币C", "S&P 500", "C", "CNY", "摩根基金", "2023-09-01"),
    ("018064", "华夏标普500ETF发起联接(QDII)A人民币", "S&P 500", "A", "CNY", "华夏基金", "2023-05-10"),
    ("018065", "华夏标普500ETF发起联接(QDII)C", "S&P 500", "C", "CNY", "华夏基金", "2023-05-10"),
    ("096001", "大成标普500等权重指数(QDII)A人民币", "S&P 500 Equal Weight", "A", "CNY", "大成基金", "2011-03-23"),
    ("008401", "大成标普500等权重指数(QDII)C人民币", "S&P 500 Equal Weight", "C", "CNY", "大成基金", None),
    ("018043", "天弘纳斯达克100指数发起(QDII)A", "NASDAQ-100", "A", "CNY", "天弘基金", "2023-04-11"),
    ("018044", "天弘纳斯达克100指数发起(QDII)C", "NASDAQ-100", "C", "CNY", "天弘基金", "2023-04-11"),
    ("040046", "华安纳斯达克100ETF联接(QDII)A", "NASDAQ-100", "A", "CNY", "华安基金", "2013-08-02"),
    ("014978", "华安纳斯达克100ETF联接(QDII)C", "NASDAQ-100", "C", "CNY", "华安基金", None),
    ("270042", "广发纳斯达克100ETF联接(QDII)A人民币", "NASDAQ-100", "A", "CNY", "广发基金", "2012-08-15"),
    ("006479", "广发纳斯达克100ETF联接(QDII)C人民币", "NASDAQ-100", "C", "CNY", "广发基金", None),
]

SNAPSHOT_DATE = "2026-08-11"
SNAPSHOT = {
    "007721": (7.90, 25.11, 1.00, "暂停申购", None), "007722": (7.75, 25.11, 1.00, "暂停申购", None),
    "017028": (9.23, 1.95, 0.75, "暂停申购", None), "017030": (9.08, 1.95, 0.75, "暂停申购", None),
    "017641": (8.94, 36.62, 0.65, "有限额", 10), "019305": (8.79, 36.62, 0.65, "有限额", 10),
    "018064": (8.85, 10.00, 0.80, "有限额", 100), "018065": (8.70, 10.00, 0.80, "有限额", 100),
    "096001": (7.25, 7.18, 1.00, "有限额", 10), "008401": (7.10, 7.18, 1.30, "有限额", 10),
    "018043": (11.95, 12.00, 0.60, "暂停申购", None), "018044": (11.80, 12.00, 0.90, "暂停申购", None),
    "040046": (12.26, 47.00, 0.80, "有限额", 10), "014978": (12.11, 47.00, 1.00, "有限额", 10),
    "270042": (11.31, 122.00, 1.00, "有限额", 5), "006479": (11.16, 122.00, 1.20, "有限额", 5),
}

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS funds (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  index_key TEXT NOT NULL CHECK(index_key IN ('S&P 500','S&P 500 Equal Weight','NASDAQ-100')),
  share_class TEXT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'CNY',
  manager TEXT NOT NULL,
  inception_date TEXT,
  asset_size_billion REAL,
  asset_size_date TEXT,
  management_fee REAL,
  custody_fee REAL,
  service_fee REAL,
  profile_source_url TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS navs (
  fund_code TEXT NOT NULL REFERENCES funds(code),
  nav_date TEXT NOT NULL,
  unit_nav REAL,
  cumulative_nav REAL,
  daily_growth_rate REAL,
  purchase_status TEXT,
  redemption_status TEXT,
  source_url TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY(fund_code, nav_date)
);
CREATE TABLE IF NOT EXISTS limit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fund_code TEXT NOT NULL REFERENCES funds(code),
  channel TEXT NOT NULL,
  business_type TEXT NOT NULL,
  status TEXT NOT NULL,
  limit_amount REAL,
  currency TEXT NOT NULL DEFAULT 'CNY',
  limit_scope TEXT NOT NULL DEFAULT '单日单账户累计',
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  announcement_date TEXT NOT NULL,
  announcement_title TEXT NOT NULL,
  announcement_url TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'verified',
  notes TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fee_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fund_code TEXT NOT NULL REFERENCES funds(code),
  fee_type TEXT NOT NULL,
  min_value REAL,
  max_value REAL,
  rate REAL NOT NULL,
  fixed_amount REAL,
  source_url TEXT,
  effective_from TEXT,
  UNIQUE(fund_code, fee_type, min_value, max_value)
);
CREATE INDEX IF NOT EXISTS idx_limit_current ON limit_events(fund_code, effective_from, effective_to);
"""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return result


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with connect() as db:
        db.executescript(SCHEMA)
        existing_columns = {row[1] for row in db.execute("PRAGMA table_info(funds)")}
        for name, definition in (("snapshot_ytd", "REAL"), ("snapshot_date", "TEXT"),
                                 ("snapshot_fee", "REAL"), ("data_quality", "TEXT"),
                                 ("is_active", "INTEGER NOT NULL DEFAULT 1"),
                                 ("platform_ytd", "REAL"), ("platform_ytd_date", "TEXT")):
            if name not in existing_columns:
                db.execute(f"ALTER TABLE funds ADD COLUMN {name} {definition}")
        nav_columns = {row[1] for row in db.execute("PRAGMA table_info(navs)")}
        if "daily_growth_rate" not in nav_columns:
            db.execute("ALTER TABLE navs ADD COLUMN daily_growth_rate REAL")
        db.executemany(
            """INSERT INTO funds
               (code,name,index_key,share_class,currency,manager,inception_date)
               VALUES (?,?,?,?,?,?,?) ON CONFLICT(code) DO NOTHING""",
            FUNDS,
        )
        for code, (ytd, size, fee, _status, _amount) in SNAPSHOT.items():
            db.execute(
                """UPDATE funds SET snapshot_ytd=?, snapshot_date=?, asset_size_billion=?,
                   asset_size_date=?, snapshot_fee=?, data_quality='public_snapshot' WHERE code=?""",
                (ytd, SNAPSHOT_DATE, size, "2026-06-30", fee, code),
            )
        for code, (_ytd, _size, _fee, status, amount) in SNAPSHOT.items():
            if code in ("018064", "018065"):
                continue
            db.execute(
                """UPDATE limit_events
                   SET status=?, limit_amount=?, effective_from=?, announcement_date=?
                   WHERE fund_code=? AND confidence='snapshot'""",
                (status, amount, SNAPSHOT_DATE, SNAPSHOT_DATE, code),
            )
            db.execute(
                """INSERT INTO limit_events
                   (fund_code,channel,business_type,status,limit_amount,currency,limit_scope,
                    effective_from,announcement_date,announcement_title,announcement_url,
                    confidence,notes,created_at)
                   SELECT ?, '代销渠道公开快照', '申购', ?, ?, 'CNY', '单日单账户累计',
                          ?, ?, '公开平台申购状态快照',
                          'https://7c092616aed044f18b0b3aa48dc20241.sh4.agentos-app.net/',
                          'snapshot', '待对应基金公司最新公告核验', datetime('now')
                   WHERE NOT EXISTS (SELECT 1 FROM limit_events WHERE fund_code=? AND confidence='snapshot')""",
                (code, status, amount, SNAPSHOT_DATE, SNAPSHOT_DATE, code),
            )
        db.execute(
            """INSERT INTO limit_events
               (fund_code,channel,business_type,status,limit_amount,currency,limit_scope,
                effective_from,announcement_date,announcement_title,announcement_url,confidence,notes,created_at)
               SELECT '018064','基金公司直销电子平台','申购','有限额',100,'CNY','单日单账户累计',
                      '2026-06-29','2026-06-26','关于在基金管理人直销电子交易平台恢复并限制华夏标普500ETF联接(QDII)人民币申购业务的公告',
                      'https://fund.chinaamc.com/c/2026-06-26/947006.shtml','verified','定投、直销柜台及代销机构仍暂停',datetime('now')
               WHERE NOT EXISTS (SELECT 1 FROM limit_events WHERE fund_code='018064' AND announcement_date='2026-06-26')"""
        )
        db.execute(
            """INSERT INTO limit_events
               (fund_code,channel,business_type,status,limit_amount,currency,limit_scope,
                effective_from,announcement_date,announcement_title,announcement_url,confidence,notes,created_at)
               SELECT '018065','基金公司直销电子平台','申购','有限额',100,'CNY','单日单账户累计',
                      '2026-06-29','2026-06-26','关于在基金管理人直销电子交易平台恢复并限制华夏标普500ETF联接(QDII)人民币申购业务的公告',
                      'https://fund.chinaamc.com/c/2026-06-26/947006.shtml','verified','定投、直销柜台及代销机构仍暂停',datetime('now')
               WHERE NOT EXISTS (SELECT 1 FROM limit_events WHERE fund_code='018065' AND announcement_date='2026-06-26')"""
        )
        db.execute(
            """INSERT INTO limit_events
               (fund_code,channel,business_type,status,limit_amount,currency,limit_scope,
                effective_from,announcement_date,announcement_title,announcement_url,
                confidence,notes,created_at)
               SELECT '021000','全渠道公告','申购/定投/转换转入','有限额',200,'CNY','单日单账户累计',
                      '2026-07-21','2026-07-20','关于调整南方纳斯达克100指数发起式证券投资基金（QDII）申购、定投及转换转入业务金额限制的公告',
                      'https://www.chnfund.com/article/212c774f-a907-623e-e85f-3a2290d8bc47',
                      'verified','I类份额限额200元；销售渠道是否代销另行展示',datetime('now')
               WHERE EXISTS (SELECT 1 FROM funds WHERE code='021000')
                 AND NOT EXISTS (SELECT 1 FROM limit_events WHERE fund_code='021000'
                 AND confidence='verified' AND effective_from='2026-07-21')"""
        )


def api_get(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Referer": "https://fundf10.eastmoney.com/",
            "User-Agent": "Mozilla/5.0 QDII-Fund-Limit-Tracker/0.1",
        },
    )
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8", errors="replace")
            break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
    else:
        raise last_error
    # The endpoint occasionally appends digits after the JSON document.
    match = re.match(r"\s*(\{.*\})\s*\d*\s*$", raw, re.DOTALL)
    if not match:
        raise ValueError("上游接口返回的不是有效 JSON")
    return json.loads(match.group(1))


def fetch_text(url: str, referer: str = "https://fund.eastmoney.com/") -> str:
    request = urllib.request.Request(url, headers={"Referer": referer, "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def classify_target(name: str) -> str | None:
    if "标普500等权重" in name:
        return "S&P 500 Equal Weight"
    if "纳斯达克100" in name or "纳指100" in name:
        return "NASDAQ-100"
    if "标普500" in name:
        return "S&P 500"
    return None


def is_otc_cny_share(code: str, name: str) -> bool:
    return not code.startswith(("15", "51")) and not any(token in name for token in ("美元", "美钞", "美汇"))


def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def parse_sales_page(code: str, name: str, page: str) -> dict:
    def first(pattern: str) -> str | None:
        match = re.search(pattern, page, re.DOTALL)
        return strip_tags(match.group(1)) if match else None

    inception = first(r"成\s*立\s*日</span>：([^<]+)")
    manager = first(r"管\s*理\s*人</span>：<a[^>]*>(.*?)</a>")
    size_match = re.search(r"规模</a>：([\d.]+)亿元（(\d{4}-\d{2}-\d{2})）", page)
    target = first(r"跟踪标的：</a>(.*?)\s*\|")
    stage_match = re.search(r'id="increaseAmount_stage".*?</table>', page, re.DOTALL)
    stage_values = re.findall(r'<div class="Rdata[^"]*">\s*([+-]?[\d.]+)%\s*</div>',
                              stage_match.group(0)) if stage_match else []
    platform_ytd = float(stage_values[4]) if len(stage_values) >= 5 else None
    platform_ytd_date = first(r'id="jdzfDate">(\d{4}-\d{2}-\d{2})</span>')
    status_text = first(r"交易状态：</span><span[^>]*>(.*?)</span><span") or ""
    amount_match = re.search(r"单日累计购买上限([\d,.]+)元", status_text)
    if "暂不开放购买" in page:
        status, amount = "不代销", None
    elif "暂停申购" in status_text:
        status, amount = "暂停申购", None
    elif "限大额" in status_text:
        status = "有限额"
        amount = float(amount_match.group(1).replace(",", "")) if amount_match else None
    elif "开放申购" in status_text:
        status, amount = "开放申购", None
    else:
        status, amount = "待核验", None
    class_match = re.search(r"([ACDEFI])(?:人民币|\(人民币\))?$", name)
    return {
        "code": code, "name": name, "index_key": classify_target(name),
        "share_class": class_match.group(1) if class_match else "A", "currency": "CNY",
        "manager": manager or "待补充", "inception_date": inception,
        "asset_size_billion": float(size_match.group(1)) if size_match else None,
        "asset_size_date": size_match.group(2) if size_match else None,
        "platform_ytd": platform_ytd, "platform_ytd_date": platform_ytd_date,
        "target": target, "status": status, "limit_amount": amount,
        "source_url": f"https://fund.eastmoney.com/{code}.html",
    }


def refresh_fees(code: str) -> tuple[float | None, float | None, float | None]:
    page = fetch_text(f"https://fundf10.eastmoney.com/jjfl_{code}.html")
    rates = [float(value) for value in re.findall(r'<td class="w135">([\d.]+)%', page)[:3]]
    if len(rates) != 3:
        return None, None, None
    with connect() as db:
        db.execute("UPDATE funds SET management_fee=?,custody_fee=?,service_fee=? WHERE code=?",
                   (*rates, code))
    return tuple(rates)


def discover_sales_funds() -> list[dict]:
    catalog = fetch_text("https://fund.eastmoney.com/js/fundcode_search.js")
    match = re.search(r"var r = (.*);", catalog, re.DOTALL)
    if not match:
        raise ValueError("天天基金目录格式发生变化")
    rows = json.loads(match.group(1))
    candidates = [(row[0], row[2]) for row in rows
                  if classify_target(row[2]) and is_otc_cny_share(row[0], row[2])]
    funds = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_text, f"https://fund.eastmoney.com/{code}.html"): (code, name)
                   for code, name in candidates}
        for future in as_completed(futures):
            code, name = futures[future]
            try:
                parsed = parse_sales_page(code, name, future.result())
            except (urllib.error.URLError, TimeoutError):
                continue
            if parsed["index_key"]:
                funds.append(parsed)
    return sorted(funds, key=lambda item: (item["index_key"], item["code"]))


def sync_sales_catalog() -> list[str]:
    funds = discover_sales_funds()
    today = date.today().isoformat()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with connect() as db:
        db.execute("UPDATE funds SET is_active=0")
        for fund in funds:
            db.execute(
                """INSERT INTO funds
                   (code,name,index_key,share_class,currency,manager,inception_date,
                    asset_size_billion,asset_size_date,profile_source_url,updated_at,
                    platform_ytd,platform_ytd_date,data_quality,is_active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'sales_live',1)
                   ON CONFLICT(code) DO UPDATE SET name=excluded.name,index_key=excluded.index_key,
                   share_class=excluded.share_class,currency=excluded.currency,manager=excluded.manager,
                   inception_date=COALESCE(excluded.inception_date,funds.inception_date),
                   asset_size_billion=COALESCE(excluded.asset_size_billion,funds.asset_size_billion),
                   asset_size_date=COALESCE(excluded.asset_size_date,funds.asset_size_date),
                   platform_ytd=excluded.platform_ytd,platform_ytd_date=excluded.platform_ytd_date,
                   profile_source_url=excluded.profile_source_url,updated_at=excluded.updated_at,
                   data_quality='sales_live',is_active=1""",
                (fund["code"], fund["name"], fund["index_key"], fund["share_class"], "CNY",
                 fund["manager"], fund["inception_date"], fund["asset_size_billion"],
                 fund["asset_size_date"], fund["source_url"], now,
                 fund["platform_ytd"], fund["platform_ytd_date"]),
            )
            db.execute(
                """UPDATE limit_events SET effective_to=date(?,'-1 day')
                   WHERE fund_code=? AND channel='天天基金' AND effective_to IS NULL
                   AND (status<>? OR COALESCE(limit_amount,-1)<>COALESCE(?,-1))""",
                (today, fund["code"], fund["status"], fund["limit_amount"]),
            )
            db.execute(
                """INSERT INTO limit_events
                   (fund_code,channel,business_type,status,limit_amount,currency,limit_scope,
                    effective_from,announcement_date,announcement_title,announcement_url,
                    confidence,notes,created_at)
                   SELECT ?,'天天基金','申购',?,?,'CNY','单日单账户累计',?,?,?,?,'channel_live',?,?
                   WHERE NOT EXISTS (SELECT 1 FROM limit_events WHERE fund_code=? AND channel='天天基金'
                     AND effective_to IS NULL AND status=? AND COALESCE(limit_amount,-1)=COALESCE(?,-1))""",
                (fund["code"], fund["status"], fund["limit_amount"], today, today,
                 f"天天基金渠道交易状态：{fund['status']}", fund["source_url"],
                 "第三方销售渠道实时页面；不代表其他渠道额度", now, fund["code"],
                fund["status"], fund["limit_amount"]),
            )
        db.execute(
            """INSERT INTO limit_events
               (fund_code,channel,business_type,status,limit_amount,currency,limit_scope,
                effective_from,announcement_date,announcement_title,announcement_url,
                confidence,notes,created_at)
               SELECT '021000','全渠道公告','申购/定投/转换转入','有限额',200,'CNY','单日单账户累计',
                      '2026-07-21','2026-07-20','关于调整南方纳斯达克100指数发起式证券投资基金（QDII）申购、定投及转换转入业务金额限制的公告',
                      'https://www.chnfund.com/article/212c774f-a907-623e-e85f-3a2290d8bc47',
                      'verified','I类份额限额200元；销售渠道是否代销另行展示',datetime('now')
               WHERE EXISTS (SELECT 1 FROM funds WHERE code='021000')
                 AND NOT EXISTS (SELECT 1 FROM limit_events WHERE fund_code='021000'
                   AND confidence='verified' AND effective_from='2026-07-21')"""
        )
    return [fund["code"] for fund in funds]


def refresh_fund(code: str) -> int:
    year = date.today().year
    ranges = [(f"{year}-01-01", date.today().isoformat()),
              (f"{year - 1}-12-01", f"{year - 1}-12-31")]
    rows = []
    source_url = ""
    for start, end in ranges:
        page_index = 1
        with connect() as db:
            known_growth_dates = {
                row[0] for row in db.execute(
                    "SELECT nav_date FROM navs WHERE fund_code=? AND nav_date>=? AND nav_date<=? "
                    "AND daily_growth_rate IS NOT NULL",
                    (code, start, end),
                )
            }
        while True:
            params = urllib.parse.urlencode(
                {"fundCode": code, "pageIndex": page_index, "pageSize": 100,
                 "startDate": start, "endDate": end}
            )
            url = f"https://api.fund.eastmoney.com/f10/lsjz?{params}"
            source_url = source_url or url
            payload = api_get(url)
            data = payload.get("Data")
            if not isinstance(data, dict):
                message = payload.get("ErrMsg") or f"上游接口未返回数据（ErrCode={payload.get('ErrCode')}）"
                raise ValueError(message)
            page_rows = data.get("LSJZList") or []
            rows.extend(page_rows)
            if start.endswith("-12-01") or any(row.get("FSRQ") in known_growth_dates for row in page_rows):
                break
            page_size = payload.get("PageSize") or len(page_rows)
            total_count = payload.get("TotalCount") or len(page_rows)
            if not page_rows or page_index * page_size >= total_count:
                break
            page_index += 1
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    values = []
    for row in rows:
        values.append(
            (
                code,
                row["FSRQ"],
                float(row["DWJZ"]) if row.get("DWJZ") else None,
                float(row["LJJZ"]) if row.get("LJJZ") else None,
                float(row["JZZZL"]) if row.get("JZZZL") not in (None, "") else None,
                row.get("SGZT"),
                row.get("SHZT"),
                source_url,
                now,
            )
        )
    with connect() as db:
        db.executemany(
            """INSERT INTO navs
               (fund_code,nav_date,unit_nav,cumulative_nav,daily_growth_rate,
                purchase_status,redemption_status,source_url,fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(fund_code,nav_date) DO UPDATE SET
               unit_nav=excluded.unit_nav,cumulative_nav=excluded.cumulative_nav,
               daily_growth_rate=excluded.daily_growth_rate,
               purchase_status=excluded.purchase_status,redemption_status=excluded.redemption_status,
               source_url=excluded.source_url,fetched_at=excluded.fetched_at""",
            values,
        )
        db.execute("UPDATE funds SET updated_at=? WHERE code=?", (now, code))
    return len(values)


def calculate_cost(amount: float, days: int, purchase_rate: float, redemption_rate: float,
                   service_rate: float, management_rate: float, custody_rate: float) -> dict:
    purchase_cost = amount * purchase_rate / 100
    redemption_cost = amount * redemption_rate / 100
    annual_product_cost = amount * (service_rate + management_rate + custody_rate) / 100 * days / 365
    return {
        "purchase_cost": purchase_cost,
        "redemption_cost": redemption_cost,
        "annual_product_cost": annual_product_cost,
        "investor_paid_cost": purchase_cost + redemption_cost,
        "estimated_total_cost": purchase_cost + redemption_cost + annual_product_cost,
    }


def list_funds() -> list[dict]:
    current_year = str(date.today().year)
    previous_year = str(date.today().year - 1)
    with connect() as db:
        funds = db.execute("SELECT * FROM funds WHERE is_active=1 ORDER BY index_key, code").fetchall()
        result = []
        for fund in funds:
            latest = db.execute(
                "SELECT * FROM navs WHERE fund_code=? ORDER BY nav_date DESC LIMIT 1", (fund["code"],)
            ).fetchone()
            base = db.execute(
                """SELECT * FROM navs WHERE fund_code=? AND nav_date>=? AND nav_date<?
                   ORDER BY nav_date DESC LIMIT 1""",
                (fund["code"], f"{previous_year}-01-01", f"{current_year}-01-01"),
            ).fetchone()
            daily_returns = db.execute(
                """SELECT nav_date, daily_growth_rate FROM navs
                   WHERE fund_code=? AND nav_date>=? AND nav_date<=?
                   ORDER BY nav_date""",
                (fund["code"], f"{current_year}-01-01",
                 latest["nav_date"] if latest else f"{current_year}-12-31"),
            ).fetchall()
            official_limit = db.execute(
                """SELECT * FROM limit_events WHERE fund_code=? AND effective_from<=date('now','localtime')
                   AND (effective_to IS NULL OR effective_to>=date('now','localtime'))
                   AND confidence='verified'
                   ORDER BY effective_from DESC, announcement_date DESC, id DESC LIMIT 1""",
                (fund["code"],),
            ).fetchone()
            channel_limit = db.execute(
                """SELECT * FROM limit_events WHERE fund_code=? AND effective_from<=date('now','localtime')
                   AND (effective_to IS NULL OR effective_to>=date('now','localtime'))
                   AND confidence='channel_live'
                   ORDER BY effective_from DESC, id DESC LIMIT 1""",
                (fund["code"],),
            ).fetchone()
            fallback_limit = db.execute(
                """SELECT * FROM limit_events WHERE fund_code=? AND effective_from<=date('now','localtime')
                   AND (effective_to IS NULL OR effective_to>=date('now','localtime'))
                   ORDER BY effective_from DESC, id DESC LIMIT 1""",
                (fund["code"],),
            ).fetchone()
            item = dict(fund)
            item.update(
                latest_nav=latest["unit_nav"] if latest else None,
                nav_date=latest["nav_date"] if latest else None,
                purchase_status=latest["purchase_status"] if latest else None,
                redemption_status=latest["redemption_status"] if latest else None,
                ytd=fund["snapshot_ytd"],
                ytd_source="公开快照" if fund["snapshot_ytd"] is not None else None,
                ytd_base_date=base["nav_date"] if base else None,
                limit=dict(official_limit or channel_limit or fallback_limit) if (official_limit or channel_limit or fallback_limit) else None,
                official_limit=dict(official_limit) if official_limit else None,
                channel_limit=dict(channel_limit) if channel_limit else None,
            )
            if (latest and base and daily_returns
                    and daily_returns[0]["nav_date"] <= f"{current_year}-01-10"
                    and all(row["daily_growth_rate"] is not None for row in daily_returns)):
                growth = 1.0
                for row in daily_returns:
                    growth *= 1 + row["daily_growth_rate"] / 100
                item["ytd"] = (growth - 1) * 100
                item["ytd_source"] = "正式日增长率复利计算"
            if (latest and fund["platform_ytd"] is not None
                    and fund["platform_ytd_date"] == latest["nav_date"]):
                item["ytd"] = fund["platform_ytd"]
                item["ytd_source"] = "天天基金阶段涨幅"
            result.append(item)
        return result


class Handler(BaseHTTPRequestHandler):
    server_version = "QDIIFundTracker/0.1"

    def check_auth(self) -> bool:
        password = os.environ.get("QDII_WEB_PASSWORD")
        if not password:
            return True
        expected = "Basic " + base64.b64encode(f"fund:{password}".encode()).decode()
        if hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="QDII Fund Monitor", charset="UTF-8"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        if not self.check_auth():
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/funds":
            self.send_json({"funds": list_funds(), "as_of": datetime.now().astimezone().isoformat(timespec="seconds")})
            return
        if parsed.path == "/api/limits":
            query = urllib.parse.parse_qs(parsed.query)
            code = query.get("code", [""])[0]
            with connect() as db:
                rows = db.execute(
                    "SELECT * FROM limit_events WHERE fund_code=? ORDER BY effective_from DESC, id DESC", (code,)
                ).fetchall()
            self.send_json({"limits": [dict(row) for row in rows]})
            return
        if parsed.path == "/api/health":
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/cost":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                numbers = {key: float(query.get(key, ["0"])[0]) for key in
                           ("amount", "purchase_rate", "redemption_rate", "service_rate", "management_rate", "custody_rate")}
                days = int(query.get("days", ["0"])[0])
                if numbers["amount"] < 0 or days < 0:
                    raise ValueError
            except ValueError:
                self.send_json({"error": "金额和天数必须是非负数"}, 400)
                return
            self.send_json(calculate_cost(days=days, **numbers))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        if not self.check_auth():
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/refresh":
            payload = self.read_json()
            try:
                discovered = sync_sales_catalog()
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                self.send_json({"refreshed": {}, "errors": {"catalog": str(exc)}}, 502)
                return
            codes = payload.get("codes") or discovered
            refreshed, errors = {}, {}
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(refresh_fund, str(code)): str(code) for code in codes}
                for future in as_completed(futures):
                    code = futures[future]
                    try:
                        refreshed[code] = future.result()
                    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                        errors[code] = str(exc)
            self.send_json({"discovered": len(discovered), "refreshed": refreshed, "errors": errors},
                           200 if not errors else 207)
            return
        if parsed.path == "/api/limits":
            payload = self.read_json()
            required = ["fund_code", "channel", "business_type", "status", "effective_from", "announcement_date", "announcement_title", "announcement_url"]
            missing = [key for key in required if not str(payload.get(key, "")).strip()]
            if missing:
                self.send_json({"error": "缺少字段：" + ", ".join(missing)}, 400)
                return
            values = (
                payload["fund_code"], payload["channel"], payload["business_type"], payload["status"],
                payload.get("limit_amount"), payload.get("currency", "CNY"), payload.get("limit_scope", "单日单账户累计"),
                payload["effective_from"], payload.get("effective_to"), payload["announcement_date"],
                payload["announcement_title"], payload["announcement_url"], payload.get("confidence", "verified"),
                payload.get("notes"), datetime.now().astimezone().isoformat(timespec="seconds"),
            )
            with connect() as db:
                cursor = db.execute(
                    """INSERT INTO limit_events
                    (fund_code,channel,business_type,status,limit_amount,currency,limit_scope,effective_from,effective_to,
                     announcement_date,announcement_title,announcement_url,confidence,notes,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values
                )
            self.send_json({"id": cursor.lastrowid}, 201)
            return
        self.send_json({"error": "Not found"}, 404)

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path == "/" else request_path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> None:
    init_db()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"QDII 基金限额跟进：http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
