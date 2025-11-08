<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import { getInterfaceDefaults, setInterfaceDefaults } from '$lib/apis/configs';
	import { config, models, settings, user } from '$lib/stores';

	// Import the same components used in user Interface settings
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Minus from '$lib/components/icons/Minus.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import ManageFloatingActionButtonsModal from '$lib/components/chat/Settings/Interface/ManageFloatingActionButtonsModal.svelte';
	import ManageImageCompressionModal from '$lib/components/chat/Settings/Interface/ManageImageCompressionModal.svelte';

	const i18n = getContext('i18n');

	export let show = false;

	let loading = false;
	let backgroundImageUrl = null;
	let inputFiles = null;
	let filesInputElement;

	// All interface settings with their defaults
	let titleAutoGenerate = true;
	let autoFollowUps = true;
	let autoTags = true;
	let responseAutoCopy = false;
	let widescreenMode = false;
	let splitLargeChunks = false;
	let scrollOnBranchChange = true;
	let userLocation = false;
	let defaultModelId = '';
	let showUsername = false;
	let notificationSound = true;
	let notificationSoundAlways = false;
	let highContrastMode = false;
	let detectArtifacts = true;
	let displayMultiModelResponsesInTabs = false;
	let richTextInput = true;
	let showFormattingToolbar = false;
	let insertPromptAsRichText = false;
	let promptAutocomplete = false;
	let largeTextAsFile = false;
	let insertSuggestionPrompt = false;
	let keepFollowUpPrompts = false;
	let insertFollowUpPrompt = false;
	let regenerateMenu = true;
	let landingPageMode = '';
	let chatBubble = true;
	let chatDirection: 'LTR' | 'RTL' | 'auto' = 'auto';
	let ctrlEnterToSend = false;
	let copyFormatted = false;
	let temporaryChatByDefault = false;
	let chatFadeStreamingText = true;
	let collapseCodeBlocks = false;
	let expandDetails = false;
	let showChatTitleInTab = true;
	let showFloatingActionButtons = true;
	let floatingActionButtons = null;
	let imageCompression = false;
	let imageCompressionSize = { width: '', height: '' };
	let imageCompressionInChannels = true;
	let stylizedPdfExport = true;
	let showUpdateToast = true;
	let showChangelog = true;
	let showEmojiInCall = false;
	let voiceInterruption = false;
	let hapticFeedback = false;
	let webSearch = null;
	let iframeSandboxAllowSameOrigin = false;
	let iframeSandboxAllowForms = false;

	let showManageFloatingActionButtonsModal = false;
	let showManageImageCompressionModal = false;

	const loadDefaults = async () => {
		loading = true;
		try {
			const defaults = await getInterfaceDefaults(localStorage.token);

			// Load all values from defaults or keep system defaults
			titleAutoGenerate = defaults?.title?.auto ?? true;
			autoTags = defaults?.autoTags ?? true;
			autoFollowUps = defaults?.autoFollowUps ?? true;
			highContrastMode = defaults?.highContrastMode ?? false;
			detectArtifacts = defaults?.detectArtifacts ?? true;
			responseAutoCopy = defaults?.responseAutoCopy ?? false;
			showUsername = defaults?.showUsername ?? false;
			showUpdateToast = defaults?.showUpdateToast ?? true;
			showChangelog = defaults?.showChangelog ?? true;
			showEmojiInCall = defaults?.showEmojiInCall ?? false;
			voiceInterruption = defaults?.voiceInterruption ?? false;
			displayMultiModelResponsesInTabs = defaults?.displayMultiModelResponsesInTabs ?? false;
			chatFadeStreamingText = defaults?.chatFadeStreamingText ?? true;
			richTextInput = defaults?.richTextInput ?? true;
			showFormattingToolbar = defaults?.showFormattingToolbar ?? false;
			insertPromptAsRichText = defaults?.insertPromptAsRichText ?? false;
			promptAutocomplete = defaults?.promptAutocomplete ?? false;
			insertSuggestionPrompt = defaults?.insertSuggestionPrompt ?? false;
			keepFollowUpPrompts = defaults?.keepFollowUpPrompts ?? false;
			insertFollowUpPrompt = defaults?.insertFollowUpPrompt ?? false;
			regenerateMenu = defaults?.regenerateMenu ?? true;
			largeTextAsFile = defaults?.largeTextAsFile ?? false;
			copyFormatted = defaults?.copyFormatted ?? false;
			collapseCodeBlocks = defaults?.collapseCodeBlocks ?? false;
			expandDetails = defaults?.expandDetails ?? false;
			landingPageMode = defaults?.landingPageMode ?? '';
			chatBubble = defaults?.chatBubble ?? true;
			widescreenMode = defaults?.widescreenMode ?? false;
			splitLargeChunks = defaults?.splitLargeChunks ?? false;
			scrollOnBranchChange = defaults?.scrollOnBranchChange ?? true;
			temporaryChatByDefault = defaults?.temporaryChatByDefault ?? false;
			chatDirection = defaults?.chatDirection ?? 'auto';
			userLocation = defaults?.userLocation ?? false;
			showChatTitleInTab = defaults?.showChatTitleInTab ?? true;
			notificationSound = defaults?.notificationSound ?? true;
			notificationSoundAlways = defaults?.notificationSoundAlways ?? false;
			iframeSandboxAllowSameOrigin = defaults?.iframeSandboxAllowSameOrigin ?? false;
			iframeSandboxAllowForms = defaults?.iframeSandboxAllowForms ?? false;
			stylizedPdfExport = defaults?.stylizedPdfExport ?? true;
			hapticFeedback = defaults?.hapticFeedback ?? false;
			ctrlEnterToSend = defaults?.ctrlEnterToSend ?? false;
			showFloatingActionButtons = defaults?.showFloatingActionButtons ?? true;
			floatingActionButtons = defaults?.floatingActionButtons ?? null;
			imageCompression = defaults?.imageCompression ?? false;
			imageCompressionSize = defaults?.imageCompressionSize ?? { width: '', height: '' };
			imageCompressionInChannels = defaults?.imageCompressionInChannels ?? true;
			defaultModelId = defaults?.models?.at(0) ?? '';
			backgroundImageUrl = defaults?.backgroundImageUrl ?? null;
			webSearch = defaults?.webSearch ?? null;
		} catch (error) {
			console.error('Error loading interface defaults:', error);
			toast.error($i18n.t('Failed to load interface defaults'));
		} finally {
			loading = false;
		}
	};

	const saveDefaults = async () => {
		loading = true;
		try {
			const defaults = {
				title: { auto: titleAutoGenerate },
				autoTags,
				autoFollowUps,
				highContrastMode,
				detectArtifacts,
				responseAutoCopy,
				showUsername,
				showUpdateToast,
				showChangelog,
				showEmojiInCall,
				voiceInterruption,
				displayMultiModelResponsesInTabs,
				chatFadeStreamingText,
				richTextInput,
				showFormattingToolbar,
				insertPromptAsRichText,
				promptAutocomplete,
				insertSuggestionPrompt,
				keepFollowUpPrompts,
				insertFollowUpPrompt,
				regenerateMenu,
				largeTextAsFile,
				copyFormatted,
				collapseCodeBlocks,
				expandDetails,
				landingPageMode,
				chatBubble,
				widescreenMode,
				splitLargeChunks,
				scrollOnBranchChange,
				temporaryChatByDefault,
				chatDirection,
				userLocation,
				showChatTitleInTab,
				notificationSound,
				notificationSoundAlways,
				iframeSandboxAllowSameOrigin,
				iframeSandboxAllowForms,
				stylizedPdfExport,
				hapticFeedback,
				ctrlEnterToSend,
				showFloatingActionButtons,
				floatingActionButtons,
				imageCompression,
				imageCompressionSize,
				imageCompressionInChannels,
				models: defaultModelId ? [defaultModelId] : [],
				backgroundImageUrl,
				webSearch
			};

			await setInterfaceDefaults(localStorage.token, defaults);
			toast.success($i18n.t('Interface defaults saved successfully'));
			show = false;
		} catch (error) {
			console.error('Error saving interface defaults:', error);
			toast.error($i18n.t('Failed to save interface defaults'));
		} finally {
			loading = false;
		}
	};

	const toggleChangeChatDirection = () => {
		if (chatDirection === 'auto') {
			chatDirection = 'LTR';
		} else if (chatDirection === 'LTR') {
			chatDirection = 'RTL';
		} else if (chatDirection === 'RTL') {
			chatDirection = 'auto';
		}
	};

	const toggleLandingPageMode = () => {
		landingPageMode = landingPageMode === '' ? 'chat' : '';
	};

	const toggleWebSearch = () => {
		webSearch = webSearch === null ? 'always' : null;
	};

	$: if (show) {
		loadDefaults();
	}
