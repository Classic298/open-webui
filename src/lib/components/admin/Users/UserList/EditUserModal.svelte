<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { createEventDispatcher } from 'svelte';
	import { onMount, getContext } from 'svelte';

	import { updateUserById } from '$lib/apis/users';

	import Modal from '$lib/components/common/Modal.svelte';
	import Switch from '$lib/components/common/Switch.svelte'; // Import Switch
	import Tooltip from '$lib/components/common/Tooltip.svelte'; // Import Tooltip for consistency
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();
	dayjs.extend(localizedFormat);

	export let show = false;
	export let selectedUser;
	export let sessionUser;

	let _user = {
		profile_image_url: '',
		role: 'pending',
		name: '',
		email: '',
		password: '',
		settings: {
			// Ensure settings structure exists
			permissions: {
				features: {
					video_generation: false // Default to false if not present
				}
			}
		}
	};

	const submitHandler = async () => {
		// Ensure all parts of _user are correctly structured before sending
		const payload = {
			role: _user.role,
			name: _user.name,
			email: _user.email,
			profile_image_url: _user.profile_image_url,
			...(typeof _user.password === 'string' && _user.password !== '' && { password: _user.password }),
			settings: {
				...(selectedUser.settings ?? {}), // Preserve other settings
				permissions: {
					...((selectedUser.settings?.permissions ?? {}).features // Preserve other feature permissions
						? { features: { ...(selectedUser.settings.permissions.features ?? {}) } }
						: { features: {} }), // Ensure features object exists
					// Apply our specific changes
					features: {
						...(_user.settings?.permissions?.features ?? {}),
						video_generation: _user.settings?.permissions?.features?.video_generation ?? false
					}
				}
			}
		};

		// Clean up permissions if features is empty
		if (Object.keys(payload.settings.permissions.features).length === 0) {
			delete payload.settings.permissions.features;
		}
		if (Object.keys(payload.settings.permissions).length === 0) {
			delete payload.settings.permissions;
		}


		const res = await updateUserById(localStorage.token, selectedUser.id, payload).catch(
			(error) => {
				toast.error(`${error}`);
			}
		);

		if (res) {
			dispatch('save');
			show = false;
		}
	};

	onMount(() => {
		if (selectedUser) {
			_user = JSON.parse(JSON.stringify(selectedUser)); // Deep copy
			_user.password = '';

			// Ensure the path to video_generation permission exists
			if (!_user.settings) {
				_user.settings = {};
			}
			if (!_user.settings.permissions) {
				_user.settings.permissions = {};
			}
			if (!_user.settings.permissions.features) {
				_user.settings.permissions.features = {};
			}
			if (typeof _user.settings.permissions.features.video_generation !== 'boolean') {
				// Initialize from global default or false if not found in selectedUser's specific settings
				// This part might need refinement based on how global defaults are propagated to user settings upon creation
				_user.settings.permissions.features.video_generation =
					selectedUser.settings?.permissions?.features?.video_generation ?? false;
			}
		}
	});
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class=" text-lg font-medium self-center">{$i18n.t('Edit User')}</div>
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

		<div class="flex flex-col md:flex-row w-full md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit|preventDefault={() => {
						submitHandler();
					}}
				>
					<div class=" flex items-center rounded-md px-5 py-2 w-full">
						<div class=" self-center mr-5">
							<img
								src={selectedUser.profile_image_url}
								class=" max-w-[55px] object-cover rounded-full"
								alt="User profile"
							/>
						</div>

						<div>
							<div class=" self-center capitalize font-semibold">{selectedUser.name}</div>

							<div class="text-xs text-gray-500">
								{$i18n.t('Created at')}
								{dayjs(selectedUser.created_at * 1000).format('LL')}
							</div>
						</div>
					</div>

					<div class=" px-5 pt-3 pb-5">
						<div class=" flex flex-col space-y-1.5">
							<div class="flex flex-col w-full">
								<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Role')}</div>

								<div class="flex-1">
									<select
										class="w-full dark:bg-gray-900 text-sm bg-transparent disabled:text-gray-500 dark:disabled:text-gray-500 outline-hidden"
										bind:value={_user.role}
										disabled={_user.id == sessionUser.id}
										required
									>
										<option value="admin">{$i18n.t('Admin')}</option>
										<option value="user">{$i18n.t('User')}</option>
										<option value="pending">{$i18n.t('Pending')}</option>
									</select>
								</div>
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Email')}</div>

								<div class="flex-1">
									<input
										class="w-full text-sm bg-transparent disabled:text-gray-500 dark:disabled:text-gray-500 outline-hidden"
										type="email"
										bind:value={_user.email}
										placeholder={$i18n.t('Enter Your Email')}
										autocomplete="off"
										required
									/>
								</div>
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Name')}</div>

								<div class="flex-1">
									<input
										class="w-full text-sm bg-transparent outline-hidden"
										type="text"
										bind:value={_user.name}
										placeholder={$i18n.t('Enter Your Name')}
										autocomplete="off"
										required
									/>
								</div>
							</div>

							<div class="flex flex-col w-full">
								<div class=" mb-1 text-xs text-gray-500">{$i18n.t('New Password')}</div>

								<div class="flex-1">
									<input
										class="w-full text-sm bg-transparent outline-hidden"
										type="password"
										placeholder={$i18n.t('Enter New Password')}
										bind:value={_user.password}
										autocomplete="new-password"
									/>
								</div>
							</div>

							<!-- Video Generation Permission Toggle -->
							<div class="border-t border-gray-200 dark:border-gray-700 pt-3 mt-3">
								<div class="text-sm font-medium mb-2">{$i18n.t('Feature Permissions')}</div>
								<div class="flex justify-between items-center py-1">
									<div class="text-xs text-gray-600 dark:text-gray-400">
										{$i18n.t('Enable Video Generation')}
										<Tooltip
											content={$i18n.t(
												'Allow this user to access the video generation feature.'
											)}
										/>
									</div>
									<Switch
										bind:state={_user.settings.permissions.features.video_generation}
										on:change={() => {
											// console.log('Video generation permission toggled:', _user.settings.permissions.features.video_generation);
										}}
									/>
								</div>
							</div>
							<!-- End Video Generation Permission Toggle -->
						</div>

						<div class="flex justify-end pt-3 text-sm font-medium">
							<button
								class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center"
								type="submit"
							>
								{$i18n.t('Save')}
							</button>
						</div>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>

<style>
	input::-webkit-outer-spin-button,
	input::-webkit-inner-spin-button {
		/* display: none; <- Crashes Chrome on hover */
		-webkit-appearance: none;
		margin: 0; /* <-- Apparently some margin are still there even though it's hidden */
	}

	.tabs::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.tabs {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}

	input[type='number'] {
		-moz-appearance: textfield; /* Firefox */
	}
</style>
