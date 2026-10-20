from __future__ import annotations
import json, os, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("FRAUD_DB", Path(__file__).resolve().parent.parent / "fraud_demo.sqlite"))
app = FastAPI(title="Fraud Detection Demo", version="1.0.0", description="Synthetic-data academic demonstrator; risk scores are heuristic, not validated model output.")

@contextmanager
def conn():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def init():
    with conn() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY, token TEXT NOT NULL, amount REAL NOT NULL, merchant TEXT NOT NULL, country TEXT NOT NULL, channel TEXT NOT NULL, created TEXT NOT NULL, score REAL NOT NULL, decision TEXT NOT NULL, reasons TEXT NOT NULL, review TEXT NOT NULL DEFAULT 'OPEN');
        CREATE TABLE IF NOT EXISTS cards(token TEXT PRIMARY KEY, blocked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);''')
        defaults={'approve_max':'0.25','hold_max':'0.65','high_amount':'1500','blocked_countries':'XX'}
        for k,v in defaults.items(): c.execute('INSERT OR IGNORE INTO config VALUES(?,?)',(k,v))
        if c.execute('SELECT count(*) FROM transactions').fetchone()[0]==0:
            c.execute('INSERT OR IGNORE INTO cards(token,blocked) VALUES(?,0)',('SYNTH-1042',))
            # Clearly synthetic examples, not model evaluation data.
            examples=[('SYNTH-1042',42.5,'Corner Cafe','US','POS',.04,'APPROVE','[]'),('SYNTH-2088',2200,'Demo Electronics','US','ONLINE',.57,'HOLD','["high amount"]'),('SYNTH-3091',980,'Demo Travel','XX','ONLINE',.96,'DECLINE','["blocked country"]')]
            for token,amt,m,country,channel,score,decision,reasons in examples:
                c.execute('INSERT INTO transactions(token,amount,merchant,country,channel,created,score,decision,reasons) VALUES(?,?,?,?,?,?,?,?,?)',(token,amt,m,country,channel,now(),score,decision,reasons))
                if decision!='APPROVE': c.execute('INSERT OR IGNORE INTO cards(token,blocked) VALUES(?,0)',(token,))

def now(): return datetime.now(timezone.utc).isoformat()
def audit(actor,action,detail):
    with conn() as c: c.execute('INSERT INTO audit(at,actor,action,detail) VALUES(?,?,?,?)',(now(),actor,action,json.dumps(detail)))
init()
class Tx(BaseModel):
    card_token: str = Field(min_length=4,max_length=40,pattern=r'^[A-Za-z0-9_-]+$')
    amount: float = Field(gt=0,le=1_000_000)
    merchant: str = Field(min_length=1,max_length=100)
    country: str = Field(min_length=2,max_length=2,pattern=r'^[A-Za-z]{2}$')
    channel: Literal['POS','ONLINE','ATM','WALLET']
class Verdict(BaseModel): verdict: Literal['CONFIRMED_FRAUD','FALSE_POSITIVE']
class Config(BaseModel): approve_max: float=Field(ge=0,le=1); hold_max: float=Field(gt=0,le=1); high_amount: float=Field(gt=0); blocked_countries: str=Field(max_length=100)
def get_config():
    with conn() as c: return {r['key']:r['value'] for r in c.execute('SELECT * FROM config')}
def score(tx):
    cfg=get_config(); reasons=[]; risk=.04
    if tx.amount>float(cfg['high_amount']): risk+=.35; reasons.append('high amount')
    if tx.country.upper() in [x.strip().upper() for x in cfg['blocked_countries'].split(',') if x.strip()]: risk+=.75; reasons.append('blocked country')
    if tx.channel=='ONLINE': risk+=.10
    with conn() as c:
        n=c.execute('SELECT count(*) FROM transactions WHERE token=? AND created>?', (tx.card_token, (datetime.now(timezone.utc).replace(microsecond=0).isoformat()[:10]+'T00:00:00+00:00'))).fetchone()[0]
    if n>=4: risk+=.25; reasons.append('high daily velocity')
    risk=min(1,round(risk,3)); decision='APPROVE' if risk<=float(cfg['approve_max']) else ('HOLD' if risk<=float(cfg['hold_max']) else 'DECLINE')
    return risk,decision,reasons
@app.get('/api/health')
def health(): return {'status':'ok','database':'sqlite','scoring':'transparent demo heuristic; no trained model'}
@app.post('/api/transactions')
def ingest(tx:Tx):
    with conn() as c:
        blocked=c.execute('SELECT blocked FROM cards WHERE token=?',(tx.card_token,)).fetchone()
        if blocked and blocked['blocked']: raise HTTPException(409,'Card token is blocked')
    risk,decision,reasons=score(tx); created=now()
    with conn() as c:
        cur=c.execute('INSERT INTO transactions(token,amount,merchant,country,channel,created,score,decision,reasons) VALUES(?,?,?,?,?,?,?,?,?)',(tx.card_token,tx.amount,tx.merchant,tx.country.upper(),tx.channel,created,risk,decision,json.dumps(reasons)))
        c.execute('INSERT OR IGNORE INTO cards(token,blocked) VALUES(?,0)',(tx.card_token,))
    result={'id':cur.lastrowid,'score':risk,'decision':decision,'reasons':reasons,'alert_created':decision!='APPROVE'}
    audit('gateway','transaction_scored',result); return result
@app.get('/api/transactions')
def transactions():
    with conn() as c: return [dict(r) for r in c.execute('SELECT * FROM transactions ORDER BY id DESC LIMIT 200')]
@app.get('/api/alerts')
def alerts(status:str='OPEN'):
    with conn() as c: return [dict(r) for r in c.execute('SELECT * FROM transactions WHERE decision != "APPROVE" AND review=? ORDER BY id DESC',(status.upper(),))]
@app.post('/api/alerts/{transaction_id}/review')
def review(transaction_id:int,v:Verdict):
    with conn() as c:
        row=c.execute('SELECT * FROM transactions WHERE id=?',(transaction_id,)).fetchone()
        if not row: raise HTTPException(404,'Transaction not found')
        c.execute('UPDATE transactions SET review=? WHERE id=?',(v.verdict,transaction_id))
        if v.verdict=='CONFIRMED_FRAUD': c.execute('UPDATE cards SET blocked=1 WHERE token=?',(row['token'],))
    audit('analyst','review_recorded',{'transaction_id':transaction_id,'verdict':v.verdict}); return {'ok':True,'card_blocked':v.verdict=='CONFIRMED_FRAUD'}
@app.post('/api/cards/{token}/block')
def block(token:str):
    with conn() as c: c.execute('INSERT INTO cards(token,blocked) VALUES(?,1) ON CONFLICT(token) DO UPDATE SET blocked=1',(token,))
    audit('admin','card_blocked',{'token':token}); return {'token':token,'blocked':True}
@app.post('/api/cards/{token}/unblock')
def unblock(token:str):
    with conn() as c: c.execute('INSERT INTO cards(token,blocked) VALUES(?,0) ON CONFLICT(token) DO UPDATE SET blocked=0',(token,))
    audit('admin','card_unblocked',{'token':token}); return {'token':token,'blocked':False}
@app.get('/api/cards')
def cards():
    with conn() as c: return [dict(r) for r in c.execute('SELECT token,blocked FROM cards ORDER BY token')]
@app.get('/api/config')
def config(): return get_config()
@app.put('/api/config')
def configure(data:Config):
    if data.approve_max>=data.hold_max: raise HTTPException(422,'approve_max must be below hold_max')
    with conn() as c:
        for k,v in data.model_dump().items(): c.execute('INSERT INTO config VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(v)))
    audit('admin','config_updated',data.model_dump()); return get_config()
@app.get('/api/reports')
def reports():
    with conn() as c:
        total=c.execute('SELECT count(*) FROM transactions').fetchone()[0]; risk=c.execute('SELECT count(*) FROM transactions WHERE decision != "APPROVE"').fetchone()[0]
        open_count=c.execute('SELECT count(*) FROM transactions WHERE decision != "APPROVE" AND review="OPEN"').fetchone()[0]
        fraud=c.execute('SELECT count(*) FROM transactions WHERE review="CONFIRMED_FRAUD"').fetchone()[0]; fp=c.execute('SELECT count(*) FROM transactions WHERE review="FALSE_POSITIVE"').fetchone()[0]
    return {'transactions':total,'alert_count':risk,'alert_backlog':open_count,'confirmed_fraud':fraud,'false_positives':fp,'alert_rate':round(risk/total,3) if total else 0,'note':'Descriptive counts over local synthetic/demo transactions only.'}
@app.get('/api/audit')
def audit_logs():
    with conn() as c: return [dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]
@app.get('/',response_class=HTMLResponse)
def dashboard(): return HTML
HTML='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fraud Desk</title><style>*{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:#18243a;font:15px system-ui}header{background:#112039;color:white;padding:24px 5vw}main{max-width:1180px;margin:28px auto;padding:0 20px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card,section{background:white;border:1px solid #e3e8f0;border-radius:12px;padding:18px;margin-bottom:18px}.metric{font-size:26px;font-weight:700}.muted{color:#66748a}.row{display:flex;gap:20px;flex-wrap:wrap}.row section{flex:1;min-width:340px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:9px;border-bottom:1px solid #edf0f5}button{background:#265cde;color:white;border:0;border-radius:7px;padding:8px 12px;cursor:pointer}input,select{padding:9px;border:1px solid #ccd4e0;border-radius:6px;margin:4px}form{display:flex;flex-wrap:wrap;align-items:center}.pill{font-weight:700}.pill.DECLINE{color:#c13232}.pill.HOLD{color:#a86a00}.pill.APPROVE{color:#17754a}@media(max-width:700px){.grid{grid-template-columns:repeat(2,1fr)}} </style></head><body><header><h1>Fraud Desk</h1><div>Local synthetic-data demonstrator · transparent heuristic scoring · not a payment authorization service</div></header><main><div id="metrics" class="grid"></div><div class="row"><section><h2>Analyst queue</h2><div id="alerts"></div></section><section><h2>Score a synthetic transaction</h2><form id="tx"><input name="card_token" placeholder="SYNTH-4481" value="SYNTH-4481" required><input name="amount" type="number" min="0.01" step=".01" placeholder="Amount" value="250" required><input name="merchant" placeholder="Merchant" value="Demo Market" required><input name="country" maxlength="2" value="US" required><select name="channel"><option>ONLINE</option><option>POS</option><option>ATM</option><option>WALLET</option></select><button>Score</button></form><p id="result" class="muted">Uses synthetic card tokens only.</p></section></div><div class="row"><section><h2>Recent transactions</h2><div id="transactions"></div></section><section><h2>Admin thresholds</h2><form id="config"><label>Approve ≤ <input name="approve_max" type="number" step=".01" min="0" max="1"></label><label>Hold ≤ <input name="hold_max" type="number" step=".01" min="0" max="1"></label><label>High amount <input name="high_amount" type="number" min="1"></label><label>Blocked countries <input name="blocked_countries"></label><button>Save settings</button></form><p class="muted">Local demo controls; no authentication configured.</p></section></div><section><h2>Audit log</h2><div id="audit"></div></section></main><script>
const api=async(p,o={})=>{let r=await fetch('/api'+p,{headers:{'Content-Type':'application/json'},...o});let d=await r.json();if(!r.ok)throw Error(d.detail||'Request failed');return d};
const table=(rows,cols)=>'<table><thead><tr>'+cols.map(x=>'<th>'+x[1]+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(x=>'<td>'+((r[x[0]]??'')+'').replaceAll('<','&lt;')+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
async function load(){let [rep,a,tx,c,logs]=await Promise.all([api('/reports'),api('/alerts'),api('/transactions'),api('/config'),api('/audit')]);document.querySelector('#metrics').innerHTML=[['transactions',rep.transactions],['alert backlog',rep.alert_backlog],['confirmed fraud',rep.confirmed_fraud],['false positives',rep.false_positives]].map(x=>`<div class="card"><div class="muted">${x[0]}</div><div class="metric">${x[1]}</div></div>`).join('');document.querySelector('#alerts').innerHTML=a.length?'<table><thead><tr><th>ID</th><th>Token</th><th>Amount</th><th>Merchant</th><th>Score</th><th>Decision</th><th>Reasons</th><th>Actions</th></tr></thead><tbody>'+a.map(r=>`<tr><td>${r.id}</td><td>${r.token}</td><td>${r.amount}</td><td>${r.merchant}</td><td>${r.score}</td><td>${r.decision}</td><td>${r.reasons}</td><td><button onclick="reviewAlert(${r.id},'FALSE_POSITIVE')">Clear</button> <button onclick="reviewAlert(${r.id},'CONFIRMED_FRAUD')">Fraud</button></td></tr>`).join('')+'</tbody></table>':'<p class="muted">No open alerts.</p>';document.querySelector('#transactions').innerHTML=table(tx.slice(0,12),[['id','ID'],['token','Token'],['amount','Amount'],['merchant','Merchant'],['score','Risk'],['decision','Decision']]);document.querySelector('#audit').innerHTML=table(logs.slice(0,8),[['at','Time'],['actor','Actor'],['action','Action'],['detail','Detail']]);for(let k of ['approve_max','hold_max','high_amount','blocked_countries'])document.querySelector(`[name=${k}]`).value=c[k]}
window.reviewAlert=async(id,verdict)=>{try{await api(`/alerts/${id}/review`,{method:'POST',body:JSON.stringify({verdict})});load()}catch(e){alert(e.message)}};
document.querySelector('#tx').onsubmit=async e=>{e.preventDefault();let f=Object.fromEntries(new FormData(e.target));f.amount=+f.amount;try{let r=await api('/transactions',{method:'POST',body:JSON.stringify(f)});document.querySelector('#result').textContent=`Decision: ${r.decision} · risk ${r.score} · ${r.reasons.join(', ')||'no flags'}`;load()}catch(err){document.querySelector('#result').textContent=err.message}};
document.querySelector('#config').onsubmit=async e=>{e.preventDefault();let f=Object.fromEntries(new FormData(e.target));for(let k of ['approve_max','hold_max','high_amount'])f[k]=+f[k];try{await api('/config',{method:'PUT',body:JSON.stringify(f)});load()}catch(err){alert(err.message)}};load();setInterval(load,10000);
</script></body></html>'''
