export type TaskStatus =
  | "RECEIVED" | "PARSING" | "QUEUED" | "SEARCHING" | "COLLECTING"
  | "PERSISTING" | "RETRY_WAIT" | "WAITING_FOR_LOGIN" | "WAITING_FOR_ACCOUNT"
  | "WAITING_FOR_VERIFICATION" | "WAITING_FOR_RESOURCE" | "PAUSED_BUDGET"
  | "CANCELLING" | "CANCELLED" | "COMPLETED" | "PARTIAL_COMPLETED"
  | "FAILED_VALIDATION" | "FAILED";

export type TaskKind = "collection" | "manual_update" | "scheduled_update";

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
  group?: string | null;
  control?: "text" | "single-select" | "cascader" | "range" | "range-group" | "profile-group" | null;
  options: CapabilityOption[];
  dimensions: CapabilityDimension[];
  region_tree: RegionNode[];
  range_constraints?: RangeConstraint | null;
  incompatible_with: string[];
  unit?: string | null;
  currencies: string[];
  cooperation_forms: string[];
  keyword_mode?: string | null;
}

export interface RangeValue { min: number | null; max: number | null; unit: "ten_thousand_count" }
export interface CountRangeValue { min: number | null; max: number | null; unit: "count" }
export interface RangeConstraint { min: number; max: number; unit: string }
export interface CapabilityOption {
  value: string;
  label: string;
  request_value?: string | number | null;
  range?: { min: number | string | null; max: number | string | null } | null;
}
export interface CapabilityDimension {
  key: string;
  label: string;
  control: "single-select" | "multi-select" | "range";
  options: CapabilityOption[];
  range_constraints?: RangeConstraint | null;
}
export interface RegionNode { value: string; label: string; children: RegionNode[] }

export interface Capabilities {
  platform: "douyin_xingtu" | "kuaishou_juxing";
  capability_version: string;
  fields: CapabilityField[];
  combinations: string[][];
  combination_policy?: { schema_version: string; mode: "composable"; fields: string[]; incompatible: string[][] } | null;
  target_count_default: number;
  target_count_min: number;
  target_count_max: number;
  fixed_sort_key: string;
  fixed_sort_label: string;
}

export interface PlatformOption {
  platform: "douyin_xingtu" | "kuaishou_juxing";
  label: string;
  enabled: boolean;
  capability_status: "verified" | "observed" | "documented" | "unavailable";
  contract_version: string | null;
  disabled_reason?: string | null;
}

