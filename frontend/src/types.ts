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
  platform: "douyin_xingtu";
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

export type RequirementForm = RequirementFormV1 | RequirementFormV2;

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
  platform: "douyin_xingtu";
  platform_creator_id: string;
  display_name: string | null;
  avatar_uri: string | null;
  creator_type_label: string | null;
  province: string | null;
  city: string | null;
  industry_labels: string[];
  followers: LibraryMetric;
  monthly_deep_users: LibraryMetric;
  monthly_connected_users: LibraryMetric;
  monthly_follower_growth_rate: LibraryMetric;
  interaction_rate: LibraryMetric;
  completion_rate: LibraryMetric;
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
  content_theme_labels: string[];
  collected_field_count: number;
  failed_field_count: number;
  field_sources: Record<string, unknown>;
  module_statuses: Record<string, string | null>;
  profile_payload: Record<string, unknown>;
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
  platform: "douyin_xingtu";
  contract_version: string;
  modules: ProfileModuleCatalog[];
}
