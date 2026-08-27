/**
 * Frontend mirror of the backend Pydantic contracts (`apps/api/app/domain.py`,
 * `schemas.py`). Kept hand-written and narrow on purpose: only what the UI reads.
 * The authoritative schema is always /openapi.json.
 */

export type EvidenceStatus =
  | "live"
  | "cached"
  | "synthetic"
  // A configured live service failed and a deterministic local stand-in was
  // used. Distinct from `synthetic`, which is ordinary demo mode.
  | "fallback"
  | "user_confirmed"
  | "missing"
  | "stale";

export type CheckStatus = "CLOSED" | "OPEN" | "TRIGGERED" | "SKIPPED";
export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type DecisionState =
  | "FIRST-PASS CHECKS CLOSED"
  | "NEEDS INFORMATION"
  | "ENGINEER REVIEW";
export type RiskLevel = "low" | "moderate" | "elevated" | "high";
export type SiteDimension =
  | "geo_terrain"
  | "water"
  | "power"
  | "connectivity"
  | "civil_soil"
  | "hazards_climate"
  | "environmental"
  | "regulatory";

export interface Quantity {
  value: number;
  unit: string;
}

export interface Meta {
  app_name: string;
  environment: string;
  demo_mode: boolean;
  services: Record<string, string>;
  mireye_field_count: number;
  dimension_weights: Record<string, number>;
  dimension_labels: Record<string, string>;
  disclaimer: string;
}

export interface RequirementTargets {
  it_load_mw?: number | null;
  min_grid_capacity_mw?: number | null;
  max_distance_to_substation_km?: number | null;
  max_water_stress_index?: number | null;
  max_permit_lead_time_months?: number | null;
  min_bearing_capacity_kpa?: number | null;
  max_seismic_pga_g?: number | null;
}

export interface Project {
  id: string;
  name: string;
  client?: string | null;
  description?: string | null;
  region?: string | null;
  targets: RequirementTargets;
  dimension_weights: Record<string, number>;
  synthetic: boolean;
}

export interface CandidateSite {
  id: string;
  project_id: string;
  name: string;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  area_hectares?: number | null;
  jurisdiction?: string | null;
  geocode_resolution?: string | null;
  shortlisted: boolean;
  synthetic: boolean;
  notes?: string | null;
  polygon_coordinates?: Array<{ latitude: number; longitude: number }> | null;
}

export interface EvidenceSource {
  source_type: string;
  source_id: string;
  source_name: string;
  page?: number | null;
  section?: string | null;
  span?: { start: number; end: number; text?: string | null } | null;
  field_key?: string | null;
  endpoint?: string | null;
  url?: string | null;
  synthetic: boolean;
  notes?: string | null;
}

export interface Evidence {
  id: string;
  project_id?: string | null;
  subject_id?: string | null;
  claim: string;
  field_key?: string | null;
  value: unknown;
  unit?: string | null;
  source: EvidenceSource;
  status: EvidenceStatus;
  verification: string;
  confidence: number;
  retrieved_at: string;
  observed_at?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  location_resolution?: string | null;
  superseded_by?: string | null;
  stale_reason?: string | null;
}

export interface MetricScore {
  field_key: string;
  label: string;
  raw_value: number | string | null;
  unit?: string | null;
  normalized: number | null;
  weight: number;
  status: EvidenceStatus;
  evidence_id?: string | null;
  explanation: string;
}

export interface DimensionScore {
  dimension: SiteDimension;
  score: number | null;
  weight: number;
  coverage: number;
  confidence: number;
  metrics: MetricScore[];
  drivers: string[];
  concerns: string[];
}

export interface RequirementFlag {
  requirement: string;
  target: string;
  actual?: string | null;
  passed: boolean | null;
  severity: Severity;
  explanation: string;
}

export interface SiteScore {
  site_id: string;
  site_name: string;
  overall_score: number | null;
  rank: number | null;
  evidence_coverage: number;
  confidence: number;
  risk_level: RiskLevel;
  dimensions: DimensionScore[];
  requirement_flags: RequirementFlag[];
  missing_fields: string[];
  synthetic_field_count: number;
  summary: string;
}

export interface SiteRanking {
  project_id: string;
  weights: Record<string, number>;
  scores: SiteScore[];
  comparisons: string[];
  computed_at: string;
}

export interface InvestigationStep {
  id: string;
  order: number;
  phase: string;
  title: string;
  rationale: string;
  requested_fields: string[];
  status: "planned" | "running" | "completed" | "blocked" | "skipped";
  result_summary?: string | null;
  evidence_ids: string[];
  gap_ids: string[];
  added_in_replan: boolean;
}

export interface ToolEvent {
  id: string;
  phase: string;
  tool: string;
  summary: string;
  detail: Record<string, unknown>;
  ok: boolean;
  duration_ms?: number | null;
  at: string;
}

