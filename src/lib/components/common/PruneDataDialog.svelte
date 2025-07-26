<script lang="ts">
  import { createEventDispatcher, getContext } from 'svelte';
  import Modal from '$lib/components/common/Modal.svelte';
  import Switch from '$lib/components/common/Switch.svelte';

  const i18n = getContext('i18n');

  export let show = false;

  let deleteChatsByAge = false;
  let days = 60;
  let exempt_archived_chats = true;

  const dispatch = createEventDispatcher();

  const confirm = () => {
    dispatch('confirm', { 
      days: deleteChatsByAge ? days : null, 
      exempt_archived_chats 
    });
    show = false;
  };
</script>

<Modal bind:show size="sm">
  <div>
    <div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
      <div class="text-lg font-medium self-center">
        {$i18n.t('Prune Orphaned Data')}
      </div>
      <button
        class="self-center"
        on:click={() => {
          show = false;
        }}
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

    <div class="flex flex-col w-full px-5 pb-5 dark:text-gray-200">
      <div class="space-y-4">
        <!-- Warning Message -->
        <div class="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
          <div class="flex">
            <div class="flex-shrink-0">
              <svg class="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
              </svg>
            </div>
            <div class="ml-3">
              <p class="text-sm text-yellow-800 dark:text-yellow-200">
                {$i18n.t('This action will permanently delete all orphaned data (files, notes, prompts, etc.) from the database. This cannot be undone.')}
              </p>
            </div>
          </div>
        </div>

        <!-- Chat Deletion Section -->
        <div class="space-y-4">
          <div class="flex items-center justify-between py-2">
            <div class="flex items-center space-x-3">
              <Switch bind:state={deleteChatsByAge} />
              <div>
                <div class="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {$i18n.t('Delete chats by age')}
                </div>
                <div class="text-xs text-gray-500 dark:text-gray-400">
                  {$i18n.t('Optionally remove old chats based on last update time')}
                </div>
              </div>
            </div>
          </div>

          <!-- Chat Options (when enabled) -->
          {#if deleteChatsByAge}
            <div class="ml-8 space-y-4 border-l-2 border-gray-200 dark:border-gray-700 pl-4">
              <div class="space-y-2">
                <label class="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {$i18n.t('Delete chats older than')}
                </label>
                <div class="flex items-center space-x-2">
                  <input
                    id="days"
                    type="number"
                    min="0"
                    bind:value={days}
                    class="w-20 px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                  <span class="text-sm text-gray-700 dark:text-gray-300">{$i18n.t('days')}</span>
                </div>
                <p class="text-xs text-gray-500 dark:text-gray-400">
                  {$i18n.t('Set to 0 to delete all chats, or specify number of days')}
                </p>
              </div>
              
              <div class="flex items-center justify-between py-2">
                <div class="flex items-center space-x-3">
                  <Switch bind:state={exempt_archived_chats} />
                  <div>
                    <div class="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {$i18n.t('Exempt archived chats')}
                    </div>
                    <div class="text-xs text-gray-500 dark:text-gray-400">
                      {$i18n.t('Keep archived chats even if they are old')}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          {/if}
        </div>

        <!-- Additional Info -->
        <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
          <div class="flex">
            <div class="flex-shrink-0">
              <svg class="h-5 w-5 text-blue-400" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" />
              </svg>
            </div>
            <div class="ml-3">
              <p class="text-sm text-blue-800 dark:text-blue-200">
                {$i18n.t('This operation will also optimize your database and clean up orphaned vector collections and uploaded files.')}
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="mt-6 flex justify-end gap-3">
        <button
          class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700 transition-colors"
          on:click={() => (show = false)}
        >
          {$i18n.t('Cancel')}
        </button>
        <button
          class="px-4 py-2 text-sm font-medium text-white bg-yellow-600 border border-transparent rounded-lg hover:bg-yellow-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-yellow-500 transition-colors"
          on:click={confirm}
        >
          {$i18n.t('Prune Data')}
        </button>
      </div>
    </div>
  </div>
</Modal>
