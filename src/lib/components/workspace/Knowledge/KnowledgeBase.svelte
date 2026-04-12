<script lang="ts">
	import Fuse from 'fuse.js';
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';

	import { onMount, getContext, onDestroy, tick } from 'svelte';
	const i18n = getContext('i18n');

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		mobile,
		showSidebar,
		knowledge as _knowledge,
		config,
		user,
		settings
	} from '$lib/stores';

	import {
		updateFileDataContentById,
		uploadFile,
		deleteFileById,
		getFileById
	} from '$lib/apis/files';
	import {
		addFileToKnowledgeById,
		getKnowledgeById,
		removeFileFromKnowledgeById,
		resetKnowledgeById,
		updateFileFromKnowledgeById,
		updateKnowledgeById,
		updateKnowledgeAccessGrants,
		searchKnowledgeFilesById,
		compareFilesForSync,
		uploadAndReplaceFile,
		type FileSyncCompareItem
	} from '$lib/apis/knowledge';
	import { processWeb, processYoutubeVideo } from '$lib/apis/retrieval';

	import { blobToFile, isYoutubeUrl } from '$lib/utils';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Files from './KnowledgeBase/Files.svelte';
	import AddFilesPlaceholder from '$lib/components/AddFilesPlaceholder.svelte';

	import AddContentMenu from './KnowledgeBase/AddContentMenu.svelte';
	import AddTextContentModal from './KnowledgeBase/AddTextContentModal.svelte';

	import SyncConfirmDialog from '../../common/ConfirmDialog.svelte';
	import Drawer from '$lib/components/common/Drawer.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import FilesOverlay from '$lib/components/chat/MessageInput/FilesOverlay.svelte';
	import DropdownOptions from '$lib/components/common/DropdownOptions.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import AttachWebpageModal from '$lib/components/chat/MessageInput/AttachWebpageModal.svelte';

	let largeScreen = true;

	let pane;
	let showSidepanel = true;

	let showAddWebpageModal = false;
	let showAddTextContentModal = false;

	let showSyncConfirmModal = false;
	let showAccessControlModal = false;

	let minSize = 0;
	type Knowledge = {
		id: string;
		name: string;
		description: string;
		data: {
			file_ids: string[];
		};
		files: any[];
		access_grants?: any[];
		write_access?: boolean;
	};

	let id = null;
	let knowledge: Knowledge | null = null;
	let knowledgeId = null;

	let selectedFileId = null;
	let selectedFile = null;
	let selectedFileContent = '';

	let inputFiles = null;

	let query = '';
	let searchDebounceTimer: ReturnType<typeof setTimeout>;

	let viewOption = null;
	let sortKey = null;
	let direction = null;

	let currentPage = 1;
	let fileItems = null;
	let fileItemsTotal = null;

	const reset = () => {
		currentPage = 1;
	};

	const init = async () => {
		reset();
		await getItemsPage();
	};

	// Debounce only query changes
	$: if (query !== undefined) {
		clearTimeout(searchDebounceTimer);

		searchDebounceTimer = setTimeout(() => {
			getItemsPage();
		}, 300);
	}

	// Immediate response to filter/pagination changes
	$: if (
		knowledgeId !== null &&
		viewOption !== undefined &&
		sortKey !== undefined &&
		direction !== undefined &&
		currentPage !== undefined
	) {
		getItemsPage();
	}

	$: if (
		query !== undefined &&
		viewOption !== undefined &&
		sortKey !== undefined &&
		direction !== undefined
	) {
		reset();
	}

	const getItemsPage = async () => {
		if (knowledgeId === null) return;

		fileItems = null;
		fileItemsTotal = null;

		if (sortKey === null) {
			direction = null;
		}

		const res = await searchKnowledgeFilesById(
			localStorage.token,
			knowledge.id,
			query,
			viewOption,
			sortKey,
			direction,
			currentPage
		).catch(() => {
			return null;
		});

		if (res) {
			fileItems = res.items;
			fileItemsTotal = res.total;
		}
		return res;
	};

	const fileSelectHandler = async (file) => {
		try {
			selectedFile = file;
			selectedFileContent = selectedFile?.data?.content || '';
		} catch (e) {
			toast.error($i18n.t('Failed to load file content.'));
		}
	};

	const createFileFromText = (name, content) => {
		const blob = new Blob([content], { type: 'text/plain' });
		const file = blobToFile(blob, `${name}.txt`);

		console.log(file);
		return file;
	};

	const uploadWeb = async (urls) => {
		if (!Array.isArray(urls)) {
			urls = [urls];
		}

		const newFileItems = urls.map((url) => ({
			type: 'file',
			file: '',
			id: null,
			url: url,
			name: url,
			size: null,
			status: 'uploading',
			error: '',
			itemId: uuidv4()
		}));

		// Display all items at once
		fileItems = [...newFileItems, ...(fileItems ?? [])];

		for (const fileItem of newFileItems) {
			try {
				console.log(fileItem);
				const res = await processWeb(localStorage.token, '', fileItem.url, false).catch((e) => {
					console.error('Error processing web URL:', e);
					return null;
				});

				if (res) {
					console.log(res);
					const file = createFileFromText(
						// Use URL as filename, sanitized
						fileItem.url
							.replace(/[^a-z0-9]/gi, '_')
							.toLowerCase()
							.slice(0, 50),
						res.content
					);

					const uploadedFile = await uploadFile(localStorage.token, file).catch((e) => {
						toast.error(`${e}`);
						return null;
					});

					if (uploadedFile) {
						console.log(uploadedFile);
						fileItems = fileItems.map((item) => {
							if (item.itemId === fileItem.itemId) {
								item.id = uploadedFile.id;
							}
							return item;
						});

						if (uploadedFile.error) {
							console.warn('File upload warning:', uploadedFile.error);
							toast.warning(uploadedFile.error);
							fileItems = fileItems.filter((file) => file.id !== uploadedFile.id);
						} else {
							await addFileHandler(uploadedFile.id);
						}
					} else {
						toast.error($i18n.t('Failed to upload file.'));
					}
				} else {
					// remove the item from fileItems
					fileItems = fileItems.filter((item) => item.itemId !== fileItem.itemId);
					toast.error($i18n.t('Failed to process URL: {{url}}', { url: fileItem.url }));
				}
			} catch (e) {
				// remove the item from fileItems
				fileItems = fileItems.filter((item) => item.itemId !== fileItem.itemId);
				toast.error(`${e}`);
			}
		}
	};

	// Returns true only if the file was uploaded AND added to the KB without
	// any error surfaced. Callers (notably the directory sync flow) rely on
	// this boolean to distinguish genuine successes from empty-file / size-
	// limit / upload / add failures that this handler otherwise swallows via
	// toasts.
	const uploadFileHandler = async (file): Promise<boolean> => {
		console.log(file);

		const fileItem = {
			type: 'file',
			file: '',
			id: null,
			url: '',
			name: file.name,
			size: file.size,
			status: 'uploading',
			error: '',
			itemId: uuidv4()
		};

		if (fileItem.size == 0) {
			toast.error($i18n.t('You cannot upload an empty file.'));
			return false;
		}

		if (
			($config?.file?.max_size ?? null) !== null &&
			file.size > ($config?.file?.max_size ?? 0) * 1024 * 1024
		) {
			console.log('File exceeds max size limit:', {
				fileSize: file.size,
				maxSize: ($config?.file?.max_size ?? 0) * 1024 * 1024
			});
			toast.error(
				$i18n.t(`File size should not exceed {{maxSize}} MB.`, {
					maxSize: $config?.file?.max_size
				})
			);
			return false;
		}

		fileItems = [fileItem, ...(fileItems ?? [])];
		try {
			let metadata = {
				knowledge_id: knowledge.id,
				// If the file is an audio file, provide the language for STT.
				...((file.type.startsWith('audio/') || file.type.startsWith('video/')) &&
				$settings?.audio?.stt?.language
					? {
							language: $settings?.audio?.stt?.language
						}
					: {})
			};

			const uploadedFile = await uploadFile(localStorage.token, file, metadata).catch((e) => {
				toast.error(`${e}`);
				return null;
			});

			if (uploadedFile) {
				console.log(uploadedFile);
				fileItems = fileItems.map((item) => {
					if (item.itemId === fileItem.itemId) {
						item.id = uploadedFile.id;
					}
					return item;
				});

				if (uploadedFile.error) {
					console.warn('File upload warning:', uploadedFile.error);
					toast.warning(uploadedFile.error);
					fileItems = fileItems.filter((file) => file.id !== uploadedFile.id);
					return false;
				} else {
					const added = await addFileHandler(uploadedFile.id);
					return Boolean(added);
				}
			} else {
				toast.error($i18n.t('Failed to upload file.'));
				return false;
			}
		} catch (e) {
			toast.error(`${e}`);
			return false;
		}
	};

	// Upload directory handler - uses shared utility
	const uploadDirectoryHandler = async () => {
	    try {
	        const files = await collectDirectoryFiles();
	
	        if (files.length === 0) {
	            toast.info($i18n.t('No files found in directory'));
	            return;
	        }
	
	        const totalFiles = files.length;
	        let uploadedFiles = 0;
	
	        const updateProgress = () => {
	            const percentage = (uploadedFiles / totalFiles) * 100;
	            toast.info(
	                $i18n.t('Upload Progress: {{uploadedFiles}}/{{totalFiles}} ({{percentage}}%)', {
	                    uploadedFiles,
	                    totalFiles,
	                    percentage: percentage.toFixed(2)
	                })
	            );
	        };
	
	        updateProgress();
	
	        for (const { file } of files) {
	            await uploadFileHandler(file);
	            uploadedFiles++;
	            updateProgress();
	        }
	    } catch (error) {
	        handleUploadError(error);
	    }
	};

	// Helper function to check if a path contains hidden folders
	const hasHiddenFolder = (path) => {
		return path.split('/').some((part) => part.startsWith('.'));
	};

	// SubtleCrypto.digest has no streaming API, so hashing requires loading
	// the full file into an ArrayBuffer. For very large files that can freeze
	// or crash the tab. Skip hashing above this threshold and let the
	// backend fall back to size-based comparison (already supported for
	// legacy files without a stored hash).
	const MAX_BROWSER_HASH_BYTES = 100 * 1024 * 1024; // 100 MB

	// Calculate SHA-256 hash of a file in the browser. Returns '' when the
	// file exceeds the in-memory hashing threshold.
	const calculateFileHash = async (file: File): Promise<string> => {
		if (file.size > MAX_BROWSER_HASH_BYTES) {
			return '';
		}
		const buffer = await file.arrayBuffer();
		const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
		return Array.from(new Uint8Array(hashBuffer))
			.map((b) => b.toString(16).padStart(2, '0'))
			.join('');
	};
	
	// Shared type for collected files
	type CollectedFile = {
	    file: File;
	    path: string;
	    size: number;
	    hash?: string;
	};
	
	// Shared utility to collect all files from a directory
	const collectDirectoryFiles = async (options?: { withHashes?: boolean }): Promise<CollectedFile[]> => {
	    const withHashes = options?.withHashes ?? false;
	    const files: CollectedFile[] = [];
	
	    const isFileSystemAccessSupported = 'showDirectoryPicker' in window;
	
	    if (isFileSystemAccessSupported) {
	        const dirHandle = await window.showDirectoryPicker();
	
	        async function processDirectory(dirHandle: FileSystemDirectoryHandle, path = '') {
	            for await (const entry of dirHandle.values()) {
	                if (entry.name.startsWith('.')) continue;
	
	                const entryPath = path ? `${path}/${entry.name}` : entry.name;
	
	                if (hasHiddenFolder(entryPath)) continue;
	
	                if (entry.kind === 'file') {
	                    const file = await (entry as FileSystemFileHandle).getFile();
	                    const fileWithPath = new File([file], entryPath, { type: file.type });
	
	                    const collectedFile: CollectedFile = {
	                        file: fileWithPath,
	                        path: entryPath,
	                        size: file.size
	                    };
	
	                    if (withHashes) {
	                        collectedFile.hash = await calculateFileHash(file);
	                    }
	
	                    files.push(collectedFile);
	                } else if (entry.kind === 'directory') {
	                    await processDirectory(entry as FileSystemDirectoryHandle, entryPath);
	                }
	            }
	        }
	
	        await processDirectory(dirHandle);
	    } else {
	        // Firefox fallback
	        await new Promise<void>((resolve, reject) => {
	            const input = document.createElement('input');
	            input.type = 'file';
	            input.webkitdirectory = true;
	            input.directory = true;
	            input.multiple = true;
	            input.style.display = 'none';
	
	            document.body.appendChild(input);
	
	            input.onchange = async () => {
	                try {
	                    const inputFiles = Array.from(input.files || []).filter(
	                        (file) => !hasHiddenFolder(file.webkitRelativePath) && !file.name.startsWith('.')
	                    );
	
	                    for (const file of inputFiles) {
	                        const relativePath = file.webkitRelativePath || file.name;
	                        const fileWithPath = new File([file], relativePath, { type: file.type });
	
	                        const collectedFile: CollectedFile = {
	                            file: fileWithPath,
	                            path: relativePath,
	                            size: file.size
	                        };
	
	                        if (withHashes) {
	                            collectedFile.hash = await calculateFileHash(file);
	                        }
	
	                        files.push(collectedFile);
	                    }
	
	                    document.body.removeChild(input);
	                    resolve();
	                } catch (error) {
	                    document.body.removeChild(input);
	                    reject(error);
	                }
	            };
	
	            input.onerror = (error) => {
	                document.body.removeChild(input);
	                reject(error);
	            };
	
	            input.click();
	        });
	    }
	
	    return files;
	};

	// Error handler
	const handleUploadError = (error) => {
		if (error.name === 'AbortError') {
			toast.info($i18n.t('Directory selection was cancelled'));
		} else {
			toast.error($i18n.t('Error accessing directory'));
			console.error('Directory access error:', error);
		}
	};

	// Smart sync: only upload changed files, delete removed files
	const syncDirectoryHandler = async () => {
	    // Collect files from the picker first. Errors here are directory/picker
	    // issues (cancelled, permission denied) — route through handleUploadError.
	    let directoryFiles;
	    try {
	        toast.info($i18n.t('Scanning directory...'));
	        directoryFiles = await collectDirectoryFiles({ withHashes: true });
	    } catch (error) {
	        handleUploadError(error);
	        return;
	    }

	    if (directoryFiles.length === 0) {
	        toast.info($i18n.t('No files found in directory'));
	        return;
	    }

	    // Warn about files that skipped hashing due to the in-memory hash
	    // threshold. Those fall back to size-only comparison on the server,
	    // so a content change that keeps the same byte size will NOT be
	    // detected as changed. Surface this up front so the user can make
	    // an informed decision (and knows which files to re-upload manually
	    // if they suspect a silent-change case).
	    const unhashed = directoryFiles.filter((f) => !f.hash);
	    if (unhashed.length > 0) {
	        console.warn(
	            'Sync: files skipped browser hashing (size-only comparison will be used):',
	            unhashed.map((f) => f.path)
	        );
	        toast.warning(
	            $i18n.t(
	                '{{count}} file(s) exceed the browser hash limit and will be compared by size only. Content changes that keep the same size will not be detected.',
	                { count: unhashed.length }
	            )
	        );
	    }

	    // Everything below is API/business logic. Surface the server's detail
	    // message so users can diagnose compare/upload/remove failures instead
	    // of seeing a misleading "Error accessing directory" toast.
	    try {
	        toast.info(
	            $i18n.t('Found {{count}} files, comparing with knowledge base...', {
	                count: directoryFiles.length
	            })
	        );

	        // Prepare comparison data
	        const compareData: FileSyncCompareItem[] = directoryFiles.map((f) => ({
	            file_path: f.path,
	            file_hash: f.hash!,
	            size: f.size
	        }));
	
	        // Call compare endpoint to get sync plan
	        const comparison = await compareFilesForSync(localStorage.token, id, compareData);
	
	        if (!comparison) {
	            toast.error($i18n.t('Failed to compare files'));
	            return;
	        }
	
	        const { new_files, changed_files, removed_file_ids, unchanged } = comparison;

	        // Build a path -> collected-file map once so per-file lookups in
	        // the new/changed loops are O(1) instead of O(n). Also gives us
	        // one place to detect server-planned paths the client can't
	        // resolve — which should not happen but we guard defensively so
	        // the sync summary can't over-report completion.
	        const filesByPath = new Map(directoryFiles.map((f) => [f.path, f]));

	        const totalToProcess = new_files.length + changed_files.length;
	        let processedCount = 0;
	
	        // STEP 1: Delete removed files FIRST.
	        // If a file was incorrectly classified as both "new" and "removed"
	        // (due to filename matching issues), deleting first allows the
	        // subsequent upload to succeed.
	        // Use removeFileFromKnowledgeById (the KB-scoped /knowledge/{id}/
	        // file/remove route). The backend endpoint now hard-deletes the
	        // file record, storage blob, and per-file vector collection only
	        // when no other knowledge base references the file — otherwise it
	        // degrades to a scoped unlink, so syncing KB-A never wipes a file
	        // that is also attached to KB-B. Global DELETE /files/{id} would
	        // not have that safeguard.
	        let removedSucceeded = 0;
	        let removedFailed = 0;
	        if (removed_file_ids.length > 0) {
	            toast.info(
	                $i18n.t('Removing {{count}} deleted files...', {
	                    count: removed_file_ids.length
	                })
	            );
	            for (const fileId of removed_file_ids) {
	                try {
	                    const res = await removeFileFromKnowledgeById(
	                        localStorage.token,
	                        id,
	                        fileId
	                    );
	                    if (res) {
	                        removedSucceeded++;
	                    } else {
	                        // API wrapper returned null without throwing — treat
	                        // as a silent failure so the user isn't told we
	                        // removed something we didn't.
	                        removedFailed++;
	                    }
	                } catch (removeErr) {
	                    removedFailed++;
	                    console.error('Delete failed for', fileId, removeErr);
	                    const detail =
	                        typeof removeErr === 'string'
	                            ? removeErr
	                            : (removeErr?.detail ?? removeErr?.message ?? 'unknown error');
	                    toast.error(
	                        $i18n.t('Failed to remove file: {{detail}}', { detail })
	                    );
	                }
	            }
	        }

	        // STEP 2: Upload new files. uploadFileHandler swallows per-file
	        // errors via toasts and returns a boolean; track successes so the
	        // final summary doesn't over-report completion when uploads fail.
	        let newSucceeded = 0;
	        let newFailed = 0;
	        for (const filePath of new_files) {
	            const fileData = filesByPath.get(filePath);
	            if (!fileData) {
	                // Server planned a new-file upload for a path we can't
	                // map back to a collected file. Count as a failure and
	                // surface it so the sync summary and the user both see
	                // that the file wasn't actually uploaded.
	                newFailed++;
	                console.error('Sync: could not resolve planned new file path', filePath);
	                toast.error(
	                    $i18n.t('Failed to upload {{path}}: file not found in scanned directory', {
	                        path: filePath
	                    })
	                );
	                processedCount++;
	                continue;
	            }
	            const ok = await uploadFileHandler(fileData.file);
	            if (ok) {
	                newSucceeded++;
	            } else {
	                newFailed++;
	            }
	            processedCount++;
	            toast.info(
	                $i18n.t('Uploading new: {{current}}/{{total}}', {
	                    current: processedCount,
	                    total: totalToProcess
	                })
	            );
	        }

	        // STEP 3: Upload changed files using atomic upload_and_replace
	        // endpoint. The API wrapper throws on failure, so catch per file
	        // to keep the sync going and report an accurate changed/failed
	        // split at the end.
	        let changedSucceeded = 0;
	        let changedFailed = 0;
	        for (const changedFile of changed_files) {
	            const fileData = filesByPath.get(changedFile.file_path);
	            if (!fileData) {
	                // Same defensive guard as the new-files loop above.
	                changedFailed++;
	                console.error(
	                    'Sync: could not resolve planned replace path',
	                    changedFile.file_path
	                );
	                toast.error(
	                    $i18n.t('Failed to update {{path}}: file not found in scanned directory', {
	                        path: changedFile.file_path
	                    })
	                );
	                processedCount++;
	                continue;
	            }
	            try {
	                await uploadAndReplaceFile(
	                    localStorage.token,
	                    id,
	                    fileData.file,
	                    changedFile.old_file_id
	                );
	                changedSucceeded++;
	            } catch (replaceErr) {
	                changedFailed++;
	                console.error('Replace failed for', changedFile.file_path, replaceErr);
	                const detail =
	                    typeof replaceErr === 'string'
	                        ? replaceErr
	                        : (replaceErr?.detail ?? replaceErr?.message ?? 'unknown error');
	                toast.error(
	                    $i18n.t('Failed to update {{path}}: {{detail}}', {
	                        path: changedFile.file_path,
	                        detail
	                    })
	                );
	            }
	            processedCount++;
	            toast.info(
	                $i18n.t('Updating: {{current}}/{{total}}', {
	                    current: processedCount,
	                    total: totalToProcess
	                })
	            );
	        }

	        // Show summary. Use succeeded counts — not the planned counts —
	        // so the user sees real outcomes. Include a failure tally only
	        // when something went wrong.
	        const totalFailed = newFailed + changedFailed + removedFailed;
	        if (totalFailed > 0) {
	            toast.warning(
	                $i18n.t(
	                    'Sync finished with issues: {{newCount}} new, {{changedCount}} updated, {{removedCount}} removed, {{unchangedCount}} unchanged, {{failedCount}} failed',
	                    {
	                        newCount: newSucceeded,
	                        changedCount: changedSucceeded,
	                        removedCount: removedSucceeded,
	                        unchangedCount: unchanged.length,
	                        failedCount: totalFailed
	                    }
	                )
	            );
	        } else {
	            toast.success(
	                $i18n.t(
	                    'Sync complete: {{newCount}} new, {{changedCount}} updated, {{removedCount}} removed, {{unchangedCount}} unchanged',
	                    {
	                        newCount: newSucceeded,
	                        changedCount: changedSucceeded,
	                        removedCount: removedSucceeded,
	                        unchangedCount: unchanged.length
	                    }
	                )
	            );
	        }
	
	        // Refresh the file list
	        await init();
	    } catch (error) {
	        console.error('Sync error:', error);
	        const message =
	            typeof error === 'string'
	                ? error
	                : (error?.detail ?? error?.message ?? $i18n.t('Failed to sync directory'));
	        toast.error(message);
	    }
	};

	// Returns a truthy value only when the file actually made it into the KB,
	// so upstream flows (uploadFileHandler → directory sync) can distinguish
	// real successes from add failures this handler otherwise absorbs via
	// toasts.
	const addFileHandler = async (fileId) => {
		const res = await addFileToKnowledgeById(localStorage.token, id, fileId).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('File added successfully.'));
			init();
			return res;
		} else {
			toast.error($i18n.t('Failed to add file.'));
			fileItems = fileItems.filter((file) => file.id !== fileId);
			return null;
		}
	};

	const deleteFileHandler = async (fileId) => {
		try {
			console.log('Starting file deletion process for:', fileId);

			// Remove from knowledge base only
			const res = await removeFileFromKnowledgeById(localStorage.token, id, fileId);
			console.log('Knowledge base updated:', res);

			if (res) {
				toast.success($i18n.t('File removed successfully.'));
				await init();
			}
		} catch (e) {
			console.error('Error in deleteFileHandler:', e);
			toast.error(`${e}`);
		}
	};

	let debounceTimeout = null;
	let mediaQuery;

	let dragged = false;
	let isSaving = false;

	const updateFileContentHandler = async () => {
		if (isSaving) {
			console.log('Save operation already in progress, skipping...');
			return;
		}

		isSaving = true;

		try {
			const res = await updateFileDataContentById(
				localStorage.token,
				selectedFile.id,
				selectedFileContent
			).catch((e) => {
				toast.error(`${e}`);
				return null;
			});

			if (res) {
				toast.success($i18n.t('File content updated successfully.'));

				selectedFileId = null;
				selectedFile = null;
				selectedFileContent = '';

				await init();
			}
		} finally {
			isSaving = false;
		}
	};

	const changeDebounceHandler = () => {
		console.log('debounce');
		if (debounceTimeout) {
			clearTimeout(debounceTimeout);
		}

		debounceTimeout = setTimeout(async () => {
			if (knowledge.name.trim() === '' || knowledge.description.trim() === '') {
				toast.error($i18n.t('Please fill in all fields.'));
				return;
			}

			const res = await updateKnowledgeById(localStorage.token, id, {
				...knowledge,
				name: knowledge.name,
				description: knowledge.description,
				access_grants: knowledge.access_grants ?? []
			}).catch((e) => {
				toast.error(`${e}`);
			});

			if (res) {
				toast.success($i18n.t('Knowledge updated successfully'));
			}
		}, 1000);
	};

	const handleMediaQuery = async (e) => {
		if (e.matches) {
			largeScreen = true;
		} else {
			largeScreen = false;
		}
	};

	const onDragOver = (e) => {
		e.preventDefault();

		// Check if a file is being draggedOver.
		if (e.dataTransfer?.types?.includes('Files')) {
			dragged = true;
		} else {
			dragged = false;
		}
	};

	const onDragLeave = () => {
		dragged = false;
	};

	const onDrop = async (e) => {
		e.preventDefault();
		dragged = false;

		if (!knowledge?.write_access) {
			toast.error($i18n.t('You do not have permission to upload files to this knowledge base.'));
			return;
		}

		const handleUploadingFileFolder = (items) => {
			for (const item of items) {
				if (item.isFile) {
					item.file((file) => {
						uploadFileHandler(file);
					});
					continue;
				}

				// Not sure why you have to call webkitGetAsEntry and isDirectory seperate, but it won't work if you try item.webkitGetAsEntry().isDirectory
				const wkentry = item.webkitGetAsEntry();
				const isDirectory = wkentry.isDirectory;
				if (isDirectory) {
					// Read the directory
					wkentry.createReader().readEntries(
						(entries) => {
							handleUploadingFileFolder(entries);
						},
						(error) => {
							console.error('Error reading directory entries:', error);
						}
					);
				} else {
					toast.info($i18n.t('Uploading file...'));
					uploadFileHandler(item.getAsFile());
					toast.success($i18n.t('File uploaded!'));
				}
			}
		};

		if (e.dataTransfer?.types?.includes('Files')) {
			if (e.dataTransfer?.files) {
				const inputItems = e.dataTransfer?.items;

				if (inputItems && inputItems.length > 0) {
					handleUploadingFileFolder(inputItems);
				} else {
					toast.error($i18n.t(`File not found.`));
				}
			}
		}
	};

	onMount(async () => {
		// listen to resize 1024px
		mediaQuery = window.matchMedia('(min-width: 1024px)');

		mediaQuery.addEventListener('change', handleMediaQuery);
		handleMediaQuery(mediaQuery);

		// Select the container element you want to observe
		const container = document.getElementById('collection-container');

		// initialize the minSize based on the container width
		minSize = !largeScreen ? 100 : Math.floor((300 / container.clientWidth) * 100);

		// Create a new ResizeObserver instance
		const resizeObserver = new ResizeObserver((entries) => {
			for (let entry of entries) {
				const width = entry.contentRect.width;
				// calculate the percentage of 300
				const percentage = (300 / width) * 100;
				// set the minSize to the percentage, must be an integer
				minSize = !largeScreen ? 100 : Math.floor(percentage);

				if (showSidepanel) {
					if (pane && pane.isExpanded() && pane.getSize() < minSize) {
						pane.resize(minSize);
					}
				}
			}
		});

		// Start observing the container's size changes
		resizeObserver.observe(container);

		if (pane) {
			pane.expand();
		}

		id = $page.params.id;
		const res = await getKnowledgeById(localStorage.token, id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			knowledge = res;
			if (!Array.isArray(knowledge?.access_grants)) {
				knowledge.access_grants = [];
			}
			knowledgeId = knowledge?.id;
		} else {
			goto('/workspace/knowledge');
		}

		const dropZone = document.querySelector('body');
		dropZone?.addEventListener('dragover', onDragOver);
		dropZone?.addEventListener('drop', onDrop);
		dropZone?.addEventListener('dragleave', onDragLeave);
	});

	onDestroy(() => {
		clearTimeout(searchDebounceTimer);
		mediaQuery?.removeEventListener('change', handleMediaQuery);
		const dropZone = document.querySelector('body');
		dropZone?.removeEventListener('dragover', onDragOver);
		dropZone?.removeEventListener('drop', onDrop);
		dropZone?.removeEventListener('dragleave', onDragLeave);
	});

	const decodeString = (str: string) => {
		try {
			return decodeURIComponent(str);
		} catch (e) {
			return str;
		}
	};
