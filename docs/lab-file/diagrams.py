"""Regenerates the figures used by build_lab_file.py.  python docs/lab-file/diagrams.py   (needs graphviz `dot`, matplotlib)"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)
FONT = "DejaVu Sans"

# ---------------- PERT / CPM schedule (planned effort in weeks: optimistic, most likely, pessimistic) ----------------
ACTIVITIES = [  # id, name, O, M, P, predecessors
    ("A1", "Problem statement (Exp 1)", 0.5, 1, 1.5, []), ("A2", "SRS (Exp 2)", 1, 1.5, 3, ["A1"]), ("A3", "DFD + structure chart (Exp 3)", 1, 1.5, 2, ["A2"]),
    ("A4", "ER + use case (Exp 4-5)", 1, 1.5, 2.5, ["A2"]), ("A5", "Class, object, state, activity (Exp 6-7)", 1, 2, 3, ["A3", "A4"]),
    ("A6", "Sequence, component, deployment (Exp 8-10)", 1, 2, 3, ["A5"]), ("B1", "Backend: API, database, scoring", 2, 3, 5, ["A2"]),
    ("B2", "Frontend (React)", 2, 3, 4, ["B1"]), ("B3", "ML pipeline (train, evaluate, register)", 1, 2, 3, ["B1"]), ("B4", "Sign-in, OTP, cardholder messages", 1, 1.5, 2.5, ["B1"]),
    ("B5", "Integration and testing (Exp 11)", 1, 2, 3, ["B2", "B3", "B4"]), ("C1", "Function-point estimate (Exp 12)", 0.5, 1, 1.5, ["B5"]),
    ("C2", "Gantt / PERT charts (Exp 13)", 0.5, 1, 1.5, ["A2"]), ("D1", "Compile and review lab file", 1, 1.5, 2, ["A6", "C1", "C2"]),
    ("D2", "Demo rehearsal and submission", 0.5, 1, 1.5, ["B5", "D1"]),
]


def cpm():
    acts = {a[0]: dict(id=a[0], name=a[1], o=a[2], m=a[3], p=a[4], pred=a[5]) for a in ACTIVITIES}
    for a in acts.values():
        a["te"] = round((a["o"] + 4 * a["m"] + a["p"]) / 6, 2)
        a["sd"] = round((a["p"] - a["o"]) / 6, 2)
    order, seen = [], set()

    def visit(i):
        if i in seen:
            return
        for p in acts[i]["pred"]:
            visit(p)
        seen.add(i); order.append(i)
    for i in acts:
        visit(i)
    for i in order:
        a = acts[i]
        a["es"] = max([acts[p]["ef"] for p in a["pred"]], default=0.0)
        a["ef"] = round(a["es"] + a["te"], 2)
    end = max(a["ef"] for a in acts.values())
    for i in reversed(order):
        a = acts[i]
        succ = [b for b in acts.values() if i in b["pred"]]
        a["lf"] = min([b["ls"] for b in succ], default=end)
        a["ls"] = round(a["lf"] - a["te"], 2)
        a["slack"] = round(a["ls"] - a["es"], 2)
        a["critical"] = abs(a["slack"]) < 1e-6
    crit = [i for i in order if acts[i]["critical"]]
    sd = round(sum(acts[i]["sd"] ** 2 for i in crit) ** 0.5, 2)
    return acts, order, crit, end, sd


def dot(name: str, src: str) -> None:
    (FIG / f"{name}.dot").write_text(src)
    subprocess.run(["dot", "-Tpng", "-Gdpi=170", str(FIG / f"{name}.dot"), "-o", str(FIG / f"{name}.png")], check=True)
    (FIG / f"{name}.dot").unlink()


HEAD = f'graph [fontname="{FONT}", fontsize=10, pad=0.2]; node [fontname="{FONT}", fontsize=10, style="filled", color="#333333"]; edge [fontname="{FONT}", fontsize=8, color="#444444"];'


def component():
    dot("fig_9_2_component_asbuilt", f"""digraph G {{ rankdir=TB; {HEAD} node [shape=component, fillcolor="#DCE9F5"];
  subgraph cluster_b {{ label="Browser"; style=dashed; spa [label="React + TypeScript SPA\\n(Vite build)"]; confirm [label="Cardholder reply page\\n(/confirm, no sign-in)"]; }}
  subgraph cluster_a {{ label="FastAPI application (one process)"; style=dashed;
    api [label="API routes + RBAC\\n(app/api)"]; sch [label="Request validation\\n(app/schemas)"];
    svc [label="Services: ingest, review, assign,\\ncards, config, reports, users"]; notif [label="Notification service\\n(simulated outbox)"]; auth [label="Auth service\\n(password, e-mail OTP, tokens)"];
    models [label="Model registry service\\n(deploy, retire, replay)"]; rules [label="HeuristicScorer\\n(rule engine)"]; hybrid [label="HybridScorer\\n(Decision engine)", fillcolor="#FFE9C7"];
    mlsvc [label="ModelService\\n(verified artifact loader)"]; repo [label="Repositories\\n(all SQL)", fillcolor="#E6F3EA"]; }}
  db [label="SQLite database\\n(WAL, versioned migrations)", shape=cylinder, fillcolor="#E6F3EA"]; art [label="ml/artifacts\\nmodel + benchmark sample", shape=folder, fillcolor="#E6F3EA"];
  smtp [label="SMTP server\\n(optional, external)", fillcolor="#FFF3D6"]; train [label="ml/train.py\\n(offline training CLI)", fillcolor="#FCE4E4"]; csv [label="creditcard.csv\\n(ULB benchmark, not shipped)", shape=note, fillcolor="#FFFFFF"];
  spa -> api [label="JSON over HTTP"]; confirm -> api [label="one-time link"]; api -> sch; api -> svc; api -> auth; api -> models; svc -> hybrid; svc -> notif; svc -> repo; notif -> repo; auth -> repo; models -> repo;
  hybrid -> rules; hybrid -> mlsvc; mlsvc -> art [label="SHA-256 checked"]; repo -> db; auth -> smtp [style=dashed, label="OTP e-mail"]; train -> csv [dir=back]; train -> art [label="writes"]; train -> db [label="registers", style=dashed];
}}""")


def deployment():
    dot("fig_10_2_deployment_asbuilt", f"""digraph G {{ rankdir=TB; {HEAD} node [shape=box3d, fillcolor="#DCE9F5"];
  br [label="<<device>>\\nBrowser\\n(analyst, administrator, cardholder)", fillcolor="#E6F3EA"];
  subgraph cluster_l {{ label="<<node>> Laptop or lab PC (Windows or Linux, 16 GB RAM)"; style=dashed;
    app [label="<<process>>\\nUvicorn + FastAPI\\n127.0.0.1:8000\\nserves API and built React files"]; db [label="<<artifact>>\\nfraud_demo.sqlite", shape=cylinder, fillcolor="#E6F3EA"];
    art [label="<<artifact>>\\nml/artifacts\\n(model .joblib, sample .csv)", shape=folder, fillcolor="#E6F3EA"]; tr [label="<<process>>\\npython -m ml.train\\n(offline, run by hand)", fillcolor="#FCE4E4"]; ds [label="<<file>>\\ndata/creditcard.csv", shape=note, fillcolor="#FFFFFF"]; }}
  smtp [label="<<node>>\\nSMTP provider\\n(optional, external)", fillcolor="#FFF3D6"];
  br -> app [label="HTTP (HTTPS needs a reverse proxy)"]; app -> db [label="file access"]; app -> art [label="loads model"]; tr -> ds [label="reads"]; tr -> art [label="writes"]; tr -> db [label="registers model"]; app -> smtp [label="STARTTLS (OTP)", style=dashed];
}}""")


def pert(acts, crit):
    lines = [f'digraph G {{ rankdir=TB; nodesep=0.25; ranksep=0.45; {HEAD} node [shape=box, fillcolor="#DCE9F5", margin="0.08,0.04"];']
    for a in acts.values():
        fill = "#F6C9C9" if a["critical"] else "#DCE9F5"
        lines.append(f'{a["id"]} [fillcolor="{fill}", label="{a["id"]}  {a["name"]}\\nTE {a["te"]}w  ES {a["es"]}  EF {a["ef"]}\\nLS {a["ls"]}  LF {a["lf"]}  slack {a["slack"]}"];')
    lines.append('S [shape=circle, label="Start", fillcolor="#E6F3EA"]; E [shape=circle, label="End", fillcolor="#E6F3EA"];')
    for a in acts.values():
        for p in a["pred"] or ["S"]:
            color = "#B42318" if (a["critical"] and (p == "S" or acts[p]["critical"])) else "#555555"
            lines.append(f'{p} -> {a["id"]} [color="{color}", penwidth={2.2 if color == "#B42318" else 1}];')
        if not any(a["id"] in b["pred"] for b in acts.values()):
            lines.append(f'{a["id"]} -> E;')
    lines.append("}")
    dot("fig_13_2_pert", "\n".join(lines))


def gantt(acts, order, end):
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=170)
    rows = sorted(order, key=lambda i: (acts[i]["es"], i))
    for k, i in enumerate(rows):
        a = acts[i]
        ax.barh(k, a["te"], left=a["es"], color="#B42318" if a["critical"] else "#7FA3CF", edgecolor="#333333", height=0.6)
        ax.text(a["es"] + a["te"] + 0.08, k, f'{a["te"]}w', va="center", fontsize=7)
    ax.set_yticks(range(len(rows)), [f'{i}  {acts[i]["name"]}' for i in rows], fontsize=7.5)
    ax.invert_yaxis(); ax.set_xlim(0, end + 1.2); ax.set_xlabel("Week from project start", fontsize=9); ax.grid(axis="x", linestyle=":", alpha=0.5)
    ax.set_xticks(range(0, int(end) + 2))
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color="#B42318"), plt.Rectangle((0, 0), 1, 1, color="#7FA3CF")], labels=["Critical path", "Has slack"], loc="lower right", fontsize=8)
    fig.tight_layout(); fig.savefig(FIG / "fig_13_1_gantt.png"); plt.close(fig)


def coverage():
    r = json.loads((HERE / "results.json").read_text())
    files = {k.replace("app/", "").replace("ml/", "ml."): v["percent"] for k, v in r["backend"]["files"].items() if v["statements"] >= 10}
    names = sorted(files, key=lambda k: files[k])
    fig, ax = plt.subplots(figsize=(8, 4.4), dpi=170)
    ax.barh(names, [files[n] for n in names], color=["#B42318" if files[n] < 80 else "#7FA3CF" for n in names], edgecolor="#333333")
    for i, n in enumerate(names):
        ax.text(files[n] + 0.6, i, f"{files[n]}%", va="center", fontsize=7.5)
    ax.set_xlim(0, 108); ax.set_xlabel("Statement coverage (%)", fontsize=9); ax.tick_params(axis="y", labelsize=7.5)
    ax.set_title(f'Backend statement coverage by module (total {r["backend"]["coverage_percent"]}%)', fontsize=10)
    fig.tight_layout(); fig.savefig(FIG / "fig_11_1_coverage.png"); plt.close(fig)


if __name__ == "__main__":
    acts, order, crit, end, sd = cpm()
    component(); deployment(); pert(acts, crit); gantt(acts, order, end)
    if (HERE / "results.json").exists():
        coverage()
    print("critical path:", " -> ".join(crit), "| expected duration", round(end, 2), "weeks | sd", sd)
