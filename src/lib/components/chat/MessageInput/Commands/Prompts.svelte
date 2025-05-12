<script lang="ts">
    import { prompts, settings, user } from '$lib/stores';
    import {
        extractCurlyBraceWords,
        getUserPosition,
        getFormattedDate,
        getFormattedTime,
        getCurrentDateTime,
        getUserTimezone,
        getWeekday
    } from '$lib/utils';
    import { tick, getContext } from 'svelte';
    import { toast } from 'svelte-sonner';
    import TurndownService from 'turndown'; // ADDED THIS LINE

    const i18n = getContext('i18n');

    // ADDED THESE 5 LINES FOR TURNDOWN INITIALIZATION AND CUSTOM RULE
    const turndownService = new TurndownService({
        codeBlockStyle: 'fenced', headingStyle: 'atx', hr: '---',
        bulletListMarker: '*', emDelimiter: '_', strongDelimiter: '**'
    });
    turndownService.addRule('emptyOrBreakParagraphToNbsp', {
        filter: (node) => node.nodeName === 'P' && (node.innerHTML.trim() === '' || node.innerHTML.trim() === '<br>' || node.innerHTML.trim() === '<br/>'),
        replacement: () => '\n&nbsp;\n' // Converts empty <p> or <p><br></p> to a Markdown line with a non-breaking space
    });                                 // This helps 'marked.parse' create a <p>&nbsp;</p> for visual empty lines.

    export let files;

    export let prompt = ''; // This is the main prompt string for the input
    export let command = ''; // This is the typed command trigger string, e.g., "/mycommand"

    let selectedPromptIdx = 0;
    let filteredPrompts = [];

    $: {
        if (command && command.length > 1) {
            const commandName = command.substring(1).toLowerCase();
            const cleanedCommandName = commandName.replace(/<\/?p>/gi, '').trim();

            filteredPrompts = $prompts
                .filter((p) => p.command.toLowerCase().includes(cleanedCommandName))
                .sort((a, b) => a.title.localeCompare(b.title));
        } else {
            filteredPrompts = [];
        }
    }

    $: if (command) {
        selectedPromptIdx = 0;
    }

    export const selectUp = () => {
        selectedPromptIdx = Math.max(0, selectedPromptIdx - 1);
    };

    export const selectDown = () => {
        selectedPromptIdx = Math.min(selectedPromptIdx + 1, filteredPrompts.length - 1);
    };

    // 'commandFromStore' is the object selected from 'filteredPrompts'
    const confirmPrompt = async (commandFromStore) => {
        let textFromCommand = commandFromStore.content; // This is HTML, e.g., <p>Test</p><p></p><p>Test</p>

        // Placeholder replacements are performed on 'textFromCommand' (which is HTML)
        if (commandFromStore.content.includes('{{CLIPBOARD}}')) {
            const clipboardText = await navigator.clipboard.readText().catch((err) => {
                toast.error($i18n.t('Failed to read clipboard contents'));
                return '{{CLIPBOARD}}';
            });
            // ... (rest of clipboard logic) ...
            if (imageUrl) { /* ... */ } // imageUrl is defined within this block
            textFromCommand = textFromCommand.replaceAll('{{CLIPBOARD}}', clipboardText);
        }
        if (commandFromStore.content.includes('{{USER_LOCATION}}')) {
            // ... (location logic) ...
            textFromCommand = textFromCommand.replaceAll('{{USER_LOCATION}}', String(location)); // location is defined within this block
        }
        // ... (ALL OTHER PLACEHOLDER REPLACEMENTS on textFromCommand) ...
        if (commandFromStore.content.includes('{{USER_NAME}}')) {
            const name = $user?.name || 'User';
            textFromCommand = textFromCommand.replaceAll('{{USER_NAME}}', name);
        }
        if (commandFromStore.content.includes('{{USER_LANGUAGE}}')) {
            const language = localStorage.getItem('locale') || 'en-US';
            textFromCommand = textFromCommand.replaceAll('{{USER_LANGUAGE}}', language);
        }
        if (commandFromStore.content.includes('{{CURRENT_DATE}}')) {
            const date = getFormattedDate();
            textFromCommand = textFromCommand.replaceAll('{{CURRENT_DATE}}', date);
        }
        if (commandFromStore.content.includes('{{CURRENT_TIME}}')) {
            const time = getFormattedTime();
            textFromCommand = textFromCommand.replaceAll('{{CURRENT_TIME}}', time);
        }
        if (commandFromStore.content.includes('{{CURRENT_DATETIME}}')) {
            const dateTime = getCurrentDateTime();
            textFromCommand = textFromCommand.replaceAll('{{CURRENT_DATETIME}}', dateTime);
        }
        if (commandFromStore.content.includes('{{CURRENT_TIMEZONE}}')) {
            const timezone = getUserTimezone();
            textFromCommand = textFromCommand.replaceAll('{{CURRENT_TIMEZONE}}', timezone);
        }
        if (commandFromStore.content.includes('{{CURRENT_WEEKDAY}}')) {
            const weekday = getWeekday();
            textFromCommand = textFromCommand.replaceAll('{{CURRENT_WEEKDAY}}', weekday);
        }
        // At this point, 'textFromCommand' is still HTML, but with placeholders resolved.

        if ($settings?.richTextInput ?? true) {
            // Convert the HTML 'textFromCommand' to a Markdown string
            const markdownToInsert = turndownService.turndown(textFromCommand || ""); // MODIFIED LINE

            const allPromptLines = prompt.split('\n'); // 'prompt' is the current content of MessageInput
            const lastLineWithTrigger = allPromptLines.pop() || '';
            const wordsInLastLine = lastLineWithTrigger.split(' ');
            wordsInLastLine.pop(); 

            let fullPromptPrefix = '';
            if (allPromptLines.length > 0) {
                fullPromptPrefix = allPromptLines.join('\n');
            }
            if (wordsInLastLine.length > 0) {
                if (fullPromptPrefix.length > 0) {
                    fullPromptPrefix += '\n';
                }
                fullPromptPrefix += wordsInLastLine.join(' ');
            }
            fullPromptPrefix = fullPromptPrefix.trimEnd();

            // Combine the Markdown prefix with the newly converted Markdown content
            if (markdownToInsert && markdownToInsert.trim().length > 0) {      // USE markdownToInsert
                if (fullPromptPrefix.length > 0) {
                    prompt = fullPromptPrefix + '\n\n' + markdownToInsert;     // USE markdownToInsert
                } else {
                    prompt = markdownToInsert;                                 // USE markdownToInsert
                }
            } else {
                prompt = fullPromptPrefix;
            }
        } else {
            // For plain text mode, convert HTML to plain text (strips all tags)
            const plainTextToInsert = turndownService.turndown(textFromCommand || ""); // MODIFIED LINE

            const currentInputLines = prompt.split('\n');
            const lastCurrentInputLine = currentInputLines.pop() || '';
            const lastCurrentInputLineWords = lastCurrentInputLine.split(' ');
            lastCurrentInputLineWords.pop();
            // Original code used 'command.content' which was pre-placeholder. Using 'plainTextToInsert' is correct.
            lastCurrentInputLineWords.push(plainTextToInsert); // USE plainTextToInsert
            currentInputLines.push(lastCurrentInputLineWords.join(' '));
            prompt = currentInputLines.join('\n');
        }

        const chatInputContainerElement = document.getElementById('chat-input-container');
        const chatInputElement = document.getElementById('chat-input');

        await tick();
        if (chatInputContainerElement) {
            chatInputContainerElement.scrollTop = chatInputContainerElement.scrollHeight;
        }

        await tick();
        if (chatInputElement) {
            chatInputElement.focus();
            chatInputElement.dispatchEvent(new Event('input'));

            const words = extractCurlyBraceWords(prompt);

            if (words.length > 0) {
                const word = words.at(0);
                // Ensure word is not undefined before accessing properties
                if (word) {
                    const fullPrompt = prompt;
                    prompt = prompt.substring(0, word.endIndex + 1);
                    await tick();
                    chatInputElement.scrollTop = chatInputElement.scrollHeight;
                    prompt = fullPrompt;
                    await tick();
                    chatInputElement.setSelectionRange(word.startIndex, word.endIndex + 1);
                }
            } else {
                chatInputElement.scrollTop = chatInputElement.scrollHeight;
            }
        }
    };
