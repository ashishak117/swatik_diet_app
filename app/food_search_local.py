# app/food_search_local.py
import os
import json
import unicodedata
from typing import Dict, Any, List
from fastapi import APIRouter, Query

router = APIRouter()

# ---- Load Ayurvedic DB once (expects app/ayurveda_db.json) ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AYUR_PATH = os.path.join(BASE_DIR, "ayurveda_db.json")

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

with open(AYUR_PATH, "r", encoding="utf-8") as f:
    _RAW_DB: Dict[str, Any] = json.load(f)

# Precompute normalized index (list of dicts: {name, props, norm})
_DB: List[Dict[str, Any]] = []
for name, props in _RAW_DB.items():
    _DB.append({
        "name": name,
        "norm": _norm(name),
        "props": props
    })

def _score(candidate: str, query: str) -> float:
    """Simple fuzzy score using substring + token overlap (0..1)."""
    if not candidate or not query:
        return 0.0
    if query in candidate:
        # reward direct substring matches with length proximity
        return 0.8 + min(0.19, len(query) / max(len(candidate), 1) * 0.19)
    # token overlap
    cq = set(query.split())
    cc = set(candidate.split())
    if not cq:
        return 0.0
    inter = len(cq & cc)
    uni = len(cq | cc)
    return inter / uni if uni else 0.0

@router.get("/ayur/search")
def search_ayur_foods(
    q: str = Query(..., min_length=1, description="Search text"),
    limit: int = Query(20, ge=1, le=100),
    diabetes_only: bool = Query(False, description="Return only diabetes_safe=true"),
    weight_only: bool = Query(False, description="Return only weight_loss_friendly=true")
):
    """
    JSON-only Food Explorer. Searches local ayurveda_db.json (20k) and returns:
    [
      {
        "name": "...",
        "ayurveda": {
          "rasa": "...",
          "virya": "...",
          "vipaka": "...",
          "dosha_balance": "...",
          "ayurvedic_benefits": "...",
          "diabetes_safe": true/false,
          "weight_loss_friendly": true/false
        }
      }, ...
    ]
    """
    nq = _norm(q)
    scored: List[Dict[str, Any]] = []

    for row in _DB:
        s = _score(row["norm"], nq)
        if s <= 0:
            continue
        ay = row["props"] or {}
        if diabetes_only and not bool(ay.get("diabetes_safe", False)):
            continue
        if weight_only and not bool(ay.get("weight_loss_friendly", False)):
            continue
        scored.append({
            "name": row["name"],
            "ayurveda": ay,
            "score": s
        })

    # If nothing matched via fuzzy, try very loose contains on original keys
    if not scored:
        for row in _DB:
            if nq in row["norm"]:
                ay = row["props"] or {}
                if diabetes_only and not bool(ay.get("diabetes_safe", False)):
                    continue
                if weight_only and not bool(ay.get("weight_loss_friendly", False)):
                    continue
                scored.append({
                    "name": row["name"],
                    "ayurveda": ay,
                    "score": 0.4
                })

    # Sort by score desc, then by shorter name first
    scored.sort(key=lambda x: (-x["score"], len(x["name"])))

    # Trim and remove score from response
    results = [{"name": x["name"], "ayurveda": x["ayurveda"]} for x in scored[:limit]]

    return {"query": q, "count": len(results), "results": results}
