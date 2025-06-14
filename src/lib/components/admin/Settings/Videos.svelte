<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { config as backendConfig, user } from '$lib/stores';

	import { getBackendConfig } from '$lib/apis';
	// Placeholder for actual video API calls - these would be in a new file e.g., $lib/apis/videos.ts
	import {
		getVideoGenerationModels, // To be created
		getVideoGenerationConfig, // To be created
		updateVideoGenerationConfig // To be created
	} from '$lib/apis/videos'; // Assuming a new videos.ts API utility

	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	let loading = false;
	let initialLoading = true;

	// This will hold the specific video generation settings
	// e.g., { ENABLE_VIDEO_GENERATION: false, VIDEO_GENERATION_API_URL: '', ... }
	let videoConfig = null;
	let videoModels = null;

	const getVideoModels = async () => {
		if (!$user || $user.role !== 'admin') return;
		try {
			videoModels = await getVideoGenerationModels(localStorage.token);
		} catch (error) {
			toast.error(`Error fetching video models: ${error.message}`);
			videoModels = [];
		}
	};

	const loadVideoConfig = async () => {
		if (!$user || $user.role !== 'admin') return;
		initialLoading = true;
		try {
			const configFromServer = await getVideoGenerationConfig(localStorage.token);
			if (configFromServer) {
				videoConfig = configFromServer;
				if (videoConfig.ENABLE_VIDEO_GENERATION) {
					await getVideoModels();
				}
			} else {
				// Initialize with default structure if config is null/undefined
				videoConfig = {
					ENABLE_VIDEO_GENERATION: false,
					VIDEO_GENERATION_API_URL: '',
					VIDEO_GENERATION_API_KEY: '',
					VIDEO_GENERATION_DEFAULT_MODEL: '',
					VIDEO_GENERATION_TIMEOUT: 120
				};
				toast.info('Video generation config not found, initialized with defaults.');
			}
		} catch (error) {
			toast.error(`Error fetching video config: ${error.message}`);
			// Fallback to a default structure on error to prevent UI breakage
			videoConfig = {
				ENABLE_VIDEO_GENERATION: false,
				VIDEO_GENERATION_API_URL: '',
				VIDEO_GENERATION_API_KEY: '',
				VIDEO_GENERATION_DEFAULT_MODEL: '',
				VIDEO_GENERATION_TIMEOUT: 120
			};
		} finally {
			initialLoading = false;
		}
	};

	const saveHandler = async () => {
		if (!videoConfig) {
			toast.error('Video configuration is not loaded.');
			return;
		}
		loading = true;
		try {
			const configToSave = { ...videoConfig }; // Ensure we are sending all fields

			const updatedConfig = await updateVideoGenerationConfig(localStorage.token, configToSave);
			if (updatedConfig) {
				videoConfig = updatedConfig;
				// Update backendConfig store potentially, if video settings affect it globally
				// For now, just refetching video models if enabled
				if (videoConfig.ENABLE_VIDEO_GENERATION) {
					await getVideoModels();
				}
				// Update the global backendConfig store if these settings are part of it
				// This might require getVideoGenerationConfig to be part of a larger getBackendConfig call
				// or for backendConfig to be updated selectively.
				// For now, we assume videoConfig is self-contained for this settings page.
				// Example: $backendConfig.videoGeneration = updatedConfig;
				// backendConfig.set(await getBackendConfig()); // Or refetch all if simpler
				toast.success($i18n.t('Video settings saved successfully!'));
				dispatch('save');
			} else {
				toast.error($i18n.t('Failed to save video settings.'));
			}
		} catch (error) {
			toast.error(`Error saving video settings: ${error.message}`);
		} finally {
			loading = false;
		}
	};

	onMount(async () => {
		await loadVideoConfig();
	});
</script>

