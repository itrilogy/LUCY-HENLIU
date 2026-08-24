"""自选股：种子、增删、持仓切换。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.service.codes import guess_market

ROOT = Path(__file__).resolve().parent.parent.parent
SEED_PATH = ROOT / "config" / "seed.json"


def load_seed() -> dict:
    if SEED_PATH.exists():
        return json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return {"portfolio_name": "组合", "stocks": []}


def seed_if_empty(db: sqlite3.Connection) -> None:
    if db.execute("SELECT 1 FROM portfolio LIMIT 1").fetchone():
        return
    seed = load_seed()
    name = seed.get("portfolio_name") or "组合"
    pid = db.execute("INSERT INTO portfolio (id,name) VALUES (1,?)", (name,)).lastrowid
    for item in seed.get("stocks") or []:
        code = item["code"]
        market = item.get("market") or guess_market(code)
        holding = 1 if item.get("holding") else 0
        industry = _guess_industry(item.get("name") or "")
        db.execute(
            "INSERT OR IGNORE INTO stock_basic (stock_code,name,market,industry_name) "
            "VALUES (?,?,?,?)",
            (code, item.get("name") or code, market, industry))
        db.execute(
            "INSERT INTO portfolio_stock (portfolio_id,stock_code,market,is_holding) "
            "VALUES (?,?,?,?)",
            (pid, code, market, holding))
    db.commit()


def _guess_industry(stock_name: str) -> str:
    for sec in ("银行", "证券", "半导体", "电力", "医药", "军工",
                "化工", "机械", "白酒", "包装"):
        if sec in (stock_name or ""):
            return sec
    if "ETF" in (stock_name or ""):
        return "ETF基金"
    return "综合"


def add_stock(db: sqlite3.Connection, code: str) -> str:
    code = (code or "").strip().upper()
    if not code:
        return "请输入股票代码"
    if db.execute("SELECT 1 FROM portfolio_stock WHERE stock_code=?", (code,)).fetchone():
        return f"{code} 已在自选中"
    try:
        from src.datasource.sdicsc_client import get_quote
        q = get_quote(code)
        name = q.get("name") or code
        market = guess_market(code)
    except Exception as e:
        return f"股票验证失败: {e}"
    db.execute(
        "INSERT OR IGNORE INTO stock_basic (stock_code,name,market,industry_name) "
        "VALUES (?,?,?,?)",
        (code, name, market, _guess_industry(name)))
    db.execute(
        "INSERT OR IGNORE INTO portfolio_stock "
        "(portfolio_id,stock_code,market,is_holding) VALUES (1,?,?,0)",
        (code, market))
    db.commit()
    return f"已添加 {name} ({code})"


def remove_stock(db: sqlite3.Connection, code: str) -> None:
    db.execute("DELETE FROM portfolio_stock WHERE stock_code=?", (code,))
    db.commit()


def toggle_holding(db: sqlite3.Connection, code: str) -> None:
    db.execute(
        "UPDATE portfolio_stock SET is_holding=1-is_holding WHERE stock_code=?",
        (code,))
    db.commit()


def list_codes(db: sqlite3.Connection) -> list[str]:
    return [r[0] for r in db.execute(
        "SELECT stock_code FROM portfolio_stock ORDER BY stock_code")]