export interface EngineeringCheck {
  id: string;
  key: string;
  name: string;
  category: string;
  status: CheckStatus;
  severity: Severity;
  detail: string;
  expected?: string | null;
  observed?: string | null;
  evidence_ids: string[];
  gap_ids: string[];
}

export interface DeltaResult {
  field: string;
  label: string;
  old_value: Quantity | string | null;
  new_value: Quantity | string | null;
  absolute_delta?: Quantity | null;
  percent_delta?: number | null;
  direction: string;
  severity: Severity;
  threshold_note?: string | null;
  status: CheckStatus;
  explanation: string;
  evidence_ids: string[];
}

export interface Impact {
  id: string;
  change_id: string;
  discipline: string;
  title: string;
  detail: string;
  severity: Severity;
  triggered_by: string[];
  stale_assumption_ids: string[];
  activities: string[];
  commissioning: string[];
  requires_human: boolean;
}

export interface ImpactNode {
  id: string;
  label: string;
  kind: "change" | "assumption" | "discipline" | "activity" | "commissioning" | "equipment" | "site";
  status?: string | null;
  detail?: string | null;
}

export interface ImpactGraph {
  change_id: string;
  nodes: ImpactNode[];
  edges: { source: string; target: string; relation: string }[];
  paths: string[][];
  backend: string;
}

export interface Recommendation {
  id: string;
  headline: string;
  rationale: string[];
  decision_state?: DecisionState | null;
  confidence: number;
  caveats: string[];
  generated_by: string;
}

export interface NextAction {
  id: string;
  type: string;
  title: string;
  recipient: string;
  body: string;
  requested_items: string[];
  related_gap_ids: string[];
  due_in_days: number;
}

export interface Investigation {
  id: string;
  project_id: string;
  workflow: string;
  subject_id?: string | null;
  question: string;
  phase: string;
  status: "running" | "completed" | "failed";
  steps: InvestigationStep[];
  events: ToolEvent[];
  evidence_ids: string[];
  gap_ids: string[];
  replan_notes: string[];
  checks: EngineeringCheck[];
  deltas: DeltaResult[];
  impacts: Impact[];
  stale_assumption_ids: string[];
  decision_state?: DecisionState | null;
  recommendation?: Recommendation | null;
  next_actions: NextAction[];
  ranking?: SiteRanking | null;
  orchestrator: string;
  llm_mode: string;
  started_at: string;
  finished_at?: string | null;
}

export interface InformationGap {
  id: string;
  project_id: string;
  subject_id?: string | null;
  field_key: string;
  description: string;
  why_it_matters: string;
  expected_source: string;
  suggested_action: string;
  severity: Severity;
  status: "open" | "requested" | "resolved";
  blocking: boolean;
  feature_request_id?: string | null;
}

export interface Assumption {
  id: string;
  statement: string;
  discipline: string;
  depends_on_fields: string[];
  equipment_tag?: string | null;
  status: "active" | "stale" | "retired";
  stale_reason?: string | null;
}

export interface EquipmentConfiguration {
  manufacturer?: string | null;
  model_number?: string | null;
  equipment_type?: string | null;
  configuration_code?: string | null;
  circuits?: number | null;
  weight?: Quantity | null;
  weight_basis?: string | null;
  support_points: { point_id: string; load: Quantity }[];
  length?: Quantity | null;
  width?: Quantity | null;
  height?: Quantity | null;
  voltage?: Quantity | null;
  phases?: number | null;
  full_load_amps?: Quantity | null;
  mca?: Quantity | null;
  mocp?: Quantity | null;
  power_input?: Quantity | null;
  refrigerant_type?: string | null;
  refrigerant_charge?: Quantity | null;
  cooling_capacity?: Quantity | null;
  rating_conditions?: {
    entering_water_temp?: Quantity | null;
    leaving_water_temp?: Quantity | null;
    ambient_temp?: Quantity | null;
    standard?: string | null;
  } | null;
  evidence_ids: Record<string, string>;
  synthetic: boolean;
}

export interface Equipment {
  id: string;
  tag: string;
  name: string;
  discipline: string;
  site_id?: string | null;
  configuration: EquipmentConfiguration;
  synthetic: boolean;
}

export interface EquipmentChange {
  id: string;
  project_id: string;
  title: string;
  reason?: string | null;
  equipment_tag: string;
  site_id?: string | null;
  existing_equipment_id: string;
  proposed_equipment_id: string;
  submitted_by?: string | null;
  status: string;
  synthetic: boolean;
}

