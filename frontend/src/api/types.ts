export type Decision = "APPROVE" | "HOLD" | "DECLINE";
export type Review = "OPEN" | "CONFIRMED_FRAUD" | "FALSE_POSITIVE" | "NOT_REQUIRED";
export type Channel = "POS" | "ONLINE" | "ATM" | "WALLET";
export type Source = "SEED" | "LIVE" | "BENCH";
export type Role = "analyst" | "admin";

export interface Factor { code: string; label: string; points: number }
export interface Transaction {
  id: number; token: string; amount: number; currency: string; merchant: string; country: string; location: string | null; channel: Channel; created: string;
  alert_id: number | null; assigned_to: string | null; cardholder_response: "LEGIT" | "NOT_ME" | null;
  score: number; decision: Decision; reasons: string[]; factors: Factor[]; review: Review; scorer: string; source: Source;
  reviewed_at: string | null; reviewed_by: string | null; review_note: string | null; has_alert: boolean;
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number; pages: number }
export interface Card {
  token: string; blocked: boolean; blocked_at: string | null; block_reason: string | null; blocked_by: string | null;
  card_network?: string | null; issuer?: string | null; card_type?: string; credit_limit?: number | null; customer_name?: string | null; customer_city?: string | null;
  tx_count?: number; alert_count?: number; last_seen?: string | null;
}
export interface AuditEvent { id: number; at: string; actor: string; action: string; detail: Record<string, unknown>; target: string | null; hash?: string }
export interface TransactionDetail extends Transaction {
  card: Card; token_history: Transaction[]; audit: AuditEvent[];
  customer: { name: string; city: string | null; state: string | null; home_country: string } | null;
  merchant_info: { name: string; category_code: string | null; category_label: string | null; city: string | null; risk_level: string } | null;
}
export interface AuditPage { items: AuditEvent[]; total: number; limit: number; offset: number; actions: string[] }
export interface RiskConfig { approve_max: number; hold_max: number; high_amount: number; blocked_countries: string; velocity_limit: number }
export interface Rules {
  scorer: string; trained_model: boolean; ml_note: string; config: RiskConfig; decision_rule: string;
  factors: { code: string; label: string; points: number; applies_when: string }[];
}
export interface TrendPoint { date: string; total: number; alerts: number; holds: number; declines: number }
export interface Report {
  transactions: number; alert_count: number; alert_backlog: number; confirmed_fraud: number; false_positives: number; reviewed: number;
  alert_rate: number; confirmed_share: number | null; average_score: number; fraud_rate: number; false_positive_share: number | null;
  flagged_value_inr: number; unassigned_open: number;
  productivity: { analyst: string; resolved: number; confirmed: number; false_positives: number; avg_minutes_to_resolve: number | null }[];
  by_decision: Record<string, number>; by_review: Record<string, number>; by_channel: Record<string, number>; by_source: Record<string, number>;
  trend: TrendPoint[]; recent_suspicious: Pick<Transaction, "id" | "token" | "amount" | "currency" | "merchant" | "score" | "decision" | "review" | "created" | "source">[];
  range: { from: string | null; to: string | null; source: string | null }; note: string; limitations: string[];
}
export interface ReviewResult { ok: boolean; transaction_id: number; verdict: string; card_blocked: boolean; card_token: string; card_currently_blocked: boolean }
export interface Me { email: string; name: string | null; role: Role; auth_required: boolean }
export interface Health { status: string; schema_version: number; scoring: string; auth_required: boolean; login_otp: boolean; otp_delivery: string; ml_available: boolean }
export interface UserRow { email: string; name: string | null; role: Role; created?: string; disabled: boolean }
export interface Notification { id: number; created: string; channel: "EMAIL" | "SMS"; recipient: string; body: string; txn_id: number | null; expires_at: string | null; replied_at: string | null; reply: string | null }
export interface NotificationPage { items: Notification[]; total: number; limit: number; offset: number; note: string }
export interface ModelMetrics { precision: number; recall: number; f1: number; tp: number; fp: number; fn: number; tn: number; threshold: number }
export interface ModelRow {
  model_id: number; name: string; version: string; algorithm: string; status: "candidate" | "active" | "retired"; pr_auc: number | null;
  precision_score: number | null; recall_score: number | null; f1_score: number | null; trained_at: string;
  metrics: {
    dataset: { name: string; rows_raw: number; duplicates_dropped: number; rows_used: number; frauds: number; currency: string; citation: string };
    split: { method: string; train: { rows: number; frauds: number }; val: { rows: number; frauds: number }; test: { rows: number; frauds: number } };
    metrics: { validation_pr_auc_by_candidate: Record<string, number>; test: { pr_auc: number; roc_auc: number; prevalence: number; at_app_threshold: ModelMetrics; at_validation_f1_threshold: ModelMetrics } };
    limitations: string[]; sklearn: string;
  };
}
export interface ModelsResponse {
  items: ModelRow[]; ml_available: boolean; training_note: string;
  benchmark: { replayed: number; tp: number; fp: number; fn: number; tn: number; precision: number | null; recall: number | null; note: string };
}
export interface AuditVerify { ok: boolean; checked: number; first_broken_id: number | null; head: string }
export interface Meta { cities: { name: string; country: string }[]; currencies: string[]; channels: string[]; fx_note: string }
export interface ConfirmInfo { amount: number; currency: string; merchant: string; location: string | null; created: string; card_last4: string; already_replied: boolean; reply: string | null }
