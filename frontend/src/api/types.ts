export type Decision = "APPROVE" | "HOLD" | "DECLINE";
export type Review = "OPEN" | "CONFIRMED_FRAUD" | "FALSE_POSITIVE" | "NOT_REQUIRED";
export type Channel = "POS" | "ONLINE" | "ATM" | "WALLET";
export type Source = "SEED" | "LIVE";
export type Role = "analyst" | "admin";

export interface Factor { code: string; label: string; points: number }
export interface Transaction {
  id: number; token: string; amount: number; merchant: string; country: string; channel: Channel; created: string;
  score: number; decision: Decision; reasons: string[]; factors: Factor[]; review: Review; scorer: string; source: Source;
  reviewed_at: string | null; reviewed_by: string | null; review_note: string | null; has_alert: boolean;
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number; pages: number }
export interface Card {
  token: string; blocked: boolean; blocked_at: string | null; block_reason: string | null; blocked_by: string | null;
  tx_count?: number; alert_count?: number; last_seen?: string | null;
}
export interface AuditEvent { id: number; at: string; actor: string; action: string; detail: Record<string, unknown>; target: string | null }
export interface TransactionDetail extends Transaction { card: Card; token_history: Transaction[]; audit: AuditEvent[] }
export interface AuditPage { items: AuditEvent[]; total: number; limit: number; offset: number; actions: string[] }
export interface RiskConfig { approve_max: number; hold_max: number; high_amount: number; blocked_countries: string; velocity_limit: number }
export interface Rules {
  scorer: string; trained_model: boolean; config: RiskConfig; decision_rule: string;
  factors: { code: string; label: string; points: number; applies_when: string }[];
}
export interface TrendPoint { date: string; total: number; alerts: number; holds: number; declines: number }
export interface Report {
  transactions: number; alert_count: number; alert_backlog: number; confirmed_fraud: number; false_positives: number; reviewed: number;
  alert_rate: number; confirmed_share: number | null; average_score: number;
  by_decision: Record<string, number>; by_review: Record<string, number>; by_channel: Record<string, number>; by_source: Record<string, number>;
  trend: TrendPoint[]; recent_suspicious: Pick<Transaction, "id" | "token" | "amount" | "merchant" | "score" | "decision" | "review" | "created" | "source">[];
  range: { from: string | null; to: string | null; source: string | null }; note: string; limitations: string[];
}
export interface ReviewResult { ok: boolean; transaction_id: number; verdict: string; card_blocked: boolean; card_token: string; card_currently_blocked: boolean }
export interface Me { username: string; role: Role; auth_required: boolean }
export interface Health { status: string; schema_version: number; scoring: string; auth_required: boolean }
