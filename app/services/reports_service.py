from __future__ import annotations

import csv
import io
import sqlite3

NOTE = "Descriptive counts over local demo data (seeded rows are synthetic). Not a model evaluation."
LIMITS = [
    "Seeded rows are synthetic and labelled SEED; they say nothing about real fraud rates.",
    "Review outcomes are analyst verdicts on flagged transactions only; approved transactions are never reviewed, so recall and the true false-negative rate cannot be computed.",
    "'Confirmed share' = confirmed fraud / reviewed alerts. It is not precision of a validated model.",
]


def _range(date_from: str | None, date_to: str | None) -> tuple[str, list]:
    where, args = [], []
    if date_from:
        where.append("substr(created,1,10)>=?"); args.append(date_from)
    if date_to:
        where.append("substr(created,1,10)<=?"); args.append(date_to)
    return (("WHERE " + " AND ".join(where)) if where else ""), args


def _group(conn, col: str, clause: str, args: list) -> dict:
    return {r[0]: r[1] for r in conn.execute(f"SELECT {col}, count(*) FROM transactions {clause} GROUP BY {col} ORDER BY {col}", args)}


def build_report(conn: sqlite3.Connection, date_from: str | None = None, date_to: str | None = None, source: str | None = None) -> dict:
    clause, args = _range(date_from, date_to)
    if source:
        clause += (" AND " if clause else "WHERE ") + "source=?"
        args = [*args, source]
    total = conn.execute(f"SELECT count(*), COALESCE(AVG(score),0) FROM transactions {clause}", args).fetchone()
    by_decision, by_review = _group(conn, "decision", clause, args), _group(conn, "review", clause, args)
    n = total[0]
    alerts = sum(v for k, v in by_decision.items() if k != "APPROVE")
    fraud, fp, backlog = by_review.get("CONFIRMED_FRAUD", 0), by_review.get("FALSE_POSITIVE", 0), by_review.get("OPEN", 0)
    reviewed = fraud + fp
    trend = [dict(r) for r in conn.execute(
        f"""SELECT substr(created,1,10) date, count(*) total, SUM(decision!='APPROVE') alerts, SUM(decision='HOLD') holds,
            SUM(decision='DECLINE') declines FROM transactions {clause} GROUP BY date ORDER BY date""", args)]
    return {
        "transactions": n, "alert_count": alerts, "alert_backlog": backlog, "confirmed_fraud": fraud, "false_positives": fp,
        "reviewed": reviewed, "alert_rate": round(alerts / n, 3) if n else 0,
        "confirmed_share": round(fraud / reviewed, 3) if reviewed else None, "average_score": round(total[1], 3),
        "by_decision": by_decision, "by_review": by_review, "by_channel": _group(conn, "channel", clause, args),
        "by_source": _group(conn, "source", clause, args), "trend": trend,
        "recent_suspicious": [dict(r) for r in conn.execute(
            f"SELECT id,token,amount,merchant,score,decision,review,created,source FROM transactions {clause}{' AND' if clause else 'WHERE'} decision!='APPROVE' ORDER BY id DESC LIMIT 6", args)],
        "range": {"from": date_from, "to": date_to, "source": source}, "note": NOTE, "limitations": LIMITS,
    }


def _safe_cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in "=+-@\t\r" else s  # neutralise spreadsheet formula injection


def export_csv(conn: sqlite3.Connection, date_from: str | None, date_to: str | None) -> str:
    clause, args = _range(date_from, date_to)
    cols = ["id", "created", "token", "amount", "merchant", "country", "channel", "score", "decision", "review", "source", "scorer"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in conn.execute(f"SELECT {','.join(cols)} FROM transactions {clause} ORDER BY id", args):
        w.writerow([_safe_cell(r[c]) for c in cols])
    return buf.getvalue()