export interface Requirement {
  id: string;
  document_id?: string | null;
  kind: string;
  label: string;
  field_key?: string | null;
  value: number | string | null;
  unit?: string | null;
  condition?: string | null;
  equipment_tag?: string | null;
  model_identifier?: string | null;
  page?: number | null;
  raw_text?: string | null;
  confidence: number;
  /** Transcribed by OCR rather than read from a text layer - confirm the page. */
  from_ocr?: boolean;
  confirmed: boolean;
  confirmed_by?: string | null;
  corrected_from?: string | null;
  evidence_id?: string | null;
}

export interface ProjectDocument {
  id: string;
  filename: string;
  kind: string;
  size_bytes: number;
  page_count: number;
  synthetic: boolean;
  uploaded_at: string;
  extraction_status: "pending" | "extracted" | "failed";
  extraction_error?: string | null;
  /** Pages with no text layer that were transcribed by OCR. */
  ocr_pages?: number[];
  /** Pages that are scans and were not read at all. */
  unread_pages?: number[];
}

export interface ProjectDetail {
  project: Project;
  sites: CandidateSite[];
  documents: ProjectDocument[];
  changes: EquipmentChange[];
  requirement_count: number;
  evidence_count: number;
  open_gap_count: number;
}

export interface ChangeDetail {
  change: EquipmentChange;
  existing: Equipment;
  proposed: Equipment;
  site?: CandidateSite | null;
  requirements: Requirement[];
  assumptions: Assumption[];
  latest_investigation_id?: string | null;
}

export interface WhatIfResponse {
  ranking: SiteRanking;
  changed_from?: SiteRanking | null;
  explanation: string[];
}

export interface RetrievedChunk {
  chunk_id: string;
  document_id: string;
  document_name: string;
  page: number;
  text: string;
  score: number;
  method: "lexical" | "vector";
  /** The quoted page was transcribed by OCR. */
  ocr?: boolean;
}

export interface SearchResponse {
  query: string;
  backend: string;
  results: RetrievedChunk[];
}

export interface AdvisorChatRequest {
  message: string;
  site_id?: string | null;
  site_context?: Record<string, any> | null;
  history?: Array<{ role: string; content: string }> | null;
}

export interface AdvisorChatResponse {
  reply: string;
  engineer_role: string;
  suggested_improvements: string[];
  mode: string;
  disclaimer: string;
}

export interface Citation {
  source_type: "document" | "web" | "mireye" | "project";
  title: string;
  detail: string;
  url?: string | null;
  page?: number | null;
  chunk_id?: string | null;
  coordinates?: string | null;
}

export interface ToolExecutionTrace {
  tool: string;
  title: string;
  input_params: Record<string, any>;
  output_summary: string;
  duration_ms: number;
  ok: boolean;
}

export interface TellMeInsights {
  key_findings: string[];
  risks_identified: string[];
  standards_compliance: string[];
  actionable_mitigations: string[];
}

export interface KnowledgeAgentRequest {
  message: string;
  site_id?: string | null;
  enabled_tools?: string[] | null;
  history?: Array<{ role: string; content: string }> | null;
}

export interface KnowledgeAgentResponse {
  answer: string;
  tell_me: TellMeInsights;
  citations: Citation[];
  tool_traces: ToolExecutionTrace[];
  site_name?: string | null;
  mode: string;
  disclaimer: string;
}

export interface MCPTool {
  name: string;
  description: string;
  inputSchema: Record<string, any>;
}

export interface ClimateStationInfo {
  station_id: string;
  name: string;
  state: string;
  country: string;
  latitude: number;
  longitude: number;
  elevation_m: number;
  cooling_db_0_4_pct_degc: number;
  cooling_wb_0_4_pct_degc: number;
  cooling_db_1_0_pct_degc: number;
  cooling_wb_1_0_pct_degc: number;
  heating_db_99_6_pct_degc: number;
  distance_km: number;
}

export interface ReferenceSpec {
  id?: string;
  equipment_type: string;
  reference_model: string;
  manufacturer: string;
  weight_kg?: number;
  length_mm?: number;
  width_mm?: number;
  height_mm?: number;
  voltage_v?: number;
  phases?: number;
  full_load_amps_a?: number;
  mca_a?: number;
  mocp_a?: number;
  power_input_kw?: number;
  cop?: number;
  wue_l_per_kwh?: number;
  cooling_capacity_kw?: number;
  description: string;
}

export type MarginStatus = "WITHIN_MARGIN" | "CRITICAL_MARGIN" | "EXCEEDED" | "NEEDS_INFORMATION";

export interface DesignMargin {
  id: string;
  margin_type: string;
  name: string;
  discipline: string;
  design_capacity?: Quantity | null;
  proposed_demand?: Quantity | null;
  remaining_margin?: Quantity | null;
  margin_pct?: number | null;
  status: MarginStatus;
  detail: string;
  evidence_ids: string[];
}