{#if initialLoading}
	<div class="flex justify-center items-center h-full">
		<p>{$i18n.t('Loading video settings...')}</p>
	</div>
{:else if videoConfig}
	<form
		class="flex flex-col h-full justify-between space-y-3 text-sm"
		on:submit|preventDefault={saveHandler}
	>
		<div class="space-y-3 overflow-y-scroll scrollbar-hidden pr-2">
			<div>
				<div class="mb-1 text-sm font-medium">{$i18n.t('Video Generation Settings')}</div>

				<div class="py-1 flex w-full justify-between">
					<div class="self-center text-xs font-medium">
						{$i18n.t('Enable Video Generation')}
						<Tooltip content={$i18n.t('Enable or disable the video generation feature.')} />
					</div>
					<div class="px-1">
						<Switch
							bind:state={videoConfig.ENABLE_VIDEO_GENERATION}
							on:change={async (e) => {
								if (videoConfig.ENABLE_VIDEO_GENERATION) {
									if (!videoConfig.VIDEO_GENERATION_API_URL) {
										toast.error($i18n.t('Video Generation API URL is required.'));
										videoConfig.ENABLE_VIDEO_GENERATION = false;
									} else {
										await getVideoModels(); // Fetch models when enabled
									}
								}
							}}
						/>
					</div>
				</div>
			</div>

			{#if videoConfig.ENABLE_VIDEO_GENERATION}
				<hr class="border-gray-100 dark:border-gray-850" />

				<div class="flex flex-col gap-3">
					<div>
						<div class="mb-2 text-sm font-medium">
							{$i18n.t('Video Generation API URL')}
							<Tooltip
								content={$i18n.t(
									'The base URL of your video generation API (e.g., http://localhost:8000/api/v1)'
								)}
							/>
						</div>
						<input
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-none"
							placeholder={$i18n.t('Enter API URL')}
							bind:value={videoConfig.VIDEO_GENERATION_API_URL}
							required
						/>
					</div>

					<div>
						<div class="mb-2 text-sm font-medium">
							{$i18n.t('Video Generation API Key')}
							<Tooltip content={$i18n.t('The API key for your video generation service.')} />
						</div>
						<SensitiveInput
							placeholder={$i18n.t('Enter API Key (optional if not required by your service)')}
							bind:value={videoConfig.VIDEO_GENERATION_API_KEY}
							required={false}
						/>
					</div>

					<div>
						<div class="mb-2 text-sm font-medium">
							{$i18n.t('Default Video Generation Model')}
							<Tooltip
								content={$i18n.t(
									'The default model to be used for video generation if not specified in a request.'
								)}
							/>
						</div>
						<input
							list="video-model-list"
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-none"
							placeholder={$i18n.t('Select or enter default model ID')}
							bind:value={videoConfig.VIDEO_GENERATION_DEFAULT_MODEL}
						/>
						<datalist id="video-model-list">
							{#if videoModels && videoModels.length > 0}
								{#each videoModels as model}
									<option value={model.id}>{model.name}</option>
								{/each}
							{:else}
								<option value="" disabled>{$i18n.t('No models loaded or found')}</option>
							{/if}
						</datalist>
						<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t(
								'Available models are fetched from the backend. Ensure your API URL is correct and the service is running.'
							)}
						</div>
					</div>

					<div>
						<div class="mb-2 text-sm font-medium">
							{$i18n.t('Video Generation Timeout (seconds)')}
							<Tooltip
								content={$i18n.t(
									'Timeout in seconds for requests to the video generation API.'
								)}
							/>
						</div>
						<input
							type="number"
							min="1"
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-none"
							placeholder={$i18n.t('Enter timeout (e.g., 120)')}
							bind:value={videoConfig.VIDEO_GENERATION_TIMEOUT}
							required
						/>
					</div>
				</div>
			{/if}
		</div>

		<div class="flex justify-end pt-3 text-sm font-medium">
			<button
				class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center {loading
					? ' cursor-not-allowed'
					: ''}"
				type="submit"
				disabled={loading || initialLoading}
			>
				{$i18n.t('Save')}
				{#if loading}
					<div class="ml-2 self-center">
						<svg
							class="w-4 h-4"
							viewBox="0 0 24 24"
							fill="currentColor"
							xmlns="http://www.w3.org/2000/svg"
						>
							<style>
								.spinner_ajPY {
									transform-origin: center;
									animation: spinner_AtaB 0.75s infinite linear;
								}
								@keyframes spinner_AtaB {
									100% {
										transform: rotate(360deg);
									}
								}
							</style>
							<path
								d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
								opacity=".25"
							/>
							<path
								d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
								class="spinner_ajPY"
							/>
						</svg>
					</div>
				{/if}
			</button>
		</div>
	</form>
{:else}
	<div class="flex justify-center items-center h-full">
		<p>{$i18n.t('Failed to load video settings. Please try refreshing the page.')}</p>
	</div>
{/if}
