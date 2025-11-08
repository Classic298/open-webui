// src/lib/utils/stream.ts

export class ReasoningStripper {
	private inThinking = false;
	private buffer = '';

	processChunk(chunk: string): string {
		this.buffer += chunk;
		let output = '';

		while (this.buffer.length > 0) {
			if (!this.inThinking) {
				const startIndex = this.buffer.indexOf('<thinking>');
				if (startIndex !== -1) {
					output += this.buffer.substring(0, startIndex);
					this.buffer = this.buffer.substring(startIndex + '<thinking>'.length);
					this.inThinking = true;
				} else {
					output += this.buffer;
					this.buffer = '';
				}
			} else {
				const endIndex = this.buffer.indexOf('</thinking>');
				if (endIndex !== -1) {
					this.buffer = this.buffer.substring(endIndex + '</thinking>'.length);
					this.inThinking = false;
				} else {
					this.buffer = '';
				}
			}
		}

		return output;
	}
}
