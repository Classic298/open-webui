<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { getAllApiKeysAdmin, deleteApiKeyAdmin, type ApiKey } from '$lib/apis/apikeys';
	import { config } from '$lib/stores';
	import FaSolidEdit from 'svelte-icons-pack/fa/FaSolidEdit';
	import FaSolidTrash from 'svelte-icons-pack/fa/FaSolidTrash';
	import Button from '$lib/components/common/Button.svelte'; // Assuming a common Button component
    import ConfirmModal from '$lib/components/common/ConfirmModal.svelte'; // Assuming a common ConfirmModal
	import EditApiKeyModal from './EditApiKeyModal.svelte';
	import { format } from 'date-fns';

	const dispatch = createEventDispatcher();

	let apiKeys: ApiKey[] = [];
	let isLoading = true;
	let errorLoading: string | null = null;

	// For EditApiKeyModal
	let showEditModal = false;
	let currentEditMode: 'create' | 'edit' = 'create';
	let selectedApiKey: ApiKey | null = null;

    // For ConfirmModal (revoke)
    let showConfirmModal = false;
    let apiKeyToRevoke: ApiKey | null = null;
    let confirmModalTitle = '';
    let confirmModalMessage = '';

	// Pagination, sorting, filtering parameters (can be expanded)
	let currentPage = 1;
	let pageSize = 10;
	let totalKeys = 0;
	// TODO: Add more state for sorting and filtering inputs

	const fetchApiKeys = async () => {
		isLoading = true;
		errorLoading = null;
		try {
			const response = await getAllApiKeysAdmin($config.token, {
				page: currentPage,
				page_size: pageSize
				// TODO: Pass sorting/filtering params here
			});
			apiKeys = response.keys;
			totalKeys = response.total;
		} catch (err) {
			let message = 'Unknown error';
			if (err instanceof Error) {
				message = err.message;
			}
			errorLoading = `Failed to load API keys: ${message}`;
			toast.error(errorLoading);
		} finally {
			isLoading = false;
		}
	};

	onMount(() => {
		fetchApiKeys();
	});

	const handleCreateNew = () => {
		currentEditMode = 'create';
		selectedApiKey = null;
		showEditModal = true;
	};

	const handleEditKey = (key: ApiKey) => {
		if (!key.is_standalone) {
			toast.info('User-associated API keys cannot be edited here. Users manage their own keys.');
			return;
		}
		currentEditMode = 'edit';
		selectedApiKey = key;
		showEditModal = true;
	};

    const openRevokeConfirm = (key: ApiKey) => {
        apiKeyToRevoke = key;
        confirmModalTitle = 'Revoke API Key';
        confirmModalMessage = `Are you sure you want to revoke the API key "${key.user_name && !key.is_standalone ? key.user_name : key.name || 'Unnamed Key'}"? This action cannot be undone.`;
        showConfirmModal = true;
    };

	const handleRevokeKey = async () => {
        if (!apiKeyToRevoke) return;
		try {
			await deleteApiKeyAdmin($config.token, apiKeyToRevoke.id);
			toast.success(`API Key for "${apiKeyToRevoke.name || apiKeyToRevoke.user_name}" revoked successfully.`);
			fetchApiKeys(); // Refresh list
		} catch (err) {
            let message = 'Unknown error';
			if (err instanceof Error) {
				message = err.message;
			}
			toast.error(`Failed to revoke API key: ${message}`);
		} finally {
            showConfirmModal = false;
            apiKeyToRevoke = null;
        }
	};

	const formatDate = (timestamp: number | null): string => {
		if (!timestamp) return 'N/A';
		return format(new Date(timestamp * 1000), 'MMM dd, yyyy HH:mm');
	};

    const formatExpiry = (timestamp: number | null): string => {
        if (!timestamp) return 'Does not expire';
        return format(new Date(timestamp * 1000), 'MMM dd, yyyy HH:mm');
    }
</script>

<div class="mb-4 flex justify-between items-center">
	<h2 class="text-xl font-semibold">API Keys</h2>
	<Button type="button" color="primary" on:click={handleCreateNew}>Create Standalone Key</Button>
</div>

{#if isLoading}
	<p>Loading API keys...</p>
{:else if errorLoading}
	<p class="text-red-500">{errorLoading}</p>
{:else if apiKeys.length === 0}
	<p>No API keys found. Create one to get started!</p>
{:else}
	<div class="overflow-x-auto shadow-md sm:rounded-lg">
		<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">
			<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
				<tr>
					<th scope="col" class="px-6 py-3">User / Name</th>
					<th scope="col" class="px-6 py-3">Email</th>
					<th scope="col" class="px-6 py-3">API Key (Masked)</th>
					<th scope="col" class="px-6 py-3">Role</th>
					<th scope="col" class="px-6 py-3">Created</th>
					<th scope="col" class="px-6 py-3">Last Used</th>
                    <th scope="col" class="px-6 py-3">Expires At</th>
					<th scope="col" class="px-6 py-3">Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each apiKeys as key (key.id)}
					<tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
						<td class="px-6 py-4">
                            {#if key.is_standalone}
                                <span class="font-semibold">Standalone:</span> {key.name || '(Unnamed)'}
                            {:else}
                                {key.user_name || '(User N/A)'}
                            {/if}
                        </td>
						<td class="px-6 py-4">{key.email || 'N/A'}</td>
						<td class="px-6 py-4 font-mono">{key.key_display || 'N/A'}</td>
						<td class="px-6 py-4">{key.role || 'N/A'}</td>
						<td class="px-6 py-4">{formatDate(key.created_at)}</td>
						<td class="px-6 py-4">{formatDate(key.last_used_at)}</td>
                        <td class="px-6 py-4">{formatExpiry(key.expires_at)}</td>
						<td class="px-6 py-4 flex space-x-2">
							<button
                                title="Edit Standalone Key"
                                class:cursor-not-allowed={!key.is_standalone}
                                class:opacity-50={!key.is_standalone}
                                on:click={() => key.is_standalone && handleEditKey(key)}
                                disabled={!key.is_standalone}
                            >
								<FaSolidEdit class="w-4 h-4 text-blue-500 hover:text-blue-700" />
							</button>
							<button title="Revoke Key" on:click={() => openRevokeConfirm(key)}>
								<FaSolidTrash class="w-4 h-4 text-red-500 hover:text-red-700" />
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
    <!-- TODO: Add pagination controls -->
{/if}

<EditApiKeyModal
	bind:showModal={showEditModal}
	mode={currentEditMode}
	apiKeyToEdit={selectedApiKey}
	on:save={fetchApiKeys}
    on:close={() => showEditModal = false}
/>

<ConfirmModal
    bind:open={showConfirmModal}
    title={confirmModalTitle}
    message={confirmModalMessage}
    on:confirm={handleRevokeKey}
    on:cancel={() => {showConfirmModal = false; apiKeyToRevoke = null;}}
/>
