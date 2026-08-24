"""股票代码规范化：市场推断、API 前缀、回写组合代码。"""
from __future__ import annotations


def guess_market(code: str) -> str:
    """按代码前缀推断市场（H→HK，6/5→SH，4/8→BJ，其余→SZ）。"""
    c = (code or "").strip().upper()
    if not c:
        return "SZ"
    if c.startswith("H"):
        return "HK"
    if c[0] in "56":
        return "SH"
    if c[0] in "48":
        return "BJ"
    # 沪市可转债/可交换债
    if c.startswith(("110", "113", "118", "132", "120", "122", "124")):
        return "SH"
    return "SZ"


def to_api_code(code: str) -> str:
    """组合代码 → 国投 API 代码：600519 → sh600519，H02380 → hk02380。"""
    c = (code or "").strip()
    if not c:
        return c
    low = c.lower()
    if any(low.startswith(p) for p in ("sh", "sz", "bj", "hk")):
        return low
    market = guess_market(c)
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj", "HK": "hk"}[market]
    bare = c[1:] if c[:1].upper() == "H" else c
    return f"{prefix}{bare.lower() if market == 'HK' else bare}"


def build_code_map(codes: list[str]) -> dict[str, str]:
    """API/裸代码 → 组合内原始代码。"""
    m: dict[str, str] = {}
    for orig in codes:
        o = (orig or "").strip()
        if not o:
            continue
        m[o.lower()] = o
        api = to_api_code(o)
        m[api.lower()] = o
        bare = o[1:] if o[:1].upper() == "H" else o
        m[bare.lower()] = o
    return m


def remap_code(api_code: str, code_map: dict[str, str]) -> str:
    c = (api_code or "").strip()
    if not c:
        return c
    low = c.lower()
    if low in code_map:
        return code_map[low]
    for p in ("sh", "sz", "bj", "hk"):
        if low.startswith(p):
            rest = low[len(p):]
            if rest in code_map:
                return code_map[rest]
    return c