</script>

{#if filteredPrompts.length > 0}
    <div
        id="commands-container"
        class="px-2 mb-2 text-left w-full absolute bottom-0 left-0 right-0 z-10"
    >
        <div class="flex w-full rounded-xl border border-gray-100 dark:border-gray-850">
            <div
                class="max-h-60 flex flex-col w-full rounded-xl bg-white dark:bg-gray-900 dark:text-gray-100"
            >
                <div class="m-1 overflow-y-auto p-1 space-y-0.5 scrollbar-hidden">
                    <!-- Changed loop variable from 'prompt' to 'promptItemFromList' to avoid conflict with exported 'prompt' -->
                    {#each filteredPrompts as promptItemFromList, promptIdx}
                        <button
                            class=" px-3 py-1.5 rounded-xl w-full text-left {promptIdx === selectedPromptIdx
                                ? '  bg-gray-50 dark:bg-gray-850 selected-command-option-button'
                                : ''}"
                            type="button"
                            on:click={() => {
                                confirmPrompt(promptItemFromList); // Pass the specific item
                            }}
                            on:mousemove={() => {
                                selectedPromptIdx = promptIdx;
                            }}
                            on:focus={() => {}}
                        >
                            <div class=" font-medium text-black dark:text-gray-100">
                                {promptItemFromList.command}
                            </div>

                            <div class=" text-xs text-gray-600 dark:text-gray-100">
                                {promptItemFromList.title}
                            </div>
                        </button>
                    {/each}
                </div>

                <div
                    class=" px-2 pt-0.5 pb-1 text-xs text-gray-600 dark:text-gray-100 bg-white dark:bg-gray-900 rounded-b-xl flex items-center space-x-1"
                >
                    <div>
                        <svg
                            xmlns="http://www.w3.org/2000/svg"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke-width="1.5"
                            stroke="currentColor"
                            class="w-3 h-3"
                        >
                            <path
                                stroke-linecap="round"
                                stroke-linejoin="round"
                                d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z"
                            />
                        </svg>
                    </div>

                    <div class="line-clamp-1">
                        {$i18n.t(
                            'Tip: Update multiple variable slots consecutively by pressing the tab key in the chat input after each replacement.'
                        )}
                    </div>
                </div>
            </div>
        </div>
    </div>
{/if}