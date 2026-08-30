import { computed, ref } from "vue";
import { useDomainRequest } from "@/shared/composables/useDomainRequest";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { memoryClient } from "@/api/client";
import type {
	MemoryDocListOptions,
	MemoryLifecycleState,
	MemoryMetadata,
	MemoryOverview,
	MemoryReviewStatus,
	MemoryRecallFeedback,
	MemoryOperation,
	MemoryAddPayload,
	MemoryQueryPayload,
} from "@/api/clients/memory-client";

export interface MemoryDoc {
	id: string;
	text: string;
	type?: string;
	memory_role?: string;
	layer?: string;
	importance?: number;
	confidence?: number;
	quality_score?: number;
	updated_at?: string;
	source?: string;
	scope?: string;
	expires_at?: string;
	metadata?: MemoryMetadata;
	source_kind?: string;
	source_id?: string;
	turn_id?: string;
	evidence?: unknown;
	confidence_history?: Array<Record<string, unknown>>;
	schema_version?: number;
	revision?: number;
	state?: MemoryLifecycleState;
	review_status?: MemoryReviewStatus;
	valid_from?: string;
	valid_to?: string;
	occurred_at?: string;
	ingested_at?: string;
	source_ids?: string[];
	supersedes?: string | string[];
	superseded_by?: string;
}

export interface MemoryDuplicateCandidate {
	id: string;
	text: string;
	score?: number;
	text_similarity?: number;
	match_reason?: string;
	layer?: string;
	scope?: string;
	type?: string;
	importance?: number;
	confidence?: number;
	quality_score?: number;
}

export interface MemoryRetrievalTrace {
	query: string;
	scope?: string;
	session_id?: string;
	workspace_id?: string;
	layers: string[];
	recall_count?: number;
	selected_ids: string[];
	candidate_limit?: number;
	candidate_count?: number;
	filtered_count?: number;
	filtered_out_count?: number;
	filter_reasons: Record<string, number>;
	anchor_ids?: string[];
	expanded_ids?: string[];
	expansion_edges?: Array<{ from: string; to: string; relation: string }>;
	evidence_ids?: string[];
	expansion_depth?: number;
	expansion_truncated?: boolean;
	relation_latency_ms?: number;
	relation_attempted?: number;
	relation_accepted?: number;
	evidence_coverage?: number;
	relation_token_estimate?: number;
	context_budget_tokens?: number;
	context_token_estimate?: number;
	budget_truncated?: boolean;
	index_consistency?: string;
	revision_stable?: boolean;
	top_score?: number;
	average_score?: number;
	latency_ms?: number;
	backend_filter_downpushed?: boolean;
	complete?: boolean;
	error_code?: string;
	scan_limit_reached?: boolean;
	ranking_strategy?: string;
	score_weights?: Record<string, number>;
}

export interface MemoryQueryResult {
	query: string;
	results: Array<{
		id: string;
		text: string;
		score?: number;
		score_components?: Record<string, number>;
		why_recalled?: string;
		evidence_type?: string;
		association?: string;
		layer?: string;
		metadata?: Record<string, unknown>;
	}>;
	trace?: MemoryRetrievalTrace;
}

interface BackendDocument {
	id?: unknown;
	text?: unknown;
	metadata?: Record<string, unknown>;
}

interface BackendQueryItem {
	id?: unknown;
	text?: unknown;
	score?: unknown;
	score_components?: unknown;
	why_recalled?: unknown;
	evidence_type?: unknown;
	association?: unknown;
	layer?: unknown;
	metadata?: Record<string, unknown>;
	doc?: BackendDocument;
}

const numberOrUndefined = (value: unknown) => {
	const numeric = Number(value);
	return Number.isFinite(numeric) ? numeric : undefined;
};

const stringOrUndefined = (value: unknown) =>
	typeof value === "string" && value.trim() ? value : undefined;

