# Live demo script (about 6 minutes)

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
| 9 | **ML model** | Held-out PR-AUC 0.782, recall 77%, precision 85% on the public ULB dataset, with caveats. Click **Replay 25 rows**. | 11, 12 |
| 10 | **Reports** | Fraud rate, false-positive share, analyst productivity, CSV export. | 2 |
| 11 | **Audit log** → **Verify integrity** | Hash chain is intact; each event links to the previous one. | 4 (ER) |
| 12 | Sign out, sign in as an analyst | Analysts cannot block cards, change rules or manage users (the back end refuses). | 5 |

## Likely viva questions
- *Is the model trained on Indian data?* No. The only public labelled data is the 2013 European ULB set (EUR, PCA features). Live Indian transactions are scored by rules; the model applies to benchmark replays. The ML page says so.
- *Why is the metric PR-AUC and not accuracy?* Frauds are 0.17% of rows; always answering "genuine" gives 99.8% accuracy.
- *Is it secure?* Argon2 password hashes, signed tokens, role checks on the back end, no PAN or CVV accepted, tamper-evident audit chain. Not PCI DSS, no TLS, SQLite only.
- *Where do the 13 experiments live?* `docs/lab-alignment.md` and the lab file in `docs/lab-file/`.
