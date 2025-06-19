<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import type { ApiKey, CreateStandaloneApiKeyForm, UpdateStandaloneApiKeyForm } from '$lib/apis/apikeys';
	import { Modal, Input, Button, Select, Label, Datepicker } from 'flowbite-svelte'; // Assuming flowbite components are available
	import { config } from '$lib/stores';
    import { toast } from 'svelte-sonner';
    import { createStandaloneApiKeyAdmin, updateStandaloneApiKeyAdmin } from '$lib/apis/apikeys';

	export let showModal = false;
	export let mode: 'create' | 'edit' = 'create';
	export let apiKeyToEdit: ApiKey | null = null;

	const dispatch = createEventDispatcher();

	let formData: {
		name: string;
		email: string;
		role: string;
		expires_at: Date | null; // Use Date object for Datepicker
	} = {
		name: '',
		email: '',
		role: 'user', // Default role
		expires_at: null
	};

    let isLoading = false;
    let newApiKey: string | null = null; // To display the key after creation

    // Pre-fill form if in edit mode
	onMount(() => {
		if (mode === 'edit' && apiKeyToEdit) {
			formData.name = apiKeyToEdit.name ?? '';
			formData.email = apiKeyToEdit.email ?? '';
			formData.role = apiKeyToEdit.role ?? 'user';
			formData.expires_at = apiKeyToEdit.expires_at ? new Date(apiKeyToEdit.expires_at * 1000) : null;
		} else {
            // Reset for create mode
            formData.name = '';
            formData.email = '';
            formData.role = 'user';
            formData.expires_at = null;
        }
        newApiKey = null; // Reset new API key display
	});

    // Reactive statement to reset form when mode or apiKeyToEdit changes (e.g. modal reopened)
    $: if (showModal) { // Only reset when modal becomes visible or key changes
        if (mode === 'edit' && apiKeyToEdit) {
            formData.name = apiKeyToEdit.name ?? '';
            formData.email = apiKeyToEdit.email ?? '';
            formData.role = apiKeyToEdit.role ?? 'user';
            formData.expires_at = apiKeyToEdit.expires_at ? new Date(apiKeyToEdit.expires_at * 1000) : null;
        } else {
            formData.name = '';
            formData.email = '';
            formData.role = 'user';
            formData.expires_at = null;
        }
        newApiKey = null;
    }


	const handleSubmit = async () => {
		isLoading = true;
        newApiKey = null;

		const payload = {
			name: formData.name || null, // Send null if empty
			email: formData.email || null,
			role: formData.role || 'user',
			expires_at: formData.expires_at ? Math.floor(formData.expires_at.getTime() / 1000) : null // Convert to Unix timestamp
		};

		try {
			if (mode === 'create') {
				const createdKey = await createStandaloneApiKeyAdmin($config.token, payload as CreateStandaloneApiKeyForm);
                newApiKey = createdKey.key; // Display this key
				toast.success('API Key created successfully. Please copy the key now, it will not be shown again.');
			} else if (mode === 'edit' && apiKeyToEdit) {
				await updateStandaloneApiKeyAdmin($config.token, apiKeyToEdit.id, payload as UpdateStandaloneApiKeyForm);
				toast.success('API Key updated successfully.');
			}
            dispatch('save'); // Notify parent to refresh list
            if (mode === 'edit' || !newApiKey) { // Close modal on edit, or if creation somehow didn't return a key
                 closeModal();
            }
		} catch (error) {
			toast.error(String(error));
		} finally {
			isLoading = false;
		}
	};

	const closeModal = () => {
		showModal = false;
        newApiKey = null; // Clear any displayed key when closing
		dispatch('close');
	};

    const copyToClipboard = () => {
        if (newApiKey) {
            navigator.clipboard.writeText(newApiKey)
                .then(() => toast.success('API Key copied to clipboard!'))
                .catch(err => toast.error('Failed to copy API Key: ' + err));
        }
    };

    // Example roles - can be fetched or configured if needed
    const availableRoles = [
        { value: 'user', name: 'User' },
        { value: 'admin', name: 'Admin' },
        { value: 'sdk-user', name: 'SDK User' },
        { value: 'viewer', name: 'Viewer'}
    ];
</script>

<Modal title={mode === 'create' ? 'Create Standalone API Key' : 'Edit Standalone API Key'} bind:open={showModal} on:close={closeModal} outsideclose>
	<form on:submit|preventDefault={handleSubmit}>
		{#if newApiKey}
			<div class="mb-4 p-3 bg-yellow-100 dark:bg-yellow-700 rounded-md">
				<Label for="newKeyDisplay" class="block mb-2 text-sm font-medium text-yellow-800 dark:text-yellow-200">Your New API Key (Copy this now):</Label>
                <div class="flex items-center">
				    <Input id="newKeyDisplay" type="text" value={newApiKey} readonly class="bg-white dark:bg-gray-800"/>
                    <Button on:click={copyToClipboard} color="alternative" class="ml-2">Copy</Button>
                </div>
                <p class="text-xs text-yellow-700 dark:text-yellow-300 mt-1">This key will not be shown again.</p>
			</div>
		{/if}

        {#if !newApiKey} <!-- Hide form after key generation until modal is closed/reopened -->
		<div class="grid gap-4 mb-6 md:grid-cols-2">
			<div>
				<Label for="keyName" class="block mb-2">Name (Optional)</Label>
				<Input id="keyName" type="text" placeholder="My SDK Key" bind:value={formData.name} />
			</div>
			<div>
				<Label for="keyEmail" class="block mb-2">Email (Optional, for identification)</Label>
				<Input id="keyEmail" type="email" placeholder="key-user@example.com" bind:value={formData.email} />
			</div>
			<div>
				<Label for="keyRole" class="block mb-2">Role</Label>
				<Select id="keyRole" items={availableRoles} bind:value={formData.role} />
			</div>
			<div>
				<Label for="keyExpires" class="block mb-2">Expires At (Optional)</Label>
                <!-- Assuming Datepicker component is correctly imported and used -->
                <!-- You might need to adjust props based on the actual Datepicker -->
                <Datepicker id="keyExpires" title="Select Expiry Date" bind:value={formData.expires_at} />
			</div>
		</div>
        {/if}

		<div class="flex justify-end space-x-2 mt-4">
            {#if newApiKey}
                <Button type="button" color="alternative" on:click={closeModal}>Close</Button>
            {:else}
                <Button type="button" color="alternative" on:click={closeModal} disabled={isLoading}>Cancel</Button>
                <Button type="submit" color="blue" disabled={isLoading}>
                    {#if isLoading}
                        Loading...
                    {:else}
                        {mode === 'create' ? 'Create Key' : 'Save Changes'}
                    {/if}
                </Button>
            {/if}
		</div>
	</form>
</Modal>
