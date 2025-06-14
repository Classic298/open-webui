// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />

// These tests run through the chat flow.
describe('Settings', () => {
	// Wait for 2 seconds after all tests to fix an issue with Cypress's video recording missing the last few frames
	after(() => {
		// eslint-disable-next-line cypress/no-unnecessary-waiting
		cy.wait(2000);
	});

	beforeEach(() => {
		// Login as the admin user
		cy.loginAdmin();
		// Visit the home page
		cy.visit('/');
	});

	context('Ollama', () => {
		it('user can select a model', () => {
			// Click on the model selector
			cy.get('button[aria-label="Select a model"]').click();
			// Select the first model
			cy.get('button[aria-label="model-item"]').first().click();
		});

		it('user can perform text chat', () => {
			// Click on the model selector
			cy.get('button[aria-label="Select a model"]').click();
			// Select the first model
			cy.get('button[aria-label="model-item"]').first().click();
			// Type a message
			cy.get('#chat-input').type('Hi, what can you do? A single sentence only please.', {
				force: true
			});
			// Send the message
			cy.get('button[type="submit"]').click();
			// User's message should be visible
			cy.get('.chat-user').should('exist');
			// Wait for the response
			// .chat-assistant is created after the first token is received
			cy.get('.chat-assistant', { timeout: 10_000 }).should('exist');
			// Generation Info is created after the stop token is received
			cy.get('div[aria-label="Generation Info"]', { timeout: 120_000 }).should('exist');
		});

		it('user can share chat', () => {
			// Click on the model selector
			cy.get('button[aria-label="Select a model"]').click();
			// Select the first model
			cy.get('button[aria-label="model-item"]').first().click();
			// Type a message
			cy.get('#chat-input').type('Hi, what can you do? A single sentence only please.', {
				force: true
			});
			// Send the message
			cy.get('button[type="submit"]').click();
			// User's message should be visible
			cy.get('.chat-user').should('exist');
			// Wait for the response
			// .chat-assistant is created after the first token is received
			cy.get('.chat-assistant', { timeout: 10_000 }).should('exist');
			// Generation Info is created after the stop token is received
			cy.get('div[aria-label="Generation Info"]', { timeout: 120_000 }).should('exist');
			// spy on requests
			const spy = cy.spy();
			cy.intercept('POST', '/api/v1/chats/**/share', spy);
			// Open context menu
			cy.get('#chat-context-menu-button').click();
			// Click share button
			cy.get('#chat-share-button').click();
			// Check if the share dialog is visible
			cy.get('#copy-and-share-chat-button').should('exist');
			// Click the copy button
			cy.get('#copy-and-share-chat-button').click();
			cy.wrap({}, { timeout: 5_000 }).should(() => {
				// Check if the share request was made
				expect(spy).to.be.callCount(1);
			});
		});

		it('user can generate image', () => {
			// Click on the model selector
			cy.get('button[aria-label="Select a model"]').click();
			// Select the first model
			cy.get('button[aria-label="model-item"]').first().click();
			// Type a message
			cy.get('#chat-input').type('Hi, what can you do? A single sentence only please.', {
				force: true
			});
			// Send the message
			cy.get('button[type="submit"]').click();
			// User's message should be visible
			cy.get('.chat-user').should('exist');
			// Wait for the response
			// .chat-assistant is created after the first token is received
			cy.get('.chat-assistant', { timeout: 10_000 }).should('exist');
			// Generation Info is created after the stop token is received
			cy.get('div[aria-label="Generation Info"]', { timeout: 120_000 }).should('exist');
			// Click on the generate image button
			cy.get('[aria-label="Generate Image"]').click();
			// Wait for image to be visible
			cy.get('img[data-cy="image"]', { timeout: 60_000 }).should('be.visible');
		});
	});

	context('Error Handling', () => {
		const setupChatWithError = (errorMessageContent = 'Test error content') => {
			// Start a new chat
			cy.get('button[aria-label="New Chat"]').click();
			// Click on the model selector
			cy.get('button[aria-label="Select a model"]').click();
			// Select the first model
			cy.get('button[aria-label="model-item"]').first().click();

			// Type a message
			const userMessage = 'This message will cause an error.';
			cy.get('#chat-input').type(userMessage, {
				force: true
			});
			// Send the message
			cy.get('button[type="submit"]').click();
			// User's message should be visible
			cy.get('.chat-user').should('contain', userMessage);

			// Wait for the app to process the message and potentially create an assistant message placeholder
			cy.wait(500); // Adjust as needed

			// Use cy.window() to manipulate the history store
			cy.window().then((win) => {
				// Access the history store (assuming it's available on `win.stores.history`)
				// This path might need adjustment based on actual store structure in OpenWebUI
				const historyStore = win.svelte.getContext('history'); // Or however stores are accessed

				if (!historyStore) {
					throw new Error('History store not found. Cannot inject error message.');
				}

				// Get current history
				let currentHistory = historyStore.get();
				const userMessageId = Object.keys(currentHistory.messages).find(
					(id) => currentHistory.messages[id].role === 'user'
				);

				if (!userMessageId) {
					throw new Error('User message not found. Cannot inject error message.');
				}

				const errorMsgId = `err-${Date.now()}`;
				const errorAssistantMessage = {
					id: errorMsgId,
					parentId: userMessageId,
					childrenIds: [],
					role: 'assistant',
					content: '', // Error messages might have no primary content initially
					error: { content: errorMessageContent },
					model: currentHistory.messages[userMessageId].models[0] || 'mock-model', // Ensure model is set
					timestamp: Math.floor(Date.now() / 1000),
					done: true // Error messages are 'done'
				};

				// Update the user message's children
				currentHistory.messages[userMessageId].childrenIds.push(errorMsgId);
				// Add the error message
				currentHistory.messages[errorMsgId] = errorAssistantMessage;
				// Set currentId to the error message to ensure it's the last one rendered
				currentHistory.currentId = errorMsgId;

				historyStore.set(currentHistory);

				// Trigger a Svelte update cycle if necessary
				// This might also need adjustment; sometimes direct store updates trigger reactivity, sometimes not.
				// win.svelte.tick(); // if available and needed
			});

			// Verify the error message is displayed
			cy.get('.chat-assistant .prose').should('contain', errorMessageContent);
			cy.get('button').contains('Retry').should('be.visible');
			cy.get('button').contains('Ignore').should('be.visible');
		};

		it('allows user to retry a failed message', () => {
			setupChatWithError('Initial error for retry');

			// Click the "Retry" button
			cy.get('button').contains('Retry').click();

			// Assertions:
			// 1. The error message content should ideally be gone or replaced by a loading state.
			//    For now, we'll check that the old error is not present and a new assistant message appears.
			cy.contains('Initial error for retry').should('not.exist');

			// 2. A new assistant message (or loading state) should appear.
			//    This assumes retry clears the old error and attempts a new generation.
			cy.get('.chat-assistant', { timeout: 10_000 }).should('exist');
			// Check for a positive response (or at least not the error one)
			// This assertion is tricky as we don't know the exact response.
			// We can check that the assistant message doesn't contain the error text.
			cy.get('.chat-assistant .prose').should((prose) => {
				expect(prose.text()).not.to.contain('Initial error for retry');
			});
			// And that a new generation happens
			cy.get('div[aria-label="Generation Info"]', { timeout: 120_000 }).should('exist');
		});

		it('allows user to ignore a failed message and send a new one', () => {
			setupChatWithError('Initial error for ignore');

			// Click the "Ignore" button
			cy.get('button').contains('Ignore').click();

			// Assertions:
			// 1. The error message component (including the specific error text) should be removed.
			cy.contains('Initial error for ignore').should('not.exist');
			cy.get('button').contains('Retry').should('not.exist');
			cy.get('button').contains('Ignore').should('not.exist');

			// 2. Chat input should be available
			cy.get('#chat-input').should('be.visible').and('not.be.disabled');

			// 3. Send a new message
			const newMessage = 'This is a new message after ignoring an error.';
			cy.get('#chat-input').type(newMessage, { force: true });
			cy.get('button[type="submit"]').click();

			// 4. The new user message should appear
			cy.get('.chat-user').should('contain', newMessage);

			// 5. A new assistant response should be generated
			cy.get('.chat-assistant', { timeout: 10_000 }).should('exist');
			cy.get('.chat-assistant .prose').should((prose) => {
				// Ensure the new response is not the old error
				expect(prose.text()).not.to.contain('Initial error for ignore');
			});
			cy.get('div[aria-label="Generation Info"]', { timeout: 120_000 }).should('exist');

			// 6. Verify the new message is correctly parented (tricky to do precisely without more DOM markers,
			// but we can check that the original user message that caused the error is still present)
			cy.get('.chat-user').contains('This message will cause an error.').should('exist');
		});
	});
});
