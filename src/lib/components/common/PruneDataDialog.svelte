<script lang="ts">
  import { createEventDispatcher, getContext } from 'svelte';
  import Modal from '$lib/components/common/Modal.svelte';
  import Switch from '$lib/components/common/Switch.svelte';

  const i18n = getContext('i18n');

  export let show = false;

  let days = 60;
  let exempt_archived_chats = true;

  const dispatch = createEventDispatcher();

  const confirm = () => {
    dispatch('confirm', { days, exempt_archived_chats });
    show = false;
  };
</script>

<Modal bind:show title={$i18n.t('Prune Orphaned Data')} on:confirm>
  <div class="flex flex-col space-y-4 text-sm text-gray-500">
    <p>
      {$i18n.t(
        'This action will permanently delete old chats and all orphaned data (files, notes, prompts, etc.) from the database. This cannot be undone.'
      )}
    </p>
    <div class="flex items-center space-x-2">
      <label for="days" class="dark:text-gray-200">{$i18n.t('Delete chats older than')}</label>
      <input
        id="days"
        type="number"
        min="0"
        bind:value={days}
        class="w-20 bg-gray-100 dark:bg-gray-800 rounded-md p-2"
      />
      <label for="days" class="dark:text-gray-200">{$i18n.t('days')}</label>
    </div>
    <div class="flex items-center space-x-2">
      <Switch bind:state={exempt_archived_chats} />
      <label class="dark:text-gray-200">{$i18n.t('Exempt archived chats')}</label>
    </div>
  </div>
  <div class="mt-6 flex justify-between gap-1.5">
    <button
      class="bg-gray-100 hover:bg-gray-200 text-gray-800 dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-white font-medium w-full py-2.5 rounded-lg transition"
      on:click={() => (show = false)}>{$i18n.t('Cancel')}</button
    >
    <button
      class="bg-yellow-500 hover:bg-yellow-600 text-white font-medium w-full py-2.5 rounded-lg transition"
      on:click={confirm}>{$i18n.t('Prune')}</button
    >
  </div>
</Modal>
