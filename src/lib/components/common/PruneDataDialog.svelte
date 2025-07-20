<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import Modal from '$lib/components/common/Modal.svelte';
  import Switch from '$lib/components/common/Switch.svelte';

  export let show = false;

  let days = 60;
  let exempt_archived_chats = true;

  const dispatch = createEventDispatcher();

  const confirm = () => {
    dispatch('confirm', { days, exempt_archived_chats });
    show = false;
  };
</script>

<Modal bind:show title="Prune Orphaned Data" on:confirm>
  <div class="flex flex-col space-y-4">
    <p>
      This action will permanently delete chats and their associated files from the database. This cannot be undone.
    </p>
    <div class="flex items-center space-x-2">
      <label for="days">Delete chats older than</label>
      <input
        id="days"
        type="number"
        min="0"
        bind:value={days}
        class="w-20 bg-gray-100 dark:bg-gray-800 rounded-md p-1"
      />
      <label for="days">days</label>
    </div>
    <div class="flex items-center space-x-2">
      <Switch bind:state={exempt_archived_chats} />
      <label>Exempt archived chats</label>
    </div>
  </div>
  <div class="flex justify-end space-x-2 mt-4">
    <button class="p-2 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800" on:click={() => (show = false)}>Cancel</button>
    <button class="p-2 bg-yellow-500 text-white rounded-md hover:bg-yellow-600" on:click={confirm}>Prune</button>
  </div>
</Modal>
