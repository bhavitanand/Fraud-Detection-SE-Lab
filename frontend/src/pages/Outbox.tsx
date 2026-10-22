import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { NotificationPage } from "../api/types";
import { Badge, Empty, ErrorState, Loading, PageHead, Pager } from "../components/ui";
import { fmtTime, useAsync } from "../lib";

const SIZE = 20;
export default function Outbox() {
  const [sp, setSp] = useSearchParams();
  const page = Number(sp.get("page") ?? 1) || 1;
  const { data, error, loading, reload } = useAsync(() => api.get<NotificationPage>("/api/notifications", { limit: SIZE, offset: (page - 1) * SIZE }), [page]);
  return (
    <>
      <PageHead title="Cardholder messages" sub="Alerts queued for cardholders when a transaction is held or declined."><button className="btn" onClick={reload}>Refresh</button></PageHead>
      <div className="banner">Simulated outbox: nothing is sent by SMS or e-mail. Each message carries a one-time “Was this you?” link; open it to see the cardholder’s page. Phone numbers are invented.</div>
      {loading && !data ? <Loading /> : error && !data ? <ErrorState message={error.message} onRetry={reload} /> : data && (
        data.items.length === 0 ? <Empty>No messages yet.</Empty> : (
          <>
            <div className="table-wrap"><table><thead><tr><th>Time</th><th>Channel</th><th>To</th><th>Message</th><th>Transaction</th><th>Cardholder reply</th></tr></thead>
              <tbody>{data.items.map((n) => {
                const link = n.body.match(/\/confirm\/\S+$/)?.[0];
                return (
                  <tr key={n.id}><td>{fmtTime(n.created)}</td><td>{n.channel}</td><td className="mono">{n.recipient}</td>
                    <td className="wrap">{link ? n.body.replace(link, "") : n.body}{link && <Link to={link}>Open reply link</Link>}</td>
                    <td>{n.txn_id ? <Link to={`/transactions/${n.txn_id}`}>#{n.txn_id}</Link> : "—"}</td>
                    <td>{n.reply ? <Badge tone={n.reply === "NOT_ME" ? "red" : "green"}>{n.reply === "NOT_ME" ? "Not me" : "Genuine"}</Badge> : <span className="muted">Awaiting</span>}</td></tr>);
              })}</tbody></table></div>
            <Pager page={page} pages={Math.max(1, Math.ceil(data.total / SIZE))} total={data.total} onPage={(n) => { const q = new URLSearchParams(sp); q.set("page", String(n)); setSp(q, { replace: true }); }} />
          </>)
      )}
    </>
  );
}
