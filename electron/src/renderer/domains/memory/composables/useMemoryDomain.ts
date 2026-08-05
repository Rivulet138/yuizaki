import { computed, ref } from "vue";
import { useDomainRequest } from "@/shared/composables/useDomainRequest";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { memoryClient } from "@/api/client";
import type { MemoryDocListOptions, MemoryMetadata } from "@/api/clients/memory-client";

export interface MemoryDoc {
	id: string;
	text: string;
	type?: string;
	layer?: string;
	importance?: number;
	confidence?: number;
	quality_score?: number;
	updated_at?: string;
	source?: string;
	scope?: string;
	expires_at?: string;
	metadata?: MemoryMetadata;
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
	top_score?: number;
	average_score?: number;
	latency_ms?: number;
	backend_filter_downpushed?: boolean;
}

interface MemoryQueryResult {
	query: string;
	results: Array<{
		id: string;
		text: string;
		score?: number;
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
		confidence: numberOrUndefined(metadata.confidence),
		quality_score: numberOrUndefined(metadata.quality_score),
		updated_at: stringOrUndefined(metadata.updated_at),
		source: stringOrUndefined(metadata.source),
		scope: stringOrUndefined(metadata.scope),
		expires_at: stringOrUndefined(metadata.expires_at),
		metadata,
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
	const rawQueryRequest = useDomainRequest<unknown>();
	const statusRequest = useDomainRequest<{ status: string; count: number }>();

	const loadDocs = async (options?: MemoryDocListOptions) => {
		const result = await docsRequest.execute(() => memoryClient.getDocs(options));
		if (result) {
			docs.value = Array.isArray(result.docs)
				? result.docs.map(normalizeDoc)
				: [];
		}
	};

	const addMemory = async (payload: {
		text: string;
		type?: string;
		layer?: string;
		importance?: number;
		confidence?: number;
		confidence_source?: string;
		metadata?: MemoryMetadata;
		session_id?: string;
		workspace_id?: string;
		scope?: string;
	}) => {
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

	const queryMemory = async (payload: {
		query: string;
		top_k?: number;
		memory_types?: string[];
		session_id?: string;
		workspace_id?: string;
		scope?: string;
		layers?: string[];
	}) => {
		const resolvedScope = resolveScope(payload);
		const resolvedWorkspaceId = resolveScopedWorkspaceId(payload);
		const result = await queryRequest.execute(() =>
			memoryClient.queryPipeline(payload.query, {
				topK: payload.top_k ?? 5,
				sessionId: payload.session_id,
				workspaceId: resolvedWorkspaceId,
				scope: resolvedScope === "workspace" ? undefined : resolvedScope,
				layers: payload.layers,
			}),
		);
		if (result) {
			queryResult.value = normalizeQueryResult(result);
		}
	};

	const queryRawRag = async (payload: {
		query: string;
		top_k?: number;
		memory_types?: string[];
		session_id?: string;
		workspace_id?: string;
		scope?: string;
		layers?: string[];
		recency_weight?: number;
	}) => {
		const resolvedScope = resolveScope(payload);
		const resolvedWorkspaceId = resolveScopedWorkspaceId(payload);
		const result = await rawQueryRequest.execute(() =>
			memoryClient.queryRag({
				query: payload.query,
				top_k: payload.top_k ?? 5,
				memory_types: payload.memory_types,
				session_id: payload.session_id,
				workspace_id: resolvedWorkspaceId,
				scope: resolvedScope,
				layers: payload.layers ?? [
					"profile",
					"working",
					"episodic",
					"relationship",
					"reflective",
					"semantic",
				],
				recency_weight: payload.recency_weight ?? 0.2,
			}),
		);
		if (result) {
			queryResult.value = normalizeQueryResult(result);
		}
	};

	const loadIndexStatus = async () => {
		return statusRequest.execute(() => memoryClient.getIndexStatus());
	};

	return {
		docs,
		queryResult,
		docsRequest,
		addRequest,
		updateRequest,
		queryRequest,
		rawQueryRequest,
		statusRequest,
		loadDocs,
		addMemory,
		updateDoc,
		queryMemory,
		queryRawRag,
		loadIndexStatus,
	};
}