export interface RequirementFormV1 {
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

export interface AudienceProfile {
  age: string[];
  gender: string | null;
  device_brand: string[];
  city_level: string[];
  crowd: string[];
}

export interface RequirementFormV2 {
  schema_version: "requirement_form.v2";
  platform: "douyin_xingtu";
  keyword: string | null;
  creator_types: [];
  followers: RangeValue | null;
  creator_gender: "male" | "female" | null;
  creator_regions: Array<{ province_code: string; city?: string | null }>;
  creator_education: "undergraduate" | "master" | "doctor" | "overseas" | null;
  yellow_v_certification: "beauty" | "sports" | "media_host" | "technology" | "athlete" | null;
  connection_users: Record<string, RangeValue | null> | null;
  viewer_profile: AudienceProfile | null;
  fan_profile: AudienceProfile | null;
  quote: null;
  sort_key: string | null;
  target_count: number;
}

export interface JuxingRange {
  min: number | null;
  max: number | null;
  unit: "yuan";
}

export interface RequirementFormV3 {
  schema_version: "requirement_form.v3";
  platform: "kuaishou_juxing";
  keyword: string | null;
  content_types: string[];
  creator_types: [];
  followers: CountRangeValue | null;
  creator_gender: null;
  creator_regions: Array<{ province_code: string; city?: string | null }>;
  creator_education: null;
  yellow_v_certification: null;
  connection_users: null;
  viewer_profile: null;
  fan_profile: null;
  quote: null;
  juxing_video_quotes: {
    seconds_1_20: JuxingRange | null;
    seconds_21_60: JuxingRange | null;
    seconds_60_plus: JuxingRange | null;
  } | null;
  sort_key: string | null;
  target_count: number;
}

export type RequirementForm = RequirementFormV1 | RequirementFormV2 | RequirementFormV3;

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
  /** Optional only for compatibility with pre-migration fixtures; API responses always include it. */
  platform?: "douyin_xingtu" | "kuaishou_juxing";
  task_kind: TaskKind;
  status: TaskStatus;
  stage: string;
  version: number;
  created_at: string;
  /** Last write to the task record (any state or version change). Not a completion moment. */
  updated_at: string;
  /** Moment the task first entered a terminal state; null while it is still progressing. */
  completed_at: string | null;
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

export interface ManualProbeCreator {
  platform_creator_id: string;
  display_name: string | null;
  state: string;
}

export interface VerificationEvent {
  event_id: string;
  unit_id: string;
  root_task_id: string;
  state: "OPEN" | "ACKNOWLEDGED" | "RESOLVED" | "EXPIRED";
  reason: string;
  detected_at: string;
  last_detected_at: string;
  deadline_at: string;
  reappearance_count: number;
  remaining_seconds: number;
}

export interface ExecutionUnit {
  unit_id: string;
  platform: "douyin_xingtu";
  platforms?: Array<"douyin_xingtu" | "kuaishou_juxing">;
  account_label: string;
  line_label: string;
  state: string;
  mode: string | null;
  allowed_task_kinds: TaskKind[];
  current_root_task_id: string | null;
  worker_status: "ONLINE" | "OFFLINE" | "DUPLICATE" | "UNKNOWN";
  worker_instances: number;
  worker_last_heartbeat_at: string | null;
  browser_status: "ONLINE" | "MAINTENANCE" | "STOPPED" | "SUSPECTED_OFFLINE" | "QUARANTINED";
  verification_state: string | null;
  takeover_state: string | null;
  verification_deadline_at: string | null;
  last_heartbeat_at: string | null;
  actionable_reason: string | null;
}

export interface BrowserTakeover {
  takeover_id: string;
  unit_id: string;
  root_task_id: string;
  state: "REQUESTED" | "ACTIVE" | "VERIFYING" | "RESUMED" | "FAILED" | "EXPIRED" | "RELEASED";
  expires_at: string;
  failure_reason: string | null;
  viewer_url: string | null;
  access_mode: "LOCAL_WINDOW" | "REMOTE_VIEWER";
  operator_message: string | null;
  manual_probe_creators: ManualProbeCreator[];
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

export interface UpdateTargetView {
  creator_id: string | null;
  platform_creator_id: string;
  display_name: string | null;
  first_position: number;
  state: "pending" | "collecting" | "done" | "invalid" | "failed";
  failure_reason: string | null;
}

export interface TaskDetail extends TaskSummary {
  requirement: RequirementForm | null;
  capability_version: string | null;
  plan: Record<string, unknown> | null;
  field_errors: Array<{ code: string; path: string; message: string }>;
  origin_root_task_id: string | null;
  challenge: ChallengeSummary | null;
  intake: IntakeProgress | null;
  update_targets: UpdateTargetView[];
  retry_plan?: RetryPlan | null;
}

export interface TaskPage { items: TaskSummary[]; next_cursor: string | null }

/**
 * What one retry click would do. The scope is derived by the server from the task's own counts
 * (`valid < target` = 继续采集, otherwise 补采缺失字段); the UI only renders it.
 */
export interface RetryPlan {
  scope: "continue" | "backfill";
  remaining_to_target: number;
  incomplete_valid_count: number;
  retryable_creator_count: number;
  search_exhausted: boolean;
  last_retry_at: string | null;
  changed_since_last_retry: number | null;
}

export interface CreatorSummary {
  creator_id: string;
  /** Optional for compatibility with pre-KJX fixtures; API responses always include it. */
  platform?: "douyin_xingtu" | "kuaishou_juxing";
  platform_creator_id: string;
  first_position: number;
  view_kind: "draft" | "published";
  snapshot_id: string | null;
  observed_at: string | null;
  payload: Record<string, unknown>;
}

export interface CreatorPage { items: CreatorSummary[]; next_cursor: string | null }

export interface LibraryMetric {
  value: string | number | null;
  raw_value: string | null;
  unit: string | null;
  is_approximate: boolean;
  status: string;
  observed_at: string | null;
}

export interface CreatorLibrarySummary {
  creator_id: string;
  platform: "douyin_xingtu" | "kuaishou_juxing";
  platform_creator_id: string;
  display_name: string | null;
  avatar_uri: string | null;
  creator_type_label: string | null;
  province: string | null;
  city: string | null;
  industry_labels: string[];
  /** The platform's own content-type labels; not the same dimension as `creator_type_label`. */
  content_theme_labels: string[];
  followers: LibraryMetric;
  monthly_deep_users: LibraryMetric;
  monthly_connected_users: LibraryMetric;
  monthly_follower_growth_rate: LibraryMetric;
  interaction_rate: LibraryMetric;
  completion_rate: LibraryMetric;
  play_median: LibraryMetric;
  average_duration: LibraryMetric;
  average_likes: LibraryMetric;
  average_comments: LibraryMetric;
  average_shares: LibraryMetric;
  expected_cpm_21_60: LibraryMetric;
  expected_cpm_60_plus: LibraryMetric;
  expected_cpe_21_60: LibraryMetric;
  expected_cpe_60_plus: LibraryMetric;
  profile_complete: boolean;
  pipeline_complete: boolean;
  data_updated_at: string | null;
}

export interface CreatorLibraryPage { items: CreatorLibrarySummary[]; next_cursor: string | null }

export interface CreatorLibraryDetail extends CreatorLibrarySummary {
  latest_snapshot_id: string | null;
  mcn_name: string | null;
  introduction: string | null;
  /** `basic.gender` as the platform's own code; the display layer owns the label mapping. */
  gender: string | null;
  collected_field_count: number;
  failed_field_count: number;
  field_sources: Record<string, unknown>;
  module_statuses: Record<string, string | null>;
  profile_payload: Record<string, unknown>;
}

export interface CreatorUpdateStatus {
  creator_id: string;
  in_flight_root_task_id: string | null;
  task_status: TaskStatus | null;
  task_stage: string | null;
  last_write_at: string | null;
  last_success_at: string | null;
  last_success_snapshot_id: string | null;
  next_due_at: string | null;
  tier: string | null;
  interval_days: number | null;
  consecutive_failures: number;
  last_failure_reason: string | null;
}

export interface CreatorUpdateResponse {
  root_task_id: string;
  status: TaskStatus;
  reused: boolean;
}

export interface CreatorLibraryHistoryPoint {
  snapshot_id: string;
  captured_at: string;
  profile_complete: boolean;
  pipeline_complete: boolean;
  module_statuses: Record<string, string | null>;
  metrics: Record<string, string | number | null>;
}

export interface CreatorLibraryHistory {
  items: CreatorLibraryHistoryPoint[];
  /** Snapshots with a library index row, against every stored snapshot for this creator. */
  indexed_snapshots: number;
  total_snapshots: number;
}

export interface CreatorLibraryQuote {
  snapshot_id: string;
  position: number;
  cooperation_form: string | null;
  settlement_description: string | null;
  price_raw: string | number | null;
  origin_price_raw: string | number | null;
  observed_at: string;
  offer_raw: Record<string, unknown>;
}

/**
 * 一条「创作能力 → 最新视频表现」的作品观测（独立于快照 JSONB 的视频观测表）。
 *
 * 计数保持平台原样：后端以 Decimal 序列化，因此既可能是 JSON 数字也可能是数字字符串；`null`
 * 表示平台未返回该字段（`field_statuses` 里说明原因），与真实的 `0` 不混淆。
 */
export interface CreatorVideoObservation {
  module_key: "recent_video_performance" | "recent_xingtu_video_performance";
  position: number;
  /** 本项目内容行 id；平台自身作品 id 见 `platform_item_id`。 */
  content_id: string | null;
  /** 抖音作品 id（平台自有标识）。 */
  platform_item_id: string | null;
  platform_video_id: string | null;
  platform_author_id: string | null;
  title: string | null;
  /** 平台从不返回该字段，恒为 null。 */
  subtitle: string | null;
  published_at: string | null;
  published_raw: string | null;
  play_count: number | string | null;
  like_count: number | string | null;
  comment_count: number | string | null;
  /** 平台从不返回该字段，恒为 null。 */
  favorite_count: number | string | null;
  share_count: number | string | null;
  /** 平台对象存储的不透明 key，不是可渲染地址。 */
  cover_source_uri: string | null;
  /** 已入库封面对象 id；仅在 `cover_status === "STORED"` 时非空。 */
  cover_object_id: string | null;
  cover_status: "STORED" | "UNRESOLVED" | "NOT_PROVIDED";
  work_url: string | null;
  field_statuses: Record<string, string>;
  observed_at: string;
}

export interface CreatorVideoPage {
  creator_id: string;
  snapshot_id: string | null;
  view_kind: "published" | "unavailable";
  items: CreatorVideoObservation[];
}

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

/**
 * Presentation metadata for one registered profile field. Served by
 * `/api/platforms/douyin_xingtu/profile-field-catalog` from the verified platform registry; it
 * carries no collected business value.
 */
export interface ProfileFieldCatalogEntry {
  key: string;
  name: string;
  contract_name: string;
  name_source: "contract" | "evidence_correction";
  kind: string;
  unit: string | null;
  period_label: string | null;
  empty_values: string[];
  missing_source_status: string | null;
}

export interface ProfileModuleCatalog {
  key: string;
  fields: ProfileFieldCatalogEntry[];
}

export interface ProfileFieldCatalog {
  platform: "douyin_xingtu" | "kuaishou_juxing";
  contract_version: string;
  modules: ProfileModuleCatalog[];
}
