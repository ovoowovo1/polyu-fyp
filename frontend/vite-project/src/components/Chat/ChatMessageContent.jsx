import React from 'react';
import MarkdownIt from 'markdown-it';

import Citation from '../Citation.jsx';

const md = new MarkdownIt({
    html: true,
    linkify: true,
    typographer: true,
});

export default function ChatMessageContent({ content }) {
    if (typeof content === 'string') {
        const renderedContent = md.render(content);
        return <div dangerouslySetInnerHTML={{ __html: renderedContent }} className="prose max-w-none markdown-content leading-relaxed text-sm" />;
    }

    if (Array.isArray(content)) {
        return (
            <div className="prose max-w-none markdown-content leading-relaxed text-sm">
                {content.map((part, index) => {
                    if (part.type === 'text') {
                        let renderedHtml = md.render(part.value);
                        if (renderedHtml.startsWith('<p>') && renderedHtml.endsWith('</p>\n') && (renderedHtml.match(/<p>/g) || []).length === 1) {
                            renderedHtml = renderedHtml.slice(3, renderedHtml.length - 5);
                        }
                        return <span key={index} dangerouslySetInnerHTML={{ __html: renderedHtml }} />;
                    }
                    if (part.type === 'citation') {
                        return <Citation key={index} part={part} index={index} />;
                    }
                    return null;
                })}
            </div>
        );
    }

    return <div>{String(content)}</div>;
}