export interface StructuredConstraint {
  parameter: string;
  operator: ">=" | "<=" | "==" | "!=" | ">" | "<";
  value: number | string;
  unit?: string | null;
  priority: "mandatory" | "preferred";
}

export interface StructuredRequirementSet {
  id: string;
  project_id: string;
  equipment_type: string;
  constraints: StructuredConstraint[];
  original_prompt?: string | null;
  created_at: string;
}

export interface CandidateProduct {
  id: string;
  model_number: string;
  manufacturer: string;
  equipment_type: string;
  specs: Record<string, any>;
  score: number;
  score_breakdown: Record<string, number>;
  passed_constraints: string[];
  failed_constraints: string[];
  compatibility_status: "COMPATIBLE" | "CONDITIONALLY_COMPATIBLE" | "INCOMPATIBLE";
  explanation: string;
  warnings: string[];
  reference_source: string;
}

export interface ProductRecommendationResult {
  id: string;
  project_id: string;
  equipment_type: string;
  requirement_set: StructuredRequirementSet;
  candidates: CandidateProduct[];
  top_recommendation?: CandidateProduct | null;
  explanation_narrative: string;
  generated_at: string;
}

export interface CascadeChangeItem {
  change_id: string;
  equipment_tag: string;
  title: string;
  equipment_type: string;
  delta_power_kw: number;
  delta_weight_kg: number;
  delta_cooling_kw: number;
  delta_water_m3_yr: number;
}

export interface CascadeImpactSummary {
  project_id: string;
  evaluated_changes: CascadeChangeItem[];
  cumulative_electrical_delta_kw: number;
  cumulative_weight_delta_kg: number;
  cumulative_cooling_delta_kw: number;
  cumulative_water_delta_m3_yr: number;
  transformer_headroom_pct?: number | null;
  generator_headroom_pct?: number | null;
  structural_headroom_pct?: number | null;
  collective_status: "WITHIN_FACILITY_LIMITS" | "FACILITY_LIMITS_EXCEEDED" | "NEEDS_INFORMATION";
  rationale: string[];
}

export interface DecisionLineageRecord {
  id: string;
  project_id: string;
  change_id: string;
  decision_state: DecisionState;
  timestamp: string;
  triggered_reasons: string[];
  source_documents: string[];
  affected_assumptions: string[];
  engine_version: string;
}

export interface CostScheduleImpact {
  change_id: string;
  equipment_tag: string;
  capex_delta_usd?: number | null;
  annual_energy_delta_usd?: number | null;
  annual_water_delta_usd?: number | null;
  total_annual_opex_delta_usd?: number | null;
  schedule_delay_days: number;
  on_critical_path: boolean;
  lead_time_weeks?: number | null;
  status: "ESTIMATED" | "NEEDS_INFORMATION";
  explanation: string;
}

export interface ConstructionPlanItem {
  category: string;
  label: string;
  model_id: string;
  model_number: string;
  manufacturer: string;
  quantity: number;
  duty_per_unit?: number | null;
  duty_unit?: string | null;
  power_input_per_unit_kw?: number | null;
  connected_power_kw: number;
  estimated_cost_low_usd: number;
  estimated_cost_high_usd: number;
  cost_basis: string;
  lead_time_weeks: number;
  description: string;
  source: string;
  synthetic_cost: boolean;
}

export interface ConstructionWorkPackage {
  sequence: number;
  name: string;
  scope: string;
  depends_on: string[];
}

export interface SitePlanningConstraint {
  field_key: string;
  label: string;
  value: number | string;
  unit?: string | null;
  status: string;
  source: string;
}

export interface ConstructionPlanTotals {
  peak_facility_power_kw: number;
  it_power_kw: number;
  facility_overhead_kw: number;
  annual_energy_kwh: number;
  annual_energy_cost_usd: number;
  annual_water_m3?: number | null;
  equipment_cost_low_usd: number;
  equipment_cost_high_usd: number;
  contingency_pct: number;
  plan_cost_low_usd: number;
  plan_cost_high_usd: number;
  budget_usd?: number | null;
  budget_status: "WITHIN_RANGE" | "BELOW_RANGE" | "NOT_PROVIDED";
}

export interface ConstructionPlanResponse {
  project_id: string;
  site: CandidateSite;
  design_basis: Record<string, any>;
  site_constraints: SitePlanningConstraint[];
  equipment_schedule: ConstructionPlanItem[];
  work_packages: ConstructionWorkPackage[];
  totals: ConstructionPlanTotals;
  warnings: string[];
  data_sources: string[];
}

export interface ActionPackageResponse {
  action_type: string;
  title: string;
  recipient: string;
  body_markdown: string;
  requested_items: string[];
  citations: any[];
  due_in_days: number;
}



