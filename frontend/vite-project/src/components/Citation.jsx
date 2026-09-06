import React from 'react';
import { Popover } from 'antd';

export default function Citation({ part }) {
    const source = part.details;
    const content = <div className="max-w-md max-h-96 overflow-y-auto">
        <p><strong>{source.source}</strong></p>
        <p>Page {source.page}{source.pageEnd && source.pageEnd !== source.page ? `–${source.pageEnd}` : ''}</p>
        <pre className="whitespace-pre-wrap break-words">{source.content}</pre>
        {source.imageData && <img src={source.imageData} alt={source.source} />}
    </div>;
    return <Popover content={content} title="Citation source" trigger="click">
        <button type="button" aria-label={`Citation ${part.number}`} className="text-blue-600 font-bold mx-0.5 px-1.5 bg-blue-50 rounded">
            [{part.number}]
        </button>
    </Popover>;
}
