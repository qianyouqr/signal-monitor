#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公式语法校验：跑一次 runMultiFormula，看 errors[]，不写 state。"""

from datetime import date, timedelta
from typing import Dict, List

from . import quant_buddy, scanner


def validate(job: Dict, assets: List[Dict]) -> Dict:
    sig = job.get("signal") or {}
    formulas_raw = sig.get("formulas") or []
    trigger_name = sig.get("trigger_formula") or "信号"
    display = sig.get("display_fields") or []

    if not formulas_raw:
        return {"ok": False, "reason": "signal.formulas 为空", "missing": [], "errors": []}
    if not assets:
        return {"ok": False, "reason": "资产池为空（无法替换 {ASSETS}）", "missing": [], "errors": []}

    api = quant_buddy.get_api()
    api.new_session()
    QuantAPI = quant_buddy.get_api_class()

    formulas = scanner.materialize_formulas(formulas_raw, assets)
    today = date.today()
    begin = today - timedelta(days=5)
    try:
        resp = api.run_multi_formula(
            formulas=formulas,
            begin_date=int(begin.strftime("%Y%m%d")),
            include_description=False,
        )
    except Exception as e:
        return {"ok": False, "reason": f"runMultiFormula 异常: {type(e).__name__}: {e}",
                "missing": [], "errors": []}

    errors = []
    if isinstance(resp, dict):
        for e in (resp.get("errors") or []):
            errors.append({"name": e.get("leftName"), "error": str(e.get("error", ""))[:300]})

    ids_map = QuantAPI.extract_obj_ids(resp)
    needed = [trigger_name] + list(display)
    missing = [k for k in dict.fromkeys(needed) if k not in ids_map]

    ok = not missing and not errors
    return {
        "ok": ok,
        "reason": "OK" if ok else "公式有错或缺名",
        "formulas_sent": formulas,
        "resolved_names": list(ids_map.keys()),
        "missing": missing,
        "errors": errors,
    }
