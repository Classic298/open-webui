import { VIDEOS_API_BASE_URL } from '$lib/constants';

// Define the expected shape of the video configuration object
export interface VideoConfig {
	ENABLE_VIDEO_GENERATION: boolean;
	VIDEO_GENERATION_API_URL: string;
	VIDEO_GENERATION_API_KEY: string;
	VIDEO_GENERATION_DEFAULT_MODEL: string;
	VIDEO_GENERATION_TIMEOUT: number;
}

// Define the expected shape of a video model info object
export interface VideoModelInfo {
	id: string;
	name: string;
}

export const getVideoGenerationConfig = async (token: string = ''): Promise<VideoConfig | null> => {
	let error = null;

	const res = await fetch(`${VIDEOS_API_BASE_URL}/config`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json() as VideoConfig;
		})
		.catch((err) => {
			console.error(`Error fetching video generation config: ${err}`);
			if ('detail' in err) {
				error = err.detail;
			} else {
				error = 'Server connection failed while fetching video config.';
			}
			return null;
		});

	if (error) {
		throw new Error(error);
	}

	return res;
};

export const updateVideoGenerationConfig = async (
	token: string = '',
	config: VideoConfig
): Promise<VideoConfig | null> => {
	let error = null;

	const res = await fetch(`${VIDEOS_API_BASE_URL}/config/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify(config)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json() as VideoConfig;
		})
		.catch((err) => {
			console.error(`Error updating video generation config: ${err}`);
			if ('detail' in err) {
				error = err.detail;
			} else {
				error = 'Server connection failed while updating video config.';
			}
			return null;
		});

	if (error) {
		throw new Error(error);
	}

	return res;
};

export const getVideoGenerationModels = async (token: string = ''): Promise<VideoModelInfo[] | null> => {
	let error = null;

	const res = await fetch(`${VIDEOS_API_BASE_URL}/models`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json() as VideoModelInfo[];
		})
		.catch((err) => {
			console.error(`Error fetching video generation models: ${err}`);
			if ('detail' in err) {
				error = err.detail;
			} else {
				error = 'Server connection failed while fetching video models.';
			}
			return null;
		});

	if (error) {
		throw new Error(error);
	}

	return res;
};

// Note: The video generation endpoint itself (e.g., POST /videos/generations)
// would be added here if client-side generation requests were to be made directly.
// For now, this file only contains config and model fetching logic for the admin settings page.
// Example for a generation function:
// export const generateVideo = async (token: string = '', prompt: string, model: string, height: number, width: number, n_seconds: number) => { ... }
