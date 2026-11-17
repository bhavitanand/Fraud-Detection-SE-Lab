# Live demo script (about 6 minutes)

## Opening act: Live mode (2 minutes, do this first)
1. Sign in as admin, open **Live mode**, press **Start simulation** (150 cardholders, speed 6).
2. Watch the feed: declines appear, cards auto-block, cardholders reply, cases close. Point at the counters: precision, recall, handled-without-a-human %, ₹ stopped, scoring time in ms.
3. Say plainly: "these figures are measured against a simulator's ground truth, not real banks."
4. Open a declined transaction from the feed: the model's top reasons, then press **Summarise this case** for the AI summary and cardholder message draft.
5. **AI copilot**: click "Show declined orders above ₹50,000 in Mumbai".
6. **ML models**: rules-only vs model table (PR-AUC 0.229 vs 0.934), per-pattern recall, and the weak spot we report honestly.

## Manual walkthrough (about 6 minutes)
Prepare: server running, signed in as admin, browser at http://127.0.0.1:8000. For a clean run, delete `fraud_demo.sqlite` first. Screenshots of every page are in `docs/screenshots/`.

| # | Do | Say / show | Lab experiment |
|---|---|---|---|
| 1 | **Overview** | 129 synthetic ₹ transactions, 14% flagged, decision split, 12 alerts waiting. The banner states what the numbers are *not*. | 1, 2 |
| 2 | **Transactions → New transaction**: card `SYNTH-IN-1001`, ₹1,20,000, merchant "Tanishq", city Mumbai, channel ONLINE | Result is DECLINE/HOLD with a score. | 3 (DFD), 8 (sequence) |
| 3 | Open the result (**Transaction page**) | "Why this score": every factor adds up to the score. High amount, online channel, unusual amount for this card. | 7 (activity) |
| 4 | Submit again from **Dubai** or **Singapore** within minutes of a Mumbai purchase | New country and impossible-travel factors fire. | 6 (classes) |
| 5 | **Alerts and cases** → open an alert → **Take** → **Confirmed fraud** → confirm | The card token is blocked. State chart: Open → Confirmed fraud. | 7 (state chart) |
| 6 | Submit another transaction on the blocked card | Rejected with HTTP 409. | 5 (use case) |
| 7 | **Cardholder messages** → open a "Was this you?" link | Public page, no sign-in; the reply updates the alert. | 5 |
| 8 | **Fraud rules** → lower the ₹ high-amount limit → save | Admin-only; next transaction scores differently. | 2 (SRS) |
| 9 | **ML models** | Live scorer: PR-AUC 0.934 on simulated data. Benchmark: PR-AUC 0.782 on real ULB data. Click **Replay 25 rows**. | 11, 12 |
| 10 | **Reports** | Fraud rate, false-positive share, analyst productivity, CSV export. | 2 |
| 11 | **Audit log** → **Verify integrity** | Hash chain is intact; each event links to the previous one. | 4 (ER) |
| 12 | Sign out, sign in as an analyst | Analysts cannot block cards, change rules or manage users (the back end refuses). | 5 |

## Likely viva questions
- *Is the model trained on real Indian data?* No. Real labelled card data is not public. The live scorer is trained on a simulator of Indian card behaviour with six fraud patterns, so its numbers measure the system on the simulation. The real-data reference is the ULB benchmark model (PR-AUC 0.78). The ML page says so.
- *How automated is it?* Autopilot blocks obvious fraud, messages the cardholder, and closes the case on their reply; only unanswered or grey cases wait for an analyst.
- *Why a model instead of rules?* Same test set: rules alone flag about 1 in 5 genuine payments (precision 4.8%); the model keeps recall at 84% with 0.06% false alarms.
- *Why is the metric PR-AUC and not accuracy?* Frauds are 0.17% of rows; always answering "genuine" gives 99.8% accuracy.
- *Is it secure?* Argon2 password hashes, signed tokens, role checks on the back end, no PAN or CVV accepted, tamper-evident audit chain. Not PCI DSS, no TLS, SQLite only.
- *Where do the 13 experiments live?* `docs/lab-alignment.md` and the lab file in `docs/lab-file/`.
