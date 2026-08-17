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
  max_latency_to_ix_ms?: number | null;
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
}

export interface SearchResponse {
  query: string;
  backend: string;
  results: RetrievedChunk[];
}
