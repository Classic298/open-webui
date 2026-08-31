import { describe, expect, it } from 'vitest';
import { buildOutputDisplayItems, getOutputText, type OutputItem } from './structuredOutput';

const messageItem = (text: string, id = 'msg-1'): OutputItem => ({
	type: 'message',
	id,
	content: [{ type: 'output_text', text }]
});

// Sparse arrays carry explicit `undefined` elements after a spread; these
// mirror the shapes that reach `buildOutputDisplayItems` from message.output.
const withHoles = (...items: (OutputItem | null | undefined)[]): OutputItem[] =>
	items as OutputItem[];

describe('buildOutputDisplayItems', () => {
	it('skips undefined and null elements instead of throwing', () => {
		const output = withHoles(undefined, null, messageItem('hello'));

		expect(() => buildOutputDisplayItems(output)).not.toThrow();

		const items = buildOutputDisplayItems(output);
		expect(items).toHaveLength(1);
		const [first] = items;
		if (first?.type !== 'message') {
			throw new Error('expected a message display item');
		}
		expect(first.text).toBe('hello');
	});

	it('preserves surrounding items after filtering holes', () => {
		const output = withHoles(
			messageItem('first', 'msg-1'),
			undefined,
			messageItem('last', 'msg-2')
		);
		const items = buildOutputDisplayItems(output);

		expect(items.map((item) => item.id)).toEqual(['msg-1', 'msg-2']);
	});

	it('returns an empty list for an empty or all-hole output', () => {
		expect(buildOutputDisplayItems(withHoles(undefined, null))).toEqual([]);
		expect(buildOutputDisplayItems([])).toEqual([]);
	});
});

describe('getOutputText', () => {
	it('does not throw when the output contains undefined elements', () => {
		const output = withHoles(undefined, messageItem('hi'));

		expect(() => getOutputText(output)).not.toThrow();
		expect(getOutputText(output)).toBe('hi');
	});

	it('returns an empty string for undefined, null, or a hole-carrying output', () => {
		expect(getOutputText(withHoles(undefined))).toBe('');
		expect(getOutputText(null)).toBe('');
		expect(getOutputText(undefined)).toBe('');
	});
});
