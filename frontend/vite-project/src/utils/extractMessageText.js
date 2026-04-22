export default function extractMessageText(messageContent) {
	let extractedText = '';

	if (typeof messageContent === 'string') {
		extractedText = messageContent;
	} else if (Array.isArray(messageContent)) {
		extractedText = messageContent
			.filter(part => part && part.type === 'text')
			.map(part => part.value)
			.join('\n');
	} else if (messageContent && typeof messageContent === 'object') {
		if (messageContent.content) {
			extractedText = messageContent.content;
		} else if (messageContent.value) {
			extractedText = messageContent.value;
		} else {
			extractedText = JSON.stringify(messageContent);
		}
	} else {
		extractedText = String(messageContent || '');
	}

	return extractedText;
}


