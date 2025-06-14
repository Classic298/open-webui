<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte'; // Assuming a generic textarea is suitable
	import { WEBUI_BASE_URL } from '$lib/constants'; // Or other relevant base URL if needed for icons

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	export let show = false;
	export let folder = { id: '', name: '', system_prompt: '', emoji: '' }; // Default structure

	let currentName = '';
	let currentSystemPrompt = '';
	// Emoji will be part of the name for now, or handled separately if a simple input is desired.
	// For this task, we'll assume emoji is part of the name or not explicitly handled by a separate input in the modal.

	let loading = false;

	onMount(() => {
		currentName = folder.name || '';
		currentSystemPrompt = folder.system_prompt || '';
	});

	// Update local state when folder prop changes (e.g., when opening modal for different folder)
	$: if (folder && show) {
		currentName = folder.name || '';
		currentSystemPrompt = folder.system_prompt || '';
	}

	const handleSubmit = () => {
		if (!currentName.trim()) {
			// Basic validation, can be enhanced with toast notifications like in AddConnectionModal
			alert('Folder name cannot be empty.'); // Replace with toast if available/easy
			return;
		}
		loading = true;
		dispatch('saveFolder', {
			id: folder.id,
			name: currentName,
			system_prompt: currentSystemPrompt,
			emoji: folder.emoji // Pass along original emoji for now, or extract if included in name
		});
		// The parent component will handle actual saving and closing the modal
		// loading = false; // Parent should set show=false which will hide modal
	};

	const handleClose = () => {
		dispatch('close'); // Or parent can just set show = false
		show = false;
	};
</script>

<Modal bind:show on:close={handleClose} size="sm">
	<div>
		<div class="flex justify-between items-center dark:text-gray-100 px-5 pt-4 pb-1.5">
			<div class="text-lg font-medium self-center font-primary">
				{$i18n.t('Edit Folder')}
			</div>
			<button
				class="self-center p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-full"
				on:click={handleClose}
				aria-label={$i18n.t('Close')}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<form
			class="flex flex-col w-full px-4 pb-4 md:space-y-4 dark:text-gray-200"
			on:submit|preventDefault={handleSubmit}
		>
			<div class="px-1 space-y-3">
				<div>
					<label for="folderName" class="block mb-1 text-xs text-gray-500">
						{$i18n.t('Folder Name')}
					</label>
					<input
						id="folderName"
						class="w-full text-sm bg-transparent placeholder:text-gray-400 dark:placeholder:text-gray-600 outline-none border border-gray-300 dark:border-gray-700 rounded-lg p-2 focus:ring-1 focus:ring-blue-500"
						type="text"
						bind:value={currentName}
						placeholder={$i18n.t('Enter folder name')}
						required
					/>
				</div>

				<div>
					<label for="systemPrompt" class="block mb-1 text-xs text-gray-500">
						{$i18n.t('System Prompt (Optional)')}
					</label>
					<Textarea
						id="systemPrompt"
						bind:value={currentSystemPrompt}
						placeholder={$i18n.t('Enter a system prompt for all chats in this folder...')}
						className="w-full text-sm bg-transparent placeholder:text-gray-400 dark:placeholder:text-gray-600 outline-none border border-gray-300 dark:border-gray-700 rounded-lg p-2 focus:ring-1 focus:ring-blue-500 min-h-[100px] resize-y"
					/>
				</div>
			</div>

			<div class="flex justify-end items-center pt-3 text-sm font-medium gap-2">
				<button
					type="button"
					class="px-3.5 py-1.5 text-sm font-medium dark:bg-gray-700 dark:hover:bg-gray-600 bg-gray-100 hover:bg-gray-200 text-black dark:text-white transition rounded-full"
					on:click={handleClose}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-800 text-white dark:bg-white dark:text-black dark:hover:bg-gray-200 transition rounded-full flex items-center"
					type="submit"
					disabled={loading}
				>
					{#if loading}
						<div class="mr-2 self-center">
							<!-- Basic spinner -->
							<svg class="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" viewBox="0 0 24 24"></svg>
						</div>
					{/if}
					{$i18n.t('Save')}
				</button>
			</div>
		</form>
	</div>
</Modal>
