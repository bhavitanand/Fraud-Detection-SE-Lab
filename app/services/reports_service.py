from __future__ import annotations

import csv
import io
import sqlite3

NOTE = "Descriptive counts over local demo data (seeded rows are synthetic). Not a model evaluation; see the Models page for held-out test metrics."
LIMITS = [
    "Seeded rows are synthetic (SEED); benchmark replay rows (BENCH) come from a public 2013 European dataset in EUR. Neither says anything about real Indian fraud rates.",
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


def _productivity(conn: sqlite3.Connection, clause: str, args: list) -> list[dict]:
    where = clause.replace("created", "t.created") if clause else ""
    rows = conn.execute(f"""SELECT a.resolved_by analyst, COUNT(*) resolved, SUM(a.status='CONFIRMED_FRAUD') confirmed, SUM(a.status='FALSE_POSITIVE') false_positives,
        ROUND(AVG((julianday(a.resolved_at)-julianday(a.created_at))*24*60)) avg_minutes_to_resolve
        FROM fraud_alerts a JOIN transactions t ON t.id=a.txn_id {where}{' AND' if where else 'WHERE'} a.status!='OPEN' AND a.resolved_by IS NOT NULL
        GROUP BY a.resolved_by ORDER BY resolved DESC""", args).fetchall()
    return [dict(r) for r in rows]


def build_report(conn: sqlite3.Connection, date_from: str | None = None, date_to: str | None = None, source: str | None = None) -> dict:
    clause, args = _range(date_from, date_to)
    if source:
        clause += (" AND " if clause else "WHERE ") + "source=?"
        args = [*args, source]
    total = conn.execute(f"SELECT count(*), COALESCE(AVG(score),0) FROM transactions {clause}", args).fetchone()
    by_decision, by_review = _group(conn, "decision", clause, args), {r[0]: r[1] for r in conn.execute(f"SELECT review, count(*) FROM v_transactions {clause} GROUP BY review", args)}
    flagged_value = conn.execute(f"SELECT COALESCE(SUM(amount),0) FROM transactions {clause}{' AND' if clause else 'WHERE'} currency='INR' AND decision!='APPROVE'", args).fetchone()[0]
    unassigned = conn.execute(f"SELECT count(*) FROM v_transactions {clause}{' AND' if clause else 'WHERE'} review='OPEN' AND assigned_to IS NULL", args).fetchone()[0]
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
        "confirmed_share": round(fraud / reviewed, 3) if reviewed else None, "fraud_rate": round(fraud / n, 4) if n else 0,
        "false_positive_share": round(fp / reviewed, 3) if reviewed else None, "flagged_value_inr": round(flagged_value), "unassigned_open": unassigned,
        "productivity": _productivity(conn, clause, args), "average_score": round(total[1], 3),
        "by_decision": by_decision, "by_review": by_review, "by_channel": _group(conn, "channel", clause, args),
        "by_source": _group(conn, "source", clause, args), "trend": trend,
        "recent_suspicious": [dict(r) for r in conn.execute(
            f"SELECT id,token,amount,currency,merchant,score,decision,review,created,source FROM v_transactions {clause}{' AND' if clause else 'WHERE'} decision!='APPROVE' ORDER BY id DESC LIMIT 6", args)],
        "range": {"from": date_from, "to": date_to, "source": source}, "note": NOTE, "limitations": LIMITS,
    }


def _safe_cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in "=+-@\t\r" else s  # neutralise spreadsheet formula injection


def export_csv(conn: sqlite3.Connection, date_from: str | None, date_to: str | None) -> str:
    clause, args = _range(date_from, date_to)
    cols = ["id", "created", "token", "amount", "currency", "merchant", "country", "location", "channel", "score", "decision", "review", "source", "scorer"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in conn.execute(f"SELECT {','.join(cols)} FROM v_transactions {clause} ORDER BY id", args):
        w.writerow([_safe_cell(r[c]) for c in cols])
    return buf.getvalue()


def export_labels(conn: sqlite3.Connection) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["transaction_id", "created", "amount", "currency", "source", "label"])
    for r in conn.execute("SELECT id,created,amount,currency,source,review FROM v_transactions WHERE review IN ('CONFIRMED_FRAUD','FALSE_POSITIVE') ORDER BY id"):
        w.writerow([r["id"], r["created"], r["amount"], r["currency"], r["source"], 1 if r["review"] == "CONFIRMED_FRAUD" else 0])
    return buf.getvalue()
