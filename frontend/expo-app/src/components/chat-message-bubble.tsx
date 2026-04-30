import React from 'react';
import { Pressable, Text, View } from 'react-native';
import Markdown from 'react-native-markdown-display';

import { commonStyles, markdownStyles } from '@/lib/styles';
import type { ChatMessage, CitationDetails, StructuredPart } from '@/lib/types';

export function ChatMessageBubble({
  message,
  onPressCitation,
}: {
  message: ChatMessage;
  onPressCitation: (number: number, details?: CitationDetails) => void;
}) {
  const isUser = message.role === 'user';
  const groupedParts = message.parts ? groupStructuredParts(message.parts) : null;

  return (
    <View style={[commonStyles.bubble, isUser ? commonStyles.userBubble : commonStyles.assistantBubble]}>
      {groupedParts ? (
        <View style={commonStyles.assistantMessageContent}>
          {groupedParts.map((part, index) => (
            <StructuredPartView
              key={`${part.type}-${index}`}
              part={part}
              onPressCitation={onPressCitation}
            />
          ))}
        </View>
      ) : (
        <Text selectable style={isUser ? commonStyles.userBubbleText : commonStyles.bubbleText}>{message.text}</Text>
      )}
    </View>
  );
}

function StructuredPartView({
  part,
  onPressCitation,
}: {
  part: StructuredPart | { type: 'citation-group'; citations: Extract<StructuredPart, { type: 'citation' }>[] };
  onPressCitation: (number: number, details?: CitationDetails) => void;
}) {
  if (part.type === 'citation-group') {
    return (
      <View style={commonStyles.citationRow}>
        {part.citations.map((citation, index) => (
          <Pressable
            key={`${citation.number}-${index}`}
            accessibilityRole="button"
            onPress={() => onPressCitation(citation.number, citation.details)}
            style={({ pressed }) => [commonStyles.citationButton, pressed && commonStyles.pressed]}>
            <Text selectable style={commonStyles.citationText}>{`[${citation.number}]`}</Text>
          </Pressable>
        ))}
      </View>
    );
  }

  if (part.type === 'citation') {
    return (
      <Pressable
        accessibilityRole="button"
        onPress={() => onPressCitation(part.number, part.details)}
        style={({ pressed }) => [commonStyles.citationButton, pressed && commonStyles.pressed]}>
        <Text selectable style={commonStyles.citationText}>{`[${part.number}]`}</Text>
      </Pressable>
    );
  }

  return (
    <View style={commonStyles.markdownContent}>
      <Markdown style={markdownStyles}>{part.value}</Markdown>
    </View>
  );
}

function groupStructuredParts(parts: StructuredPart[]) {
  const grouped: (StructuredPart | {
    type: 'citation-group';
    citations: Extract<StructuredPart, { type: 'citation' }>[];
  })[] = [];

  for (const part of parts) {
    if (part.type === 'citation') {
      const last = grouped[grouped.length - 1];
      if (last && last.type === 'citation-group') {
        last.citations.push(part);
      } else {
        grouped.push({ type: 'citation-group', citations: [part] });
      }
      continue;
    }

    grouped.push(part);
  }

  return grouped;
}
