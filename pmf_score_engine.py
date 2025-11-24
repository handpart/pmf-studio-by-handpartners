import json, os
DEFAULT_WEIGHTS = {
    "problem_score": 0.20,
    "persona_score": 0.10,
    "solution_score": 0.25,
    "market_score": 0.25,
    "retention_score": 0.20
}

def load_weights(path="weights.json"):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                w = json.load(f)
            total = sum(w.values())
            if total <= 0:
                return DEFAULT_WEIGHTS
            return {k: float(v)/total for k,v in w.items()}
        except Exception:
            return DEFAULT_WEIGHTS
    return DEFAULT_WEIGHTS

def map_sean_ellis_to_score(very_disappointed_percent):
    if very_disappointed_percent is None:
        return None
    x = float(very_disappointed_percent)
    if x <= 0:
        return 0.0
    if x >= 100:
        return 100.0
    if x < 20:
        return x * 1.2
    if x < 40:
        return 24 + (x - 20) * 1.8
    return min(100.0, 60 + (x - 40) * 1.0)

def scale_nps_to_0_100(nps):
    try:
        val = float(nps)
        return max(0.0, min(100.0, (val + 100.0) / 2.0))
    except Exception:
        return None

def build_scores_from_raw(raw):
    scores = {}
    problem_text = (raw.get("problem") or "").strip()
    interviews = int(raw.get("interviews_count") or 0)
    if problem_text and interviews >= 8:
        scores["problem_score"] = 90
    elif problem_text and interviews >= 3:
        scores["problem_score"] = 70
    elif interviews >= 8:
        scores["problem_score"] = 60
    else:
        scores["problem_score"] = 35

    persona = raw.get("target")
    if isinstance(persona, list) and len(persona) >= 2:
        scores["persona_score"] = 85
    elif isinstance(persona, list) and len(persona) == 1:
        scores["persona_score"] = 65
    elif isinstance(persona, str) and len(persona) > 10:
        scores["persona_score"] = 60
    else:
        scores["persona_score"] = 30

    sean = raw.get("very_disappointed_percent", None)
    if sean is not None:
        mapped = map_sean_ellis_to_score(sean)
        scores["solution_score"] = mapped
    else:
        nps = raw.get("nps", None)
        mapped_nps = scale_nps_to_0_100(nps) if nps is not None else None
        if mapped_nps is not None:
            scores["solution_score"] = mapped_nps
        else:
            positive_comments = int(raw.get("positive_comments", 0) or 0)
            scores["solution_score"] = 75 if positive_comments >= 5 else 50

    pilots = int(raw.get("pilot_users") or 0)
    paid_customers = int(raw.get("paid_customers") or 0)
    if paid_customers >= 20:
        scores["market_score"] = 90
    elif pilots >= 50:
        scores["market_score"] = 85
    elif pilots >= 10 or interviews >= 10:
        scores["market_score"] = 70
    else:
        scores["market_score"] = 40

    day7 = raw.get("day7_retention", None)
    dau_mau = raw.get("dau_mau", None)
    if day7 is not None:
        try:
            d7 = float(day7)
            if d7 <= 1: d7 = d7 * 100
            scores["retention_score"] = max(0.0, min(100.0, d7))
        except Exception:
            scores["retention_score"] = 40
    elif dau_mau is not None:
        try:
            dm = float(dau_mau)
            if dm <= 1: dm = dm * 100
            scores["retention_score"] = max(0.0, min(100.0, dm * 0.8))
        except Exception:
            scores["retention_score"] = 40
    else:
        scores["retention_score"] = 40

    return scores

def calculate_pmf_score(component_scores=None, weights_path='weights.json'):
    weights = load_weights(weights_path)
    comps = component_scores or {}
    total = 0.0
    for key, w in weights.items():
        val = float(comps.get(key, 0) or 0)
        if val < 0: val = 0
        if val > 100: val = 100
        total += w * val
    pmf_score = round(total, 1)
    if pmf_score <= 40.0:
        stage = "Problem Discovery"
    elif pmf_score <= 60.0:
        stage = "Problem/Solution Fit"
    elif pmf_score <= 80.0:
        stage = "Product/Market Fit (In Progress)"
    else:
        stage = "PMF Achieved"
    return pmf_score, stage, comps
