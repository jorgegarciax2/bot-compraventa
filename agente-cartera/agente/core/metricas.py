"""Métricas de resultado. Todo en Python puro."""
from __future__ import annotations

import math
from typing import Dict, List, Sequence


def _retornos(equity: Sequence[float]) -> List[float]:
    return [equity[i] / equity[i - 1] - 1
            for i in range(1, len(equity)) if equity[i - 1] > 0]


def resumen(equity: Sequence[float], ticks_por_anio: float,
            operaciones: Sequence[dict] = ()) -> Dict[str, float]:
    if len(equity) < 2:
        return {"error": "serie de equity demasiado corta"}

    inicial, final = equity[0], equity[-1]
    r = _retornos(equity)
    n = len(r)

    total = final / inicial - 1
    anios = n / ticks_por_anio if ticks_por_anio else 0
    cagr = ((final / inicial) ** (1 / anios) - 1) if anios > 0 and final > 0 else 0.0

    media = sum(r) / n if n else 0.0
    var = sum((x - media) ** 2 for x in r) / (n - 1) if n > 1 else 0.0
    desv = math.sqrt(var)
    vol_anual = desv * math.sqrt(ticks_por_anio)
    sharpe = (media / desv * math.sqrt(ticks_por_anio)) if desv > 0 else 0.0

    negativos = [x for x in r if x < 0]
    dd_desv = math.sqrt(sum(x ** 2 for x in negativos) / len(negativos)) if negativos else 0.0
    sortino = (media / dd_desv * math.sqrt(ticks_por_anio)) if dd_desv > 0 else 0.0

    pico = equity[0]
    max_dd = 0.0
    for e in equity:
        pico = max(pico, e)
        if pico > 0:
            max_dd = max(max_dd, 1 - e / pico)

    cerradas = [o for o in operaciones if o.get("realizado") is not None]
    ganadoras = [o for o in cerradas if o["realizado"] > 0]
    perdedoras = [o for o in cerradas if o["realizado"] <= 0]
    beneficio = sum(o["realizado"] for o in ganadoras)
    perdida = abs(sum(o["realizado"] for o in perdedoras))

    return {
        "equity_inicial": inicial,
        "equity_final": final,
        "retorno_total": total,
        "cagr": cagr,
        "volatilidad_anual": vol_anual,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": (cagr / max_dd) if max_dd > 0 else 0.0,
        "ticks": n,
        "operaciones_cerradas": len(cerradas),
        "tasa_acierto": (len(ganadoras) / len(cerradas)) if cerradas else 0.0,
        "factor_beneficio": (beneficio / perdida) if perdida > 0 else 0.0,
    }


def formatea(m: Dict[str, float], divisa: str = "EUR") -> str:
    if "error" in m:
        return m["error"]
    pct = lambda x: f"{x * 100:>8.2f} %"
    return "\n".join([
        f"  Equity inicial      {m['equity_inicial']:>10.2f} {divisa}",
        f"  Equity final        {m['equity_final']:>10.2f} {divisa}",
        f"  Retorno total      {pct(m['retorno_total'])}",
        f"  CAGR               {pct(m['cagr'])}",
        f"  Volatilidad anual  {pct(m['volatilidad_anual'])}",
        f"  Máx. drawdown      {pct(m['max_drawdown'])}",
        f"  Sharpe              {m['sharpe']:>10.2f}",
        f"  Sortino             {m['sortino']:>10.2f}",
        f"  Calmar              {m['calmar']:>10.2f}",
        f"  Operaciones         {m['operaciones_cerradas']:>10d}",
        f"  Tasa de acierto    {pct(m['tasa_acierto'])}",
        f"  Factor beneficio    {m['factor_beneficio']:>10.2f}",
    ])
