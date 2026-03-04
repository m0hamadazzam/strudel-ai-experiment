/**
 * Maximum number of lines from each side of a hunk to include in the inline preview.
 */
export const MAX_PREVIEW_LINES_PER_HUNK = 40;

/**
 * Removes markdown bold markers (`**`) from LLM reasoning output to keep the
 * inline thinking text visually lightweight in the UI.
 *
 * @param {string} text - Raw reasoning text returned by the model.
 * @returns {string} Reasoning text with markdown bold markers stripped out.
 */
export function sanitizeReasoningText(text) {
    if (!text) return '';
    return text.replace(/\*\*/g, '');
}

/**
 * Formats a token count into a short human‑readable label (e.g. `1.2k`, `3.4M`).
 *
 * @param {number | null | undefined} n - Raw token count.
 * @returns {string} String representation suitable for display in the UI.
 */
export function formatTokens(n) {
    if (n == null || typeof n !== 'number' || Number.isNaN(n)) return '0';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
}

/**
 * Formats an estimated cost in USD into a short human‑readable label.
 *
 * Values lower than $0.01 are shown with higher precision; invalid or negative
 * values return `null` so callers can omit the label entirely.
 *
 * @param {number | null | undefined} cost - Estimated dollar cost for a call.
 * @returns {string | null} Formatted cost label like `~$0.0123`, or `null`.
 */
export function formatCost(cost) {
    if (cost == null || typeof cost !== 'number' || Number.isNaN(cost) || cost < 0) return null;
    if (cost >= 0.01) return `~$${cost.toFixed(2)}`;
    if (cost > 0) return `~$${cost.toFixed(4)}`;
    return '~$0.00';
}

/**
 * Hunk status used while a proposed change is waiting for user review.
 * @type {'pending'}
 */
export const HUNK_PENDING = 'pending';

/**
 * Hunk status used when a proposed change has been applied to the document.
 * @type {'accepted'}
 */
export const HUNK_ACCEPTED = 'accepted';

/**
 * Hunk status used when a proposed change has been explicitly rejected.
 * @type {'rejected'}
 */
export const HUNK_REJECTED = 'rejected';

/**
 * Normalizes a diff text block into an array of non‑empty lines, trimming any
 * trailing empty line and handling Windows line endings.
 *
 * @param {string} text - Raw hunk text from the backend.
 * @returns {string[]} Array of individual logical lines.
 */
export function splitDiffLines(text) {
    if (!text) return [];
    const normalized = text.replace(/\r\n/g, '\n');
    const lines = normalized.split('\n');
    if (lines[lines.length - 1] === '') {
        lines.pop();
    }
    return lines;
}

/**
 * Counts how many hunks are pending, accepted, and rejected.
 *
 * @param {Array<{status: string}>} hunks - List of hunk objects associated with a message.
 * @returns {{pending: number, accepted: number, rejected: number}} Aggregate counts by status.
 */
export function summarizeHunks(hunks) {
    const summary = { pending: 0, accepted: 0, rejected: 0 };
    for (const hunk of hunks || []) {
        if (hunk.status === HUNK_ACCEPTED) summary.accepted += 1;
        else if (hunk.status === HUNK_REJECTED) summary.rejected += 1;
        else summary.pending += 1;
    }
    return summary;
}

/**
 * Builds a compact preview of a hunk by taking up to `MAX_PREVIEW_LINES_PER_HUNK`
 * removed and added lines, and marking whether the preview was truncated.
 *
 * @param {{ oldText?: string, newText?: string }} hunk - Hunk payload containing old/new text.
 * @returns {{ lines: Array<{type: 'remove' | 'add', text: string}>, truncated: boolean }}
 * Preview lines and a flag indicating if additional lines were omitted.
 */
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
