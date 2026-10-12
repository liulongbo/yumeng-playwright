export type TaskStatus =
  | "RECEIVED" | "PARSING" | "QUEUED" | "SEARCHING" | "COLLECTING"
  | "PERSISTING" | "RETRY_WAIT" | "WAITING_FOR_LOGIN" | "WAITING_FOR_ACCOUNT"
  | "WAITING_FOR_VERIFICATION" | "WAITING_FOR_RESOURCE" | "PAUSED_BUDGET"
  | "CANCELLING" | "CANCELLED" | "COMPLETED" | "PARTIAL_COMPLETED"
  | "FAILED_VALIDATION" | "FAILED";

export interface UserView {
  user_id: string;
  username: string;
  display_name: string;
  csrf_token: string;
}

export interface ProductError {
  code: string;
  message: string;
  field_errors?: Array<{ code: string; path: string; message: string }>;
  request_id?: string;
  current_version?: number | null;
  allowed_actions?: string[];
}

export interface CapabilityField {
  field: string;
  label: string;
  operators: string[];
  options: string[];
  unit?: string | null;
  currencies: string[];
  cooperation_forms: string[];
  keyword_mode?: string | null;
}

export interface Capabilities {
  platform: "douyin_xingtu";
  capability_version: string;
  fields: CapabilityField[];
  combinations: string[][];
  target_count_default: number;
  target_count_min: number;
  target_count_max: number;
  fixed_sort_key: string;
  fixed_sort_label: string;
}

export interface RequirementForm {
  schema_version: "requirement_form.v1";
  platform: "douyin_xingtu";
  keyword: string | null;
  creator_types: string[];
  followers: { min: number | null; max: number | null; unit: "count" } | null;
  creator_gender: string | null;
  creator_regions: string[];
  quote: {
    cooperation_form: string; currency: string; min: number | null; max: number | null; unit: string;
  } | null;
  sort_key: string | null;
  target_count: number;
}

export interface TaskCounts {
  target_count: number;
  discovered_count: number;
  valid_count: number;
  profile_complete_count: number;
  featured_complete_count: number;
  failed_count: number;
}

export interface TaskSummary {
  root_task_id: string;
  status: TaskStatus;
  stage: string;
  version: number;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  created_by_name: string | null;
  source: "product" | "internal_acceptance";
  keyword: string | null;
  counts: TaskCounts;
  allowed_actions: string[];
  failure_reason: string | null;
}

export interface ChallengeSummary {
  state: string;
  challenge_type: string | null;
  first_detected_at: string | null;
  last_detected_at: string | null;
  wait_started_at: string | null;
  last_recovered_at: string | null;
  detected_count: number;
  recovery_count: number;
  current_creator_id: string | null;
  completed_creator_count: number;
  remaining_creator_count: number;
  waiting_seconds: number;
  account_matches: boolean | null;
  requires_user_action: boolean;
  monitoring: boolean;
  terminal_reason: string | null;
  terminal_message: string | null;
  delivered_result: string;
}

export interface IntakeProgress {
  sent: boolean;
  pending_seconds: number | null;
  consumer_alive: boolean | null;
  consumer_checked_at: string | null;
  observed_fresh_pollers: number | null;
  dispatch_error: string | null;
  blocked_reason: string | null;
  blocked_seconds: number | null;
}

export interface TaskDetail extends TaskSummary {
  requirement: RequirementForm | null;
  capability_version: string | null;
  plan: Record<string, unknown> | null;
  field_errors: Array<{ code: string; path: string; message: string }>;
  origin_root_task_id: string | null;
  challenge: ChallengeSummary | null;
  intake: IntakeProgress | null;
}

export interface TaskPage { items: TaskSummary[]; next_cursor: string | null }

export interface CreatorSummary {
  creator_id: string;
  platform_creator_id: string;
  first_position: number;
  view_kind: "draft" | "published";
  snapshot_id: string | null;
  observed_at: string | null;
  payload: Record<string, unknown>;
}

export interface CreatorPage { items: CreatorSummary[]; next_cursor: string | null }

export interface ContentPage {
  view_kind: "draft" | "published";
  snapshot_id?: string;
  collection_type: "excellent_reach" | "excellent_seeding";
  status: string;
  observed_at?: string;
  coverage_gaps?: string[];
  cards: Array<Record<string, unknown>>;
  next_cursor?: string | null;
}