</script>

<FilesOverlay show={dragged} />
<SyncConfirmDialog
	bind:show={showSyncConfirmModal}
	message={$i18n.t(
		'This will sync the knowledge base with the selected directory. New and changed files will be uploaded, and files removed from the directory will be deleted from the knowledge base. Continue?'
	)}
	on:confirm={() => {
		syncDirectoryHandler();
	}}
/>

<AttachWebpageModal
	bind:show={showAddWebpageModal}
	onSubmit={async (e) => {
		uploadWeb(e.data);
	}}
/>

<AddTextContentModal
	bind:show={showAddTextContentModal}
	on:submit={(e) => {
		const file = createFileFromText(e.detail.name, e.detail.content);
		uploadFileHandler(file);
	}}
/>

<input
	id="files-input"
	bind:files={inputFiles}
	type="file"
	multiple
	hidden
	on:change={async () => {
		if (inputFiles && inputFiles.length > 0) {
			for (const file of inputFiles) {
				await uploadFileHandler(file);
			}

			inputFiles = null;
			const fileInputElement = document.getElementById('files-input');

			if (fileInputElement) {
				fileInputElement.value = '';
			}
		} else {
			toast.error($i18n.t(`File not found.`));
		}
	}}
/>

<div class="flex flex-col w-full h-full min-h-full" id="collection-container">
	{#if id && knowledge}
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessGrants={knowledge.access_grants}
			share={$user?.permissions?.sharing?.knowledge || $user?.role === 'admin'}
			sharePublic={$user?.permissions?.sharing?.public_knowledge || $user?.role === 'admin'}
			shareUsers={($user?.permissions?.access_grants?.allow_users ?? true) ||
				$user?.role === 'admin'}
			onChange={async () => {
				try {
					await updateKnowledgeAccessGrants(localStorage.token, id, knowledge.access_grants ?? []);
					toast.success($i18n.t('Saved'));
				} catch (error) {
					toast.error(`${error}`);
				}
			}}
			accessRoles={['read', 'write']}
		/>
		<div class="w-full px-2">
			<div class=" flex w-full">
				<div class="flex-1">
					<div class="flex items-center justify-between w-full">
						<div class="w-full flex justify-between items-center">
							<input
								type="text"
								class="text-left w-full text-lg bg-transparent outline-hidden flex-1"
								bind:value={knowledge.name}
								aria-label={$i18n.t('Knowledge Name')}
								placeholder={$i18n.t('Knowledge Name')}
								disabled={!knowledge?.write_access}
								on:input={() => {
									changeDebounceHandler();
								}}
							/>

							<div class="shrink-0 mr-2.5">
								{#if fileItemsTotal}
									<div class="text-xs text-gray-500">
										<!-- {$i18n.t('{{COUNT}} files')} -->
										{$i18n.t('{{COUNT}} files', {
											COUNT: fileItemsTotal
										})}
									</div>
								{/if}
							</div>
						</div>

						{#if knowledge?.write_access}
							<div class="self-center shrink-0">
								<button
									class="bg-gray-50 hover:bg-gray-100 text-black dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-white transition px-2 py-1 rounded-full flex gap-1 items-center"
									type="button"
									on:click={() => {
										showAccessControlModal = true;
									}}
								>
									<LockClosed strokeWidth="2.5" className="size-3.5" />

									<div class="text-sm font-medium shrink-0">
										{$i18n.t('Access')}
									</div>
								</button>
							</div>
						{:else}
							<div class="text-xs shrink-0 text-gray-500">
								{$i18n.t('Read Only')}
							</div>
						{/if}
					</div>

					<div class="flex w-full">
						<input
							type="text"
							class="text-left text-xs w-full text-gray-500 bg-transparent outline-hidden"
							bind:value={knowledge.description}
							aria-label={$i18n.t('Knowledge Description')}
							placeholder={$i18n.t('Knowledge Description')}
							disabled={!knowledge?.write_access}
							on:input={() => {
								changeDebounceHandler();
							}}
						/>
					</div>
				</div>
			</div>
		</div>

		<div
			class="mt-2 mb-2.5 py-2 -mx-0 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30 flex-1"
		>
			<div class="px-3.5 flex flex-1 items-center w-full space-x-2 py-0.5 pb-2">
				<div class="flex flex-1 items-center">
					<div class=" self-center ml-1 mr-3">
						<Search className="size-3.5" />
					</div>
					<input
						class=" w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
						bind:value={query}
						aria-label={$i18n.t('Search Collection')}
						placeholder={$i18n.t('Search Collection')}
						on:focus={() => {
							selectedFileId = null;
						}}
					/>

					{#if knowledge?.write_access}
						<div>
							<AddContentMenu
								onUpload={(data) => {
									if (data.type === 'directory') {
										uploadDirectoryHandler();
									} else if (data.type === 'web') {
										showAddWebpageModal = true;
									} else if (data.type === 'text') {
										showAddTextContentModal = true;
									} else {
										document.getElementById('files-input').click();
									}
								}}
								onSync={() => {
									showSyncConfirmModal = true;
								}}
							/>
						</div>
					{/if}
				</div>
			</div>

			<div class="px-3 flex justify-between">
				<div
					class="flex w-full bg-transparent overflow-x-auto scrollbar-none"
					on:wheel={(e) => {
						if (e.deltaY !== 0) {
							e.preventDefault();
							e.currentTarget.scrollLeft += e.deltaY;
						}
					}}
				>
					<div
						class="flex gap-3 w-fit text-center text-sm rounded-full bg-transparent px-0.5 whitespace-nowrap"
					>
						<DropdownOptions
							align="start"
							className="flex shrink-0 items-center gap-2 px-3 py-1.5 text-sm bg-gray-50 dark:bg-gray-850 rounded-xl placeholder-gray-400 outline-hidden focus:outline-hidden"
							bind:value={viewOption}
							items={[
								{ value: null, label: $i18n.t('All') },
								{ value: 'created', label: $i18n.t('Created by you') },
								{ value: 'shared', label: $i18n.t('Shared with you') }
							]}
							onChange={(value) => {
								if (value) {
									localStorage.workspaceViewOption = value;
								} else {
									delete localStorage.workspaceViewOption;
								}
							}}
						/>

						<DropdownOptions
							align="start"
							bind:value={sortKey}
							placeholder={$i18n.t('Sort')}
							items={[
								{ value: 'name', label: $i18n.t('Name') },
								{ value: 'created_at', label: $i18n.t('Created At') },
								{ value: 'updated_at', label: $i18n.t('Updated At') }
							]}
						/>

						{#if sortKey}
							<DropdownOptions
								align="start"
								bind:value={direction}
								items={[
									{ value: 'asc', label: $i18n.t('Asc') },
									{ value: null, label: $i18n.t('Desc') }
								]}
							/>
						{/if}
					</div>
				</div>
			</div>

			{#if fileItems !== null && fileItemsTotal !== null}
				<div class="flex flex-row flex-1 gap-3 px-2.5 mt-2">
					<div class="flex-1 flex">
						<div class=" flex flex-col w-full space-x-2 rounded-lg h-full">
							<div class="w-full h-full flex flex-col min-h-full">
								{#if fileItems.length > 0}
									<div class=" flex overflow-y-auto h-full w-full scrollbar-hidden text-xs">
										<Files
											files={fileItems}
											{knowledge}
											{selectedFileId}
											onClick={(fileId) => {
												selectedFileId = fileId;

												if (fileItems) {
													const file = fileItems.find((file) => file.id === selectedFileId);
													if (file) {
														fileSelectHandler(file);
													} else {
														selectedFile = null;
													}
												}
											}}
											onDelete={(fileId) => {
												selectedFileId = null;
												selectedFile = null;

												deleteFileHandler(fileId);
											}}
										/>
									</div>

									{#if fileItemsTotal > 30}
										<Pagination bind:page={currentPage} count={fileItemsTotal} perPage={30} />
									{/if}
								{:else}
									<div class="my-3 flex flex-col justify-center text-center text-gray-500 text-xs">
										<div>
											{$i18n.t('No content found')}
										</div>
									</div>
								{/if}
							</div>
						</div>
					</div>

					{#if selectedFileId !== null}
						<Drawer
							className="h-full"
							show={selectedFileId !== null}
							onClose={() => {
								selectedFileId = null;
								selectedFile = null;
							}}
						>
							<div class="flex flex-col justify-start h-full max-h-full">
								<div class=" flex flex-col w-full h-full max-h-full">
									<div class="shrink-0 flex items-center p-2">
										<div class="mr-2">
											<button
												class="w-full text-left text-sm p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850"
												aria-label={$i18n.t('Close')}
												on:click={() => {
													selectedFileId = null;
													selectedFile = null;
												}}
											>
												<ChevronLeft strokeWidth="2.5" />
											</button>
										</div>
										<div class=" flex-1 text-lg line-clamp-1">
											{selectedFile?.meta?.name}
										</div>

										{#if knowledge?.write_access}
											<div>
												<button
													class="flex self-center w-fit text-sm py-1 px-2.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
													disabled={isSaving}
													on:click={() => {
														updateFileContentHandler();
													}}
												>
													{$i18n.t('Save')}
													{#if isSaving}
														<div class="ml-2 self-center">
															<Spinner />
														</div>
													{/if}
												</button>
											</div>
										{/if}
									</div>

									{#key selectedFile.id}
										<textarea
											class="w-full h-full text-sm outline-none resize-none px-3 py-2"
											bind:value={selectedFileContent}
											disabled={!knowledge?.write_access}
											aria-label={$i18n.t('File content')}
											placeholder={$i18n.t('Add content here')}
										/>
									{/key}
								</div>
							</div>
						</Drawer>
					{/if}
				</div>
			{:else}
				<div class="my-10">
					<Spinner className="size-4" />
				</div>
			{/if}
		</div>
	{:else}
		<Spinner className="size-5" />
	{/if}
</div>
