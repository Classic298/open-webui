<script lang="ts">
	import AdminLayout from '../+layout.svelte'; // Assuming a common admin layout
	import ApiKeyList from '$lib/components/admin/ApiKeys/ApiKeyList.svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	// Ensure user is on the correct path if they land on /admin/settings/apikeys
	// This specific page is /admin/apikeys, so direct settings check is less relevant here,
	// but admin access is handled by +layout.svelte or individual components.

</script>

<svelte:head>
	<title>Admin - API Keys</title>
</svelte:head>

<AdminLayout>
	<div class="flex justify-between items-center mb-4">
		<h1 class="text-2xl font-semibold">API Key Management</h1>
	</div>

	<!-- This component will be created next -->
	<ApiKeyList />
</AdminLayout>
