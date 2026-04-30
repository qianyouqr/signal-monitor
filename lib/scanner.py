#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信号扫描：构造矩阵公式 → runMultiFormula → read_data → 触发判定。"""

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import asset_source, cooldown, quant_buddy

ASSETS_PLACEHOLDER = "{ASSETS}"


def _build_pool_args(assets: List[Dict]) -> str:
    return ", ".join(a["company"] for a in assets if a.get("company"))


def materialize_formulas(formulas: List[Dict], assets: List[Dict]) -> List[str]:
    """把 job.signal.formulas 实例化成 quant-buddy 接受的字符串列表。"""
    pool_args = _build_pool_args(assets)
    out = []
    for f in formulas:
        name = f.get("name", "").strip()
        expr = f.get("expression", "")
        if ASSETS_PLACEHOLDER in expr:
            expr = expr.replace(ASSETS_PLACEHOLDER, pool_args)
        out.append(f"{name} = {expr}" if name else expr)
    return out


def _extract_last_column_map(item: Dict) -> Dict[str, Any]:
    for key in ("last_column_full", "last_day_stats"):
        block = item.get(key)
        if not isinstance(block, dict):
            continue
        values = block.get("values") or []
        if values and isinstance(values, list) and isinstance(values[0], dict):
            mapped = {}
            for row in values:
                a = row.get("asset")
                v = row.get("value")
                if a is not None and v is not None:
                    mapped[str(a)] = v
            if mapped:
                return mapped
        assets = block.get("assets") or []
        if assets and len(assets) == len(values):
            return {str(a): v for a, v in zip(assets, values) if v is not None}
    return {}


def _extract_last_date(item: Dict) -> str:
    block = item.get("last_column_full") or item.get("last_day_stats") or {}
    d = block.get("date")
    if isinstance(d, int):
        s = str(d)
        if len(s) == 8:
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(d) if d else ""


def _resolve_codes(api, assets: List[Dict]) -> Dict[str, str]:
    intentions = [a["company"] for a in assets]
    code_map = {}
    try:
        resp = api.confirm_multiple_assets(intentions)
    except Exception:
        return {a["company"]: a["ticker"] for a in assets}
    inner = resp.get("data") if isinstance(resp, dict) and "data" in resp else resp
    items = inner if isinstance(inner, list) else (
        (inner or {}).get("results") or (inner or {}).get("assets") or []
    )
    found = {}
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            intention = it.get("intention") or it.get("name") or it.get("query")
            code = it.get("code") or it.get("ticker") or it.get("asset_code")
            if intention and code:
                found[intention] = code
    for a in assets:
        code_map[a["company"]] = found.get(a["company"], a["ticker"])
    return code_map


def run_signal(job: Dict, assets: List[Dict]) -> Dict:
    """跑一遍信号，返回结构化结果。不写任何 state。"""
    sig = job.get("signal") or {}
    formulas_raw = sig.get("formulas") or []
    trigger_name = sig.get("trigger_formula") or "信号"
    display_fields = sig.get("display_fields") or []
    lookback = int(sig.get("lookback_days") or 60)

    if not assets:
        return {"by_ticker": {}, "fatal": "资产池为空", "anomalies": [], "last_date": ""}
    if not formulas_raw:
        return {"by_ticker": {}, "fatal": "signal.formulas 为空", "anomalies": [], "last_date": ""}

    api = quant_buddy.get_api()
    api.new_session()
    QuantAPI = quant_buddy.get_api_class()

    code_map = _resolve_codes(api, assets)
    formulas = materialize_formulas(formulas_raw, assets)

    today = date.today()
    begin = today - timedelta(days=lookback)
    try:
        resp = api.run_multi_formula(
            formulas=formulas,
            begin_date=int(begin.strftime("%Y%m%d")),
            include_description=False,
        )
    except Exception as e:
        return {"by_ticker": {}, "fatal": f"runMultiFormula 异常: {type(e).__name__}: {str(e)[:200]}",
                "anomalies": [], "last_date": ""}
    if isinstance(resp, dict) and resp.get("code", 0) != 0:
        # 错误信息可能在顶层 message，也可能嵌在 error.message（如版本过期提示）
        err_obj = resp.get("error") or {}
        msg = (resp.get("message") or err_obj.get("message") or
               resp.get("_raw") or str(resp))[:300]
        return {"by_ticker": {}, "fatal": f"runMultiFormula code={resp.get('code')}: {msg}",
                "anomalies": [], "last_date": ""}

    ids_map = QuantAPI.extract_obj_ids(resp)
    needed = [trigger_name] + list(display_fields)
    needed = list(dict.fromkeys(needed))  # dedupe, preserve order
    missing = [k for k in needed if k not in ids_map]
    if missing:
        errors = (resp.get("errors") or [])
        es = "; ".join(f"{e.get('leftName')}: {str(e.get('error',''))[:100]}" for e in errors)
        return {"by_ticker": {}, "fatal": f"公式缺失 {missing}; errors: {es[:300]}",
                "anomalies": [], "last_date": ""}

    try:
        rd = api.read_data(ids=[ids_map[k] for k in needed], mode="last_column_full")
    except Exception as e:
        return {"by_ticker": {}, "fatal": f"read_data 异常: {type(e).__name__}: {str(e)[:200]}",
                "anomalies": [], "last_date": ""}

    items = rd.get("data") if isinstance(rd, dict) else None
    if not isinstance(items, list):
        return {"by_ticker": {}, "fatal": f"read_data 返回异常: {str(rd)[:300]}",
                "anomalies": [], "last_date": ""}

    by_id = {it.get("id"): it for it in items if isinstance(it, dict)}
    maps: Dict[str, Dict[str, Any]] = {}
    last_date = ""
    for name in needed:
        item = by_id.get(ids_map[name]) or {}
        maps[name] = _extract_last_column_map(item)
        if not last_date:
            last_date = _extract_last_date(item)

    by_ticker = {}
    anomalies = []
    trig_map = maps[trigger_name]
    for a in assets:
        code = code_map.get(a["company"], a["ticker"])
        trig = trig_map.get(code, trig_map.get(a["ticker"]))
        if trig is None:
            anomalies.append({**a, "error": f"trigger_formula `{trigger_name}` 无数据 (code={code})"})
            continue
        try:
            trig_v = float(trig)
        except (TypeError, ValueError):
            anomalies.append({**a, "error": f"trigger 非数值: {trig}"})
            continue
        record = {
            "ticker": a["ticker"], "company": a["company"], "code": code,
            "date": last_date,
            "triggered": trig_v >= 0.5,
            "trigger_value": trig_v,
            "fields": {},
        }
        for name in display_fields:
            v = maps[name].get(code, maps[name].get(a["ticker"]))
            try:
                record["fields"][name] = round(float(v), 4) if v is not None else None
            except (TypeError, ValueError):
                record["fields"][name] = v
        by_ticker[a["ticker"]] = record

    return {"by_ticker": by_ticker, "fatal": None, "anomalies": anomalies, "last_date": last_date}


def apply_cooldown(records: Dict, state: Dict, today: date, cooldown_days: int) -> Tuple[List[Dict], List[Dict]]:
    """把 by_ticker 拆成 (triggered, cooled_down)。"""
    triggered, cooled = [], []
    for ticker, rec in records.items():
        if not rec["triggered"]:
            continue
        last = state.get(ticker)
        if last and cooldown.is_cooled_down(last, today, cooldown_days):
            cooled.append({**rec, "last_triggered": last,
                           "cooldown_end": cooldown.cooldown_end(last, cooldown_days)})
        else:
            triggered.append(rec)
    return triggered, cooled