const normalizeStringList = (value: unknown) =>
	Array.isArray(value)
		? value
				.map((item) => String(item ?? "").trim())
				.filter((item) => item.length > 0)
		: [];

const normalizeStringNumberRecord = (value: unknown) => {
	if (!value || typeof value !== "object" || Array.isArray(value)) return {};
	return Object.fromEntries(
		Object.entries(value as Record<string, unknown>)
			.map(([key, item]) => [key, Number(item)])
			.filter(([, item]) => Number.isFinite(item)),
	) as Record<string, number>;
};

const normalizeDuplicateCandidate = (raw: unknown): MemoryDuplicateCandidate => {
	const candidate = raw as Record<string, unknown>;
	return {
		id: String(candidate.id ?? ""),
		text: String(candidate.text ?? ""),
		score: numberOrUndefined(candidate.score),
		text_similarity: numberOrUndefined(candidate.text_similarity),
		match_reason: stringOrUndefined(candidate.match_reason),
		layer: stringOrUndefined(candidate.layer),
		scope: stringOrUndefined(candidate.scope),
		type: stringOrUndefined(candidate.type),
		importance: numberOrUndefined(candidate.importance),
		confidence: numberOrUndefined(candidate.confidence),
		quality_score: numberOrUndefined(candidate.quality_score),
	};
};

const resolveLifecycleState = (metadata: MemoryMetadata): MemoryLifecycleState => {
	if (metadata.soft_forgotten === true) return "forgotten";
	const reviewStatus = stringOrUndefined(metadata.review_status);
	if (reviewStatus === "rejected" || reviewStatus === "superseded") return reviewStatus;
	if (stringOrUndefined(metadata.superseded_by)) return "superseded";
	const now = Date.now();
	const expiresAt = Date.parse(String(metadata.expires_at ?? ""));
	const validTo = Date.parse(String(metadata.valid_to ?? ""));
	if ((Number.isFinite(expiresAt) && expiresAt <= now) || (Number.isFinite(validTo) && validTo <= now)) return "expired";
	const validFrom = Date.parse(String(metadata.valid_from ?? ""));
	if (Number.isFinite(validFrom) && validFrom > now) return "scheduled";
	return "active";
};

export const normalizeDuplicateCandidates = (value: unknown) =>
	Array.isArray(value) ? value.map(normalizeDuplicateCandidate) : [];

const normalizeDoc = (raw: unknown): MemoryDoc => {
	const doc = raw as BackendDocument;
	const metadata = doc.metadata || {};
	return {
		id: String(doc.id ?? ""),
		text: String(doc.text ?? ""),
		type: typeof metadata.type === "string" ? metadata.type : undefined,
		layer: typeof metadata.layer === "string" ? metadata.layer : undefined,
		importance: numberOrUndefined(metadata.importance),
		memory_role: stringOrUndefined(metadata.memory_role),
		confidence: numberOrUndefined(metadata.confidence),
		quality_score: numberOrUndefined(metadata.quality_score),
		updated_at: stringOrUndefined(metadata.updated_at),
		source: stringOrUndefined(metadata.source),
		scope: stringOrUndefined(metadata.scope),
		expires_at: stringOrUndefined(metadata.expires_at),
		metadata,
		source_kind: stringOrUndefined(metadata.source_kind),
		source_id: stringOrUndefined(metadata.source_id),
		turn_id: stringOrUndefined(metadata.turn_id),
		evidence: metadata.evidence,
		confidence_history: Array.isArray(metadata.confidence_history) ? metadata.confidence_history as Array<Record<string, unknown>> : [],
		schema_version: numberOrUndefined(metadata.schema_version),
		revision: numberOrUndefined(metadata.revision),
		state: (stringOrUndefined(metadata.state) as MemoryLifecycleState | undefined) ?? resolveLifecycleState(metadata),
		review_status: stringOrUndefined(metadata.review_status) as MemoryReviewStatus | undefined,
		valid_from: stringOrUndefined(metadata.valid_from),
		valid_to: stringOrUndefined(metadata.valid_to),
		occurred_at: stringOrUndefined(metadata.occurred_at),
		ingested_at: stringOrUndefined(metadata.ingested_at),
		source_ids: normalizeStringList(metadata.source_ids),
		supersedes:
			Array.isArray(metadata.supersedes)
				? normalizeStringList(metadata.supersedes)
				: stringOrUndefined(metadata.supersedes),
		superseded_by: stringOrUndefined(metadata.superseded_by),
	};
};