</script>

<ManageFloatingActionButtonsModal
	bind:show={showManageFloatingActionButtonsModal}
	{floatingActionButtons}
	onSave={(buttons) => {
		floatingActionButtons = buttons;
	}}
/>

<ManageImageCompressionModal
	bind:show={showManageImageCompressionModal}
	size={imageCompressionSize}
	onSave={(size) => {
		imageCompressionSize = size;
	}}
/>

<Modal size="xl" bind:show>
	<div class="text-gray-700 dark:text-gray-100">
		<div class="flex justify-between dark:text-gray-300 px-4 md:px-4.5 pt-4.5 pb-2.5">
			<div class="text-lg font-medium self-center">{$i18n.t('Configure Global Interface Defaults')}</div>
			<button
				aria-label={$i18n.t('Close modal')}
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

		<div class="text-xs text-gray-500 dark:text-gray-400 px-4 pb-3">
			{$i18n.t('These settings will be used as defaults for all users who haven\'t customized their interface settings.')}
		</div>

		<form
			class="flex flex-col space-y-3 text-sm px-4 pb-4"
			on:submit|preventDefault={saveDefaults}
		>
			<input
				bind:this={filesInputElement}
				bind:files={inputFiles}
				type="file"
				hidden
				accept="image/*"
				on:change={() => {
					let reader = new FileReader();
					reader.onload = (event) => {
						backgroundImageUrl = `${event.target.result}`;
					};

					if (
						inputFiles &&
						inputFiles.length > 0 &&
						['image/gif', 'image/webp', 'image/jpeg', 'image/png'].includes(inputFiles[0]['type'])
					) {
						reader.readAsDataURL(inputFiles[0]);
					} else {
						console.log(`Unsupported File Type '${inputFiles[0]['type']}'.`);
						inputFiles = null;
					}
				}}
			/>

			<div class="space-y-3 overflow-y-scroll max-h-[28rem] md:max-h-[32rem]">
				<div>
					<h1 class="mb-2 text-sm font-medium">{$i18n.t('UI')}</h1>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="high-contrast-mode-label" class="self-center text-xs">
								{$i18n.t('High Contrast Mode')} ({$i18n.t('Beta')})
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="high-contrast-mode-label"
									tooltip={true}
									bind:state={highContrastMode}
								/>
							</div>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="use-chat-title-as-tab-title-label" class="self-center text-xs">
								{$i18n.t('Display chat title in tab')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="use-chat-title-as-tab-title-label"
									tooltip={true}
									bind:state={showChatTitleInTab}
								/>
							</div>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="notification-sound-label" class="self-center text-xs">
								{$i18n.t('Notification Sound')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="notification-sound-label"
									tooltip={true}
									bind:state={notificationSound}
								/>
							</div>
						</div>
					</div>

					{#if notificationSound}
						<div>
							<div class="py-0.5 flex w-full justify-between">
								<div id="play-notification-sound-label" class="self-center text-xs">
									{$i18n.t('Always Play Notification Sound')}
								</div>
								<div class="flex items-center gap-2 p-1">
									<Switch
										ariaLabelledbyId="play-notification-sound-label"
										tooltip={true}
										bind:state={notificationSoundAlways}
									/>
								</div>
							</div>
						</div>
					{/if}

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="copy-formatted-label" class="self-center text-xs">
								{$i18n.t('Copy Formatted Text')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="copy-formatted-label"
									tooltip={true}
									bind:state={copyFormatted}
								/>
							</div>
						</div>
					</div>

					<div class="my-2 text-sm font-medium">{$i18n.t('Chat')}</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="chat-direction-label" class="self-center text-xs">
								{$i18n.t('Chat direction')}
							</div>
							<button
								aria-labelledby="chat-direction-label chat-direction-mode"
								class="p-1 px-3 text-xs flex rounded-sm transition"
								on:click={toggleChangeChatDirection}
								type="button"
							>
								<span class="ml-2 self-center" id="chat-direction-mode">
									{chatDirection === 'LTR'
										? $i18n.t('LTR')
										: chatDirection === 'RTL'
											? $i18n.t('RTL')
											: $i18n.t('Auto')}
								</span>
							</button>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="landing-page-mode-label" class="self-center text-xs">
								{$i18n.t('Landing Page Mode')}
							</div>
							<button
								aria-labelledby="landing-page-mode-label"
								class="p-1 px-3 text-xs flex rounded-sm transition"
								on:click={toggleLandingPageMode}
								type="button"
							>
								<span class="ml-2 self-center">
									{landingPageMode === '' ? $i18n.t('Default') : $i18n.t('Chat')}
								</span>
							</button>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="chat-background-label" class="self-center text-xs">
								{$i18n.t('Chat Background Image')}
							</div>
							<button
								aria-labelledby="chat-background-label"
								class="p-1 px-3 text-xs flex rounded-sm transition"
								on:click={() => {
									if (backgroundImageUrl !== null) {
										backgroundImageUrl = null;
									} else {
										filesInputElement.click();
									}
								}}
								type="button"
							>
								<span class="ml-2 self-center">
									{backgroundImageUrl !== null ? $i18n.t('Reset') : $i18n.t('Upload')}
								</span>
							</button>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="chat-bubble-ui-label" class="self-center text-xs">
								{$i18n.t('Chat Bubble UI')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									tooltip={true}
									ariaLabelledbyId="chat-bubble-ui-label"
									bind:state={chatBubble}
								/>
							</div>
						</div>
					</div>

					{#if !chatBubble}
						<div>
							<div class="py-0.5 flex w-full justify-between">
								<div id="chat-bubble-username-label" class="self-center text-xs">
									{$i18n.t('Display the username instead of You in the Chat')}
								</div>
								<div class="flex items-center gap-2 p-1">
									<Switch
										ariaLabelledbyId="chat-bubble-username-label"
										tooltip={true}
										bind:state={showUsername}
									/>
								</div>
							</div>
						</div>
					{/if}

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="widescreen-mode-label" class="self-center text-xs">
								{$i18n.t('Widescreen Mode')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="widescreen-mode-label"
									tooltip={true}
									bind:state={widescreenMode}
								/>
							</div>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="temp-chat-default-label" class="self-center text-xs">
								{$i18n.t('Temporary Chat by Default')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="temp-chat-default-label"
									tooltip={true}
									bind:state={temporaryChatByDefault}
								/>
							</div>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="fade-streaming-label" class="self-center text-xs">
								{$i18n.t('Fade Effect for Streaming Text')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="fade-streaming-label"
									tooltip={true}
									bind:state={chatFadeStreamingText}
								/>
							</div>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="auto-generation-label" class="self-center text-xs">
								{$i18n.t('Title Auto-Generation')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="auto-generation-label"
									tooltip={true}
									bind:state={titleAutoGenerate}
								/>
							</div>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div class="self-center text-xs" id="follow-up-auto-generation-label">
								{$i18n.t('Follow-Up Auto-Generation')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="follow-up-auto-generation-label"
									tooltip={true}
									bind:state={autoFollowUps}
								/>
							</div>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="chat-tags-label" class="self-center text-xs">
								{$i18n.t('Chat Tags Auto-Generation')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									ariaLabelledbyId="chat-tags-label"
									tooltip={true}
									bind:state={autoTags}
								/>
							</div>
						</div>
					</div>

					<!-- Continue with more settings in next part... -->
					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="rich-input-label" class="self-center text-xs">
								{$i18n.t('Rich Text Input for Chat')}
							</div>
							<div class="flex items-center gap-2 p-1">
								<Switch
									tooltip={true}
									ariaLabelledbyId="rich-input-label"
									bind:state={richTextInput}
								/>
							</div>
						</div>
					</div>

					<div>
						<div class="py-0.5 flex w-full justify-between">
							<div id="web-search-in-chat-label" class="self-center text-xs">
								{$i18n.t('Web Search in Chat')}
							</div>
							<button
								aria-labelledby="web-search-in-chat-label"
								class="p-1 px-3 text-xs flex rounded-sm transition"
								on:click={toggleWebSearch}
								type="button"
							>
								<span class="ml-2 self-center">
									{webSearch === 'always' ? $i18n.t('Always') : $i18n.t('Default')}
								</span>
							</button>
						</div>
					</div>
				</div>
			</div>

			<div class="flex justify-end text-sm font-medium gap-2 pt-2">
				<button
					class="px-3.5 py-1.5 text-sm font-medium bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 transition rounded-full"
					type="button"
					on:click={() => show = false}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
					type="submit"
					disabled={loading}
				>
					{loading ? $i18n.t('Saving...') : $i18n.t('Save Defaults')}
				</button>
			</div>
		</form>
	</div>
</Modal>
