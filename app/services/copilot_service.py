"""AI analyst copilot: case summaries, cardholder message drafts and a natural-language search box.

Provider: Google Gemini over REST when FRAUD_GEMINI_API_KEY is set, otherwise (or if the call fails) a deterministic offline engine,
so the feature always works, including without internet. Only the synthetic fields of one transaction are ever sent out.

The chat never lets a model write SQL. The model (or the offline parser) only fills a small JSON filter; every field is validated
against a whitelist and executed as a parameterised query.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3

import httpx

from app.core.config import Settings
from app.core.errors import Invalid

from . import transactions_service

log = logging.getLogger("fraud.copilot")
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DECISIONS, REVIEWS, CHANNELS = {"APPROVE", "HOLD", "DECLINE"}, {"OPEN", "CONFIRMED_FRAUD", "FALSE_POSITIVE"}, {"ONLINE", "POS", "ATM"}
FILTER_KEYS = {"decision", "review", "channel", "city", "merchant", "min_amount", "max_amount", "min_score", "card_last4", "limit"}


def status(settings: Settings) -> dict:
    return {"provider": "gemini" if settings.gemini_api_key else "offline", "model": settings.gemini_model if settings.gemini_api_key else "rule-based",
            "note": "Only synthetic data is sent to the external model. Without a key everything runs offline."}


# ---------- provider ----------
def _gemini(settings: Settings, prompt: str, *, client: httpx.Client | None = None) -> dict:
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    own = client is None
    client = client or httpx.Client(timeout=12.0)
    try:
        r = client.post(API.format(model=settings.gemini_model), json=body, headers={"x-goog-api-key": settings.gemini_api_key or ""})
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    finally:
        if own:
            client.close()


# ---------- case summary ----------
def _facts(d: dict) -> dict:
    top = []
    for f in d.get("factors", []):
        if f.get("code") == "ml_model" and f.get("detail"):
            top = f["detail"].get("top", [])
    cust = d.get("customer") or {}
    return {"amount_inr": d["amount"] if d["currency"] == "INR" else f"{d['amount']} {d['currency']}", "merchant": d["merchant"], "city": d.get("location"), "country": d["country"],
            "channel": d["channel"], "risk_score": d["score"], "decision": d["decision"], "model_top_reasons": top,
            "reasons": d.get("reasons", [])[:6], "cardholder_city": cust.get("city"), "cardholder_reply": d.get("cardholder_response"),
            "previous_transactions_on_card": len(d.get("token_history", [])), "review_status": d["review"]}


def _offline_case(f: dict, name: str) -> dict:
    why = ", ".join(t["feature"].lower() for t in f["model_top_reasons"][:3]) or (", ".join(f["reasons"][:3]) or "no strong signals")
    amount = f"₹{f['amount_inr']:,.0f}" if isinstance(f["amount_inr"], (int, float)) else str(f["amount_inr"])
    summary = (f"{amount} {f['channel'].lower()} payment at {f['merchant']}{' in ' + f['city'] if f['city'] else ''} scored {f['risk_score']:.2f} and was {f['decision'].lower()}d "
              f"mainly because of {why}.")
    if f["cardholder_reply"] == "NOT_ME":
        rec = "Cardholder says it was not them. Confirm fraud and keep the card blocked."
    elif f["cardholder_reply"] == "LEGIT":
        rec = "Cardholder confirmed the payment. Mark as a false positive and release the card."
    elif f["decision"] == "DECLINE":
        rec = "High risk and no reply yet. Keep the card blocked and call the cardholder before any release."
    elif f["decision"] == "HOLD":
        rec = "Grey case. Contact the cardholder and decide on their answer."
    else:
        rec = "Approved with a low score. No action needed."
    msg = (f"Hello {name}, we noticed a payment of {amount} at {f['merchant']}{' (' + f['city'] + ')' if f['city'] else ''} on your card and paused it as a precaution. "
           "Was this you? Reply YES if it was, or NO and we will secure your card straight away.")
    return {"summary": summary, "recommendation": rec, "customer_message": msg}


def case_summary(conn: sqlite3.Connection, tx_id: int, settings: Settings, client: httpx.Client | None = None) -> dict:
    d = transactions_service.detail(conn, tx_id)
    f = _facts(d)
    name = ((d.get("customer") or {}).get("name") or "there").split()[0]
    if settings.gemini_api_key:
        prompt = ("You are a fraud analyst assistant at an Indian card issuer. Using ONLY these facts, return JSON with keys summary (two sentences), "
                  "recommendation (one sentence for the analyst), customer_message (a polite SMS under 300 characters asking the cardholder to confirm the payment). "
                  f"Cardholder first name: {name}.\nFacts: {json.dumps(f, default=str)}")
        try:
            out = _gemini(settings, prompt, client=client)
            if all(isinstance(out.get(k), str) and out[k].strip() for k in ("summary", "recommendation", "customer_message")):
                return {"provider": "gemini", "model": settings.gemini_model, **{k: out[k].strip() for k in ("summary", "recommendation", "customer_message")}}
        except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            log.warning("gemini unavailable (%s); using the offline copilot", type(exc).__name__)
            return {"provider": "offline", "model": "rule-based", "fallback_reason": type(exc).__name__, **_offline_case(f, name)}
    return {"provider": "offline", "model": "rule-based", **_offline_case(f, name)}


# ---------- natural-language search ----------
MONEY = re.compile(r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|lakh|lakhs|l|crore|cr)?", re.I)
MULT = {"k": 1e3, "lakh": 1e5, "lakhs": 1e5, "l": 1e5, "crore": 1e7, "cr": 1e7}


def _money(m: re.Match) -> float:
    return float(m.group(1).replace(",", "")) * MULT.get((m.group(2) or "").lower(), 1)


def offline_filter(question: str, cities: list[str]) -> dict:
    q, spec = question.lower(), {}
    for w, d in (("declin", "DECLINE"), ("held", "HOLD"), ("hold", "HOLD"), ("approved", "APPROVE")):
        if w in q:
            spec["decision"] = d
            break
    if re.search(r"confirmed|fraud(?!\s*desk)", q) and "decision" not in spec and "open" not in q:
        spec["review"] = "CONFIRMED_FRAUD"
    if "false positive" in q:
        spec["review"] = "FALSE_POSITIVE"
    if re.search(r"\b(open|pending|unreviewed|queue)\b", q):
        spec["review"] = "OPEN"
    for c in CHANNELS:
        if re.search(rf"\b{c.lower()}\b", q) or (c == "ONLINE" and "e-commerce" in q):
            spec["channel"] = c
    for city in cities:
        if re.search(rf"\b{re.escape(city.lower())}\b", q):
            spec["city"] = city
            break
    m = re.search(r"score\s*(?:above|over|>)\s*(0?\.\d+)", q)
    if m:
        spec["min_score"] = float(m.group(1))
        q = q[:m.start()] + q[m.end():]
    for pat, key in ((r"(?:above|over|more than|greater than|>|at least|min(?:imum)?)\s*", "min_amount"), (r"(?:below|under|less than|<|at most|max(?:imum)?)\s*", "max_amount")):
        m = re.search(pat + MONEY.pattern, q, re.I)
        if m:
            spec[key] = _money(re.search(MONEY, q[m.start():]) or m)
    m = re.search(r"(?:card|ending)\s*(?:ending\s*)?(\d{4})\b", q)
    if m:
        spec["card_last4"] = m.group(1)
    m = re.search(r"\b(?:at|from)\s+([a-z][a-z .&']{2,24}?)(?:\s+(?:above|over|below|under|in|on|with)\b|$|[?.,])", q)
    if m and m.group(1).strip() not in {c.lower() for c in cities} and m.group(1).strip() not in {"the", "least", "most"}:
        spec["merchant"] = m.group(1).strip()
    return spec


def clean_filter(raw: dict) -> dict:
    """Validate a filter coming from a model or the parser. Unknown keys are dropped, values are type-checked."""
    spec: dict = {}
    if not isinstance(raw, dict):
        raise Invalid("The filter must be an object.")
    for k, v in raw.items():
        if k not in FILTER_KEYS or v in (None, ""):
            continue
        if k == "decision" and str(v).upper() in DECISIONS:
            spec[k] = str(v).upper()
        elif k == "review" and str(v).upper() in REVIEWS:
            spec[k] = str(v).upper()
        elif k == "channel" and str(v).upper() in CHANNELS:
            spec[k] = str(v).upper()
        elif k in ("city", "merchant") and isinstance(v, str) and len(v) <= 40:
            spec[k] = v.strip()
        elif k in ("min_amount", "max_amount", "min_score"):
            try:
                spec[k] = float(v)
            except (TypeError, ValueError):
                continue
        elif k == "card_last4" and re.fullmatch(r"\d{4}", str(v)):
            spec[k] = str(v)
        elif k == "limit":
            try:
                spec[k] = max(1, min(int(v), 50))
            except (TypeError, ValueError):
                continue
    return spec


def _like(s: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", s) + "%"


def run_filter(conn: sqlite3.Connection, spec: dict) -> dict:
    where, args = ["source != 'BENCH'"], []
    simple = {"decision": "decision", "review": "review", "channel": "channel"}
    for k, col in simple.items():
        if k in spec:
            where.append(f"{col}=?")
            args.append(spec[k])
    if "city" in spec:
        where.append("location=? COLLATE NOCASE")
        args.append(spec["city"])
    if "merchant" in spec:
        where.append("merchant LIKE ? ESCAPE '\\'")
        args.append(_like(spec["merchant"]))
    if "min_amount" in spec:
        where.append("amount>=?"); args.append(spec["min_amount"])
    if "max_amount" in spec:
        where.append("amount<=?"); args.append(spec["max_amount"])
    if "min_score" in spec:
        where.append("score>=?"); args.append(spec["min_score"])
    if "card_last4" in spec:
        where.append("token LIKE ? ESCAPE '\\'"); args.append("%" + spec["card_last4"])
    sql = " AND ".join(where)
    agg = conn.execute(f"SELECT count(*) n, coalesce(sum(amount),0) total FROM v_transactions WHERE {sql}", args).fetchone()
    rows = conn.execute(f"SELECT id,token,amount,currency,merchant,location,channel,score,decision,review,created FROM v_transactions WHERE {sql} ORDER BY id DESC LIMIT ?",
                        [*args, spec.get("limit", 15)]).fetchall()
    return {"count": agg["n"], "total_amount": round(agg["total"], 2), "rows": [dict(r) for r in rows]}


def _describe(spec: dict) -> str:
    bits = []
    if "decision" in spec: bits.append(spec["decision"].lower())
    if "review" in spec: bits.append("review " + spec["review"].lower().replace("_", " "))
    if "channel" in spec: bits.append(spec["channel"].lower())
    if "city" in spec: bits.append("in " + spec["city"])
    if "merchant" in spec: bits.append("at " + spec["merchant"])
    if "min_amount" in spec: bits.append(f"above ₹{spec['min_amount']:,.0f}")
    if "max_amount" in spec: bits.append(f"below ₹{spec['max_amount']:,.0f}")
    if "min_score" in spec: bits.append(f"score ≥ {spec['min_score']:.2f}")
    if "card_last4" in spec: bits.append("card …" + spec["card_last4"])
    return ", ".join(bits) or "all transactions"


def chat(conn: sqlite3.Connection, question: str, settings: Settings, cities: list[str], client: httpx.Client | None = None) -> dict:
    question = question.strip()
    if not 2 <= len(question) <= 300:
        raise Invalid("Ask a question between 2 and 300 characters.", [{"field": "question", "message": "length"}])
    provider, spec, reason = "offline", None, None
    if settings.gemini_api_key:
        prompt = ("Convert the analyst's question into a JSON filter over card transactions. Allowed keys only: decision (APPROVE|HOLD|DECLINE), "
                  "review (OPEN|CONFIRMED_FRAUD|FALSE_POSITIVE), channel (ONLINE|POS|ATM), city, merchant, min_amount, max_amount (rupees as numbers), "
                  f"min_score (0-1), card_last4, limit. Omit what is not asked. Question: {question}")
        try:
            spec, provider = clean_filter(_gemini(settings, prompt, client=client)), "gemini"
        except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            reason = type(exc).__name__
    if spec is None:
        spec = clean_filter(offline_filter(question, cities))
    res = run_filter(conn, spec)
    answer = (f"Found {res['count']} transaction{'s' if res['count'] != 1 else ''} ({_describe(spec)}) worth ₹{res['total_amount']:,.0f} in total."
              if res["count"] else f"No transactions match ({_describe(spec)}).")
    return {"provider": provider, "fallback_reason": reason, "question": question, "filter": spec, "answer": answer, **res}