const normalizeTrace = (raw: unknown): MemoryRetrievalTrace | undefined => {
	if (!raw || typeof raw !== "object") return undefined;
	const trace = raw as Record<string, unknown>;
	return {
		query: String(trace.query ?? ""),
		scope: stringOrUndefined(trace.scope),
		session_id: stringOrUndefined(trace.session_id),
		workspace_id: stringOrUndefined(trace.workspace_id),
		layers: normalizeStringList(trace.layers),
		recall_count: numberOrUndefined(trace.recall_count),
		selected_ids: normalizeStringList(trace.selected_ids),
		anchor_ids: normalizeStringList(trace.anchor_ids),
		expanded_ids: normalizeStringList(trace.expanded_ids),
		expansion_edges: Array.isArray(trace.expansion_edges)
			? trace.expansion_edges
					.filter((edge): edge is Record<string, unknown> => Boolean(edge) && typeof edge === "object")
					.map((edge) => ({
						from: String(edge.from ?? ""),
						to: String(edge.to ?? ""),
						relation: String(edge.relation ?? ""),
					}))
					.filter((edge) => edge.from && edge.to)
			: [],
		evidence_ids: normalizeStringList(trace.evidence_ids),
		expansion_depth: numberOrUndefined(trace.expansion_depth),
		expansion_truncated: typeof trace.expansion_truncated === "boolean" ? trace.expansion_truncated : undefined,
		relation_latency_ms: numberOrUndefined(trace.relation_latency_ms),
		relation_attempted: numberOrUndefined(trace.relation_attempted),
		relation_accepted: numberOrUndefined(trace.relation_accepted),
		evidence_coverage: numberOrUndefined(trace.evidence_coverage),
		relation_token_estimate: numberOrUndefined(trace.relation_token_estimate),
		context_budget_tokens: numberOrUndefined(trace.context_budget_tokens),
		context_token_estimate: numberOrUndefined(trace.context_token_estimate),
		budget_truncated: typeof trace.budget_truncated === "boolean" ? trace.budget_truncated : undefined,
		index_consistency: stringOrUndefined(trace.index_consistency),
		revision_stable: typeof trace.revision_stable === "boolean" ? trace.revision_stable : undefined,
		candidate_limit: numberOrUndefined(trace.candidate_limit),
		candidate_count: numberOrUndefined(trace.candidate_count),
		filtered_count: numberOrUndefined(trace.filtered_count),
		filtered_out_count: numberOrUndefined(trace.filtered_out_count),
		filter_reasons: normalizeStringNumberRecord(trace.filter_reasons),
		top_score: numberOrUndefined(trace.top_score),
		average_score: numberOrUndefined(trace.average_score),
		latency_ms: numberOrUndefined(trace.latency_ms),
		backend_filter_downpushed:
			typeof trace.backend_filter_downpushed === "boolean"
				? trace.backend_filter_downpushed
				: undefined,
		complete: typeof trace.complete === "boolean" ? trace.complete : undefined,
		error_code: stringOrUndefined(trace.error_code),
		scan_limit_reached:
			typeof trace.scan_limit_reached === "boolean"
				? trace.scan_limit_reached
				: undefined,
		ranking_strategy: stringOrUndefined(trace.ranking_strategy),
		score_weights: normalizeStringNumberRecord(trace.score_weights),
	};
};

