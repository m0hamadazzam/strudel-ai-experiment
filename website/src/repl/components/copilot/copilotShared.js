export const MAX_PREVIEW_LINES_PER_HUNK = 40;

/** Strip markdown ** bold markers from LLM reasoning output. */
export function sanitizeReasoningText(text) {
    if (!text) return '';
    return text.replace(/\*\*/g, '');
}

export function formatTokens(n) {
    if (n == null || typeof n !== 'number' || Number.isNaN(n)) return '0';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
}

export function formatCost(cost) {
    if (cost == null || typeof cost !== 'number' || Number.isNaN(cost) || cost < 0) return null;
    if (cost >= 0.01) return `~$${cost.toFixed(2)}`;
    if (cost > 0) return `~$${cost.toFixed(4)}`;
    return '~$0.00';
}

export const HUNK_PENDING = 'pending';
export const HUNK_ACCEPTED = 'accepted';
export const HUNK_REJECTED = 'rejected';

export function splitDiffLines(text) {
    if (!text) return [];
    const normalized = text.replace(/\r\n/g, '\n');
    const lines = normalized.split('\n');
    if (lines[lines.length - 1] === '') {
        lines.pop();
    }
    return lines;
}

export function summarizeHunks(hunks) {
    const summary = { pending: 0, accepted: 0, rejected: 0 };
    for (const hunk of hunks || []) {
        if (hunk.status === HUNK_ACCEPTED) summary.accepted += 1;
        else if (hunk.status === HUNK_REJECTED) summary.rejected += 1;
        else summary.pending += 1;
    }
    return summary;
}

export function buildHunkPreview(hunk) {
    const removed = splitDiffLines(hunk.oldText || '');
    const added = splitDiffLines(hunk.newText || '');

    const removedPreview = removed.slice(0, MAX_PREVIEW_LINES_PER_HUNK);
    const addedPreview = added.slice(0, MAX_PREVIEW_LINES_PER_HUNK);

    const lines = [
        ...removedPreview.map((text) => ({ type: 'remove', text })),
        ...addedPreview.map((text) => ({ type: 'add', text })),
    ];

    const truncated = removed.length > removedPreview.length || added.length > addedPreview.length;
    return { lines, truncated };
}
