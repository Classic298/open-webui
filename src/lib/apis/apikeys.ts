import { WEBUI_API_BASE_URL } from '$lib/constants';
import type { User } from '$lib/types'; // Assuming User type might be needed for admin checks or responses

// Define interfaces based on Pydantic models from the backend
// These should match what backend/open_webui/routers/apikeys.py expects/returns

export interface ApiKey {
	id: string;
	name: string | null;
	email: string | null; // Email of the key itself (for standalone) or associated user
	role: string | null; // Role of the key (for standalone) or associated user
	user_id: string | null;
	created_at: number;
	last_used_at: number | null;
	expires_at: number | null;
	info: object | null;
	key: string | null; // Only present on creation
	is_standalone: boolean;
	user_name: string | null; // Name of the associated user, if any
	// user_email is already covered by 'email' if we adopt the backend's merged approach.
	// If we need separate key.email and user.email, we'd add user_email here.
	// For now, assuming 'email' field correctly represents either key's or user's email.
	key_display: string | null; // e.g., sk-...XXXX
}

export interface CreateStandaloneApiKeyForm {
	name?: string | null;
	email?: string | null;
	role?: string | null;
	expires_at?: number | null;
}

export interface UpdateStandaloneApiKeyForm {
	name?: string | null;
	email?: string | null;
	role?: string | null;
	expires_at?: number | null;
}

export interface PaginatedApiKeysResponse {
	keys: ApiKey[];
	total: number;
	page: number;
	page_size: number;
}

const getApiKeyBaseUrl = () => `${WEBUI_API_BASE_URL}/v1/apikeys`; // Matches router prefix in main.py

// Generic request function
const request = async <T>(
	method: string,
	url: string,
	body: object | null = null,
	token: string
): Promise<T> => {
	const headers = new Headers();
	headers.append('Authorization', `Bearer ${token}`);
	if (body) {
		headers.append('Content-Type', 'application/json');
	}

	const options: RequestInit = {
		method,
		headers,
		body: body ? JSON.stringify(body) : null
	};

	const response = await fetch(url, options);

	if (!response.ok) {
		const errorData = await response.json().catch(() => ({ detail: response.statusText }));
		throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
	}
	return response.json();
};

// Get all API Keys (Admin)
export const getAllApiKeysAdmin = async (
	token: string,
	params: {
		page?: number;
		page_size?: number;
		sort_by?: string;
		sort_order?: 'asc' | 'desc';
		q?: string;
		user_id_filter?: string;
		role_filter?: string;
	} = {}
): Promise<PaginatedApiKeysResponse> => {
	const queryParams = new URLSearchParams();
	if (params.page) queryParams.append('page', params.page.toString());
	if (params.page_size) queryParams.append('page_size', params.page_size.toString());
	if (params.sort_by) queryParams.append('sort_by', params.sort_by);
	if (params.sort_order) queryParams.append('sort_order', params.sort_order);
	if (params.q) queryParams.append('q', params.q);
	if (params.user_id_filter) queryParams.append('user_id_filter', params.user_id_filter);
	if (params.role_filter) queryParams.append('role_filter', params.role_filter);

	const url = `${getApiKeyBaseUrl()}/admin/api_keys?${queryParams.toString()}`;
	return request<PaginatedApiKeysResponse>('GET', url, null, token);
};

// Create Standalone API Key (Admin)
export const createStandaloneApiKeyAdmin = async (
	token: string,
	formData: CreateStandaloneApiKeyForm
): Promise<ApiKey> => {
	const url = `${getApiKeyBaseUrl()}/admin/api_keys`;
	return request<ApiKey>('POST', url, formData, token);
};

// Get API Key by ID (Admin)
export const getApiKeyByIdAdmin = async (token: string, keyId: string): Promise<ApiKey> => {
	const url = `${getApiKeyBaseUrl()}/admin/api_keys/${keyId}`;
	return request<ApiKey>('GET', url, null, token);
};

// Update Standalone API Key by ID (Admin)
export const updateStandaloneApiKeyAdmin = async (
	token: string,
	keyId: string,
	formData: UpdateStandaloneApiKeyForm
): Promise<ApiKey> => {
	const url = `${getApiKeyBaseUrl()}/admin/api_keys/${keyId}`;
	return request<ApiKey>('PUT', url, formData, token);
};

// Delete API Key by ID (Admin)
export const deleteApiKeyAdmin = async (
	token: string,
	keyId: string
): Promise<{ detail: string }> => {
	const url = `${getApiKeyBaseUrl()}/admin/api_keys/${keyId}`;
	return request<{ detail: string }>('DELETE', url, null, token);
};

// User-specific API key operations (these would typically live in a user-specific API file)

// Regenerate User API Key
export const regenerateUserApiKey = async (token: string): Promise<ApiKey> => {
	// Note: The backend route for this is /api/v1/auths/api_key
	const url = `${WEBUI_API_BASE_URL}/v1/auths/api_key`;
	return request<ApiKey>('POST', url, {}, token); // Empty body for regenerate
};

// Get User API Key
export const getUserApiKey = async (token: string): Promise<ApiKey> => {
	const url = `${WEBUI_API_BASE_URL}/v1/auths/api_key`;
	return request<ApiKey>('GET', url, null, token);
};

// Delete User API Key
export const deleteUserApiKey = async (token: string): Promise<boolean> => {
	const url = `${WEBUI_API_BASE_URL}/v1/auths/api_key`;
	// Backend returns boolean (true if deleted)
	const response = await fetch(url, {
		method: 'DELETE',
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!response.ok) {
		const errorData = await response.json().catch(() => ({ detail: response.statusText }));
		throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
	}
	// Assuming backend returns { "success": true } or similar, or just true
	// For now, let's adapt to the boolean response from the backend for delete
	const data = await response.json();
	return typeof data === 'boolean' ? data : (data.success || false);
};