const normalizeQueryResult = (raw: unknown): MemoryQueryResult => {
	const payload = raw as { query?: unknown; results?: unknown[]; trace?: unknown };
	const results = Array.isArray(payload.results) ? payload.results : [];
	return {
		query: String(payload.query ?? ""),
		results: results.map((item) => {
			const result = item as BackendQueryItem;
			const doc = result.doc;
			const metadata = result.metadata || doc?.metadata || {};
			return {
				id: String(result.id ?? doc?.id ?? ""),
				text: String(result.text ?? doc?.text ?? ""),
				score: numberOrUndefined(result.score),
				score_components: normalizeStringNumberRecord(result.score_components),
				why_recalled: stringOrUndefined(result.why_recalled),
				evidence_type: stringOrUndefined(result.evidence_type),
				association: stringOrUndefined(result.association),
				layer:
					typeof result.layer === "string"
						? result.layer
						: typeof metadata.layer === "string"
							? metadata.layer
							: undefined,
				metadata,
			};
		}),
		trace: normalizeTrace(payload.trace),
	};
};

export function useMemoryDomain() {
	const workspaceStore = useWorkspaceStore();
	const activeWorkspace = computed(() => workspaceStore.activeWorkspace);
	const docs = ref<MemoryDoc[]>([]);
	const forgottenDocs = ref<MemoryDoc[]>([]);
	const reviewCandidates = ref<MemoryDoc[]>([]);
	const overview = ref<MemoryOverview | null>(null);
	const queryResult = ref<MemoryQueryResult | null>(null);

	const workspaceDefaultScope = () =>
		activeWorkspace.value.memory_scope || "workspace";
	const resolveScope = (payload: { scope?: string; session_id?: string }) =>
		payload.scope ?? (payload.session_id ? "session" : workspaceDefaultScope());
	const resolveScopedWorkspaceId = (payload: {
		scope?: string;
		session_id?: string;
		workspace_id?: string;
	}) => {
		const scope = resolveScope(payload);
		if (scope === "global") return undefined;
		return payload.workspace_id ?? activeWorkspace.value.id;
	};

	const docsRequest = useDomainRequest<{ docs: unknown[] }>();
	const forgottenDocsRequest = useDomainRequest<{ docs: unknown[] }>();
	const overviewRequest = useDomainRequest<MemoryOverview>();
	const candidatesRequest = useDomainRequest<{ status: string; candidates: unknown[]; count: number }>();
	const addRequest = useDomainRequest<{
		status?: string;
		id?: string;
		skipped?: boolean;
		reason?: string;
		duplicate_candidates?: unknown[];
	}>();
	const updateRequest = useDomainRequest<{
		status?: string;
		id?: string;
		layer?: string;
		scope?: string;
		importance?: number;
	}>();
	const queryRequest = useDomainRequest<unknown>();
	const operationsRequest = useDomainRequest<{ status: string; operations: MemoryOperation[]; count: number }>();
	const operations = computed<MemoryOperation[]>(() => operationsRequest.data?.operations ?? []);

	const loadDocs = async (options?: MemoryDocListOptions) => {
		const result = await docsRequest.execute(() => memoryClient.getDocs(options));
		if (result) {
			docs.value = Array.isArray(result.docs)
				? result.docs.map(normalizeDoc)
				: [];
		}
	};

	const loadOverview = async (options?: MemoryDocListOptions) => {
		const result = await overviewRequest.execute(() => memoryClient.getOverview(options));
		if (result) overview.value = result;
		return result;
	};

	const loadCandidates = async (options?: MemoryDocListOptions) => {
		const result = await candidatesRequest.execute(() => memoryClient.getCandidates({ ...options, status: "pending" }));
		if (result) {
			reviewCandidates.value = Array.isArray(result.candidates)
				? result.candidates.map(normalizeDoc)
				: [];
		}
		return result;
	};

	const loadOperations = async (documentId: string, options?: MemoryDocListOptions) => {
		return operationsRequest.execute(() => memoryClient.getOperations({
			...options,
			documentId,
			limit: 50,
		}));
	};

	const reviewCandidate = async (id: string, decision: "approve" | "reject", reason?: string, sessionId?: string) => {
		const result = await memoryClient.reviewCandidate(id, { decision, reason, session_id: sessionId });
		if (result) reviewCandidates.value = reviewCandidates.value.filter((item) => item.id !== id);
		return result;
	};

	const loadForgottenDocs = async (options?: MemoryDocListOptions) => {
		const result = await forgottenDocsRequest.execute(() => memoryClient.getDocs({
			...options,
			includeState: "forgotten",
		}));
		if (result) {
			forgottenDocs.value = Array.isArray(result.docs)
				? result.docs.map(normalizeDoc)
				: [];
		}
		return result;
	};

	const addMemory = async (payload: MemoryAddPayload) => {
		return addRequest.execute(() =>
			memoryClient.addMemory({
				...payload,
				scope: resolveScope(payload),
				workspace_id: resolveScopedWorkspaceId(payload),
			}),
		);
	};

	const updateDoc = async (
		id: string,
		payload: {
			text: string;
		type?: string;
		memory_role?: string;
			layer?: string;
			importance?: number;
			confidence?: number;
			confidence_source?: string;
			edit_reason?: string;
			metadata?: MemoryMetadata;
			session_id?: string;
			workspace_id?: string;
			scope?: string;
		},
	) => {
		return updateRequest.execute(() =>
			memoryClient.updateDoc(id, {
				...payload,
				scope: resolveScope(payload),
				workspace_id: resolveScopedWorkspaceId(payload),
			}),
		);
	};
	const correctDoc = (id: string, payload: { text: string; reason?: string; turn_id?: string; session_id?: string; evidence?: unknown }) =>
		memoryClient.correctDoc(id, payload);
	const softForgetDoc = (id: string, payload?: { reason?: string; turn_id?: string; session_id?: string }) =>
		memoryClient.softForgetDoc(id, payload);
	const restoreDoc = (id: string, payload?: { reason?: string; session_id?: string }) =>
		memoryClient.restoreDoc(id, payload);

	const queryMemory = async (payload: MemoryQueryPayload) => {
		const resolvedScope = resolveScope(payload);
		const resolvedWorkspaceId = resolveScopedWorkspaceId(payload);
		const result = await queryRequest.execute(() => memoryClient.query({
			query: payload.query,
			top_k: payload.top_k ?? 5,
			memory_types: payload.memory_types,
			session_id: payload.session_id,
			workspace_id: resolvedWorkspaceId,
			scope: resolvedScope,
			layers: payload.layers,
			expand_relations: payload.expand_relations,
			relation_limit: payload.relation_limit,
			relation_depth: payload.relation_depth,
		}));
		if (result) {
			queryResult.value = normalizeQueryResult(result);
		}
	};

	const recordRecallFeedback = async (id: string, feedback: MemoryRecallFeedback, sessionId?: string) => {
		const result = await memoryClient.recordRecallFeedback(id, feedback, sessionId);
		const item = queryResult.value?.results.find((candidate) => candidate.id === id);
		if (item) {
			item.metadata = {
				...(item.metadata || {}),
				recall_feedback: { summary: result.counts },
			};
		}
		return result;
	};

	return {
		docs,
		operations,
		forgottenDocs,
		reviewCandidates,
		overview,
		queryResult,
		docsRequest,
		forgottenDocsRequest,
		overviewRequest,
		candidatesRequest,
		addRequest,
		updateRequest,
		queryRequest,
		operationsRequest,
		loadDocs,
		loadForgottenDocs,
		loadCandidates,
		loadOperations,
		loadOverview,
		addMemory,
		updateDoc,
		correctDoc,
		softForgetDoc,
		restoreDoc,
		reviewCandidate,
		queryMemory,
		recordRecallFeedback,
	};
}
