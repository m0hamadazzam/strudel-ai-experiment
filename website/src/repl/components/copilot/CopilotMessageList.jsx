import React from 'react';
import {
    HUNK_ACCEPTED,
    HUNK_PENDING,
    HUNK_REJECTED,
    buildHunkPreview,
    summarizeHunks,
    formatTokens,
    formatCost,
} from './copilotShared';
import CopilotThinkingIndicator from './CopilotThinkingIndicator';

const EMPTY_HINTS = [
    'Add a simple drum pattern',
    'Create a dancy Techno beat',
    'Do something experimental',
];

/**
 * Renders the conversational history between the user and the AI Copilot,
 * including patch review controls for messages that propose code edits.
 *
 * Assistant messages that contain hunks are annotated with small usage and
 * patch statistics, and expose per‑hunk and bulk accept/reject actions.
 *
 * @param {object} props
 * @param {Array<object>} props.messages - Ordered list of chat messages to display.
 * @param {string | null} props.activePatchMessageId - Identifier of the message whose hunks are currently shown in the editor.
 * @param {(messageId: string) => void} props.activatePatchMessage - Callback to focus a message's hunks in the editor.
 * @param {(messageId: string, action: 'accept' | 'reject') => void} props.handleAllHunksDecision - Applies an action to all pending hunks in a message.
 * @param {(messageId: string, hunkId: string, action: 'accept' | 'reject') => void} props.handleHunkDecision - Applies an action to a single hunk.
 * @param {boolean} props.isLoading - Whether the assistant is currently generating a response.
 * @param {{ phase?: string, reasoning?: string, isWebSearching?: boolean } | null} props.liveAssistant - Live reasoning state for the currently running request.
 */
export default function CopilotMessageList({
    messages,
    activePatchMessageId,
    activatePatchMessage,
    handleAllHunksDecision,
    handleHunkDecision,
    isLoading,
    liveAssistant,
}) {
    const isEmpty = messages.length === 0 && !isLoading;

    return (
        <div className="mb-3 space-y-2 flex-1 overflow-auto flex flex-col">
            {isEmpty && (
                <div className="flex-1 flex items-center justify-center min-h-[10rem] px-4">
                    <div className="w-full max-w-[85%] rounded-xl border border-white/10 bg-white/[0.03] px-5 py-6 text-left space-y-4">
                        <div className="space-y-1">
                            <p className="font-bold mb-4" style={{ color: 'var(--variable, #c792ea)' }}>Let&apos;s get it started 🔊</p>

                            <p className="text-foreground/60 text-sm">Describe a pattern, an effect, or an idea. Try:</p>
                        </div>
                        <div className="flex flex-col gap-2 pt-1">
                            {EMPTY_HINTS.map((hint) => (
                                <span
                                    key={hint}
                                    className="w-full rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-foreground/70 text-center"
                                >
                                    {hint}
                                </span>
                            ))}
                        </div>
                    </div>
                </div>
            )}
            {messages.map((msg) => {
                const isUser = msg.role === 'user';
                const hasHunks = Array.isArray(msg.hunks) && msg.hunks.length > 0;
                const summary = hasHunks ? summarizeHunks(msg.hunks) : null;
                const isActiveInEditor = activePatchMessageId === msg.id;

                return (
                    <div
                        key={msg.id}
                        className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
                    >
                        <div
                            className={
                                `max-w-[85%] rounded px-2 py-1 text-sm whitespace-pre-wrap ${isUser ?
                                    'bg-white/10' : 'bg-background'
                                }`
                            }
                        >
                            {msg.content}

                            {msg.patchStats && (
                                <div className="mt-2 text-[11px] opacity-70">
                                    {`${msg.patchStats.operations} edits · +${msg.patchStats.additions} / -${msg.patchStats.deletions}`}
                                </div>
                            )}

                            {!isUser && msg.usage && (msg.usage.input_tokens != null || msg.usage.output_tokens != null) && (
                                <div className="mt-2 text-[11px] flex flex-wrap items-baseline gap-x-1">
                                    <span className="text-cyan-400/90 font-medium">{formatTokens(msg.usage.input_tokens)}</span>
                                    <span className="opacity-70">in</span>
                                    <span className="opacity-50">/</span>
                                    <span className="text-emerald-400/90 font-medium">{formatTokens(msg.usage.output_tokens)}</span>
                                    <span className="opacity-70">out</span>
                                    {msg.usage.estimated_cost_usd != null && !Number.isNaN(msg.usage.estimated_cost_usd) && (
                                        <span className="text-amber-400/90 font-medium ml-1">{formatCost(msg.usage.estimated_cost_usd)}</span>
                                    )}
                                </div>
                            )}

                            {summary && (
                                <div className="mt-2 text-[11px] opacity-70">
                                    {`Pending ${summary.pending} · Accepted ${summary.accepted} · Rejected ${summary.rejected}`}
                                </div>
                            )}

                            {hasHunks && summary.pending > 0 && (
                                <div className="mt-2 flex flex-wrap gap-2">
                                    <button
                                        onClick={() => activatePatchMessage(msg.id)}
                                        className="flex-1 min-w-0 px-3 py-1.5 rounded border border-white/20 text-xs font-medium hover:bg-white/10"
                                    >
                                        {isActiveInEditor ? 'Reviewing in editor' : 'Show in editor'}
                                    </button>
                                    <button
                                        onClick={() => handleAllHunksDecision(msg.id, 'accept')}
                                        className="flex-1 min-w-0 px-3 py-1.5 rounded bg-white text-black text-xs font-medium hover:bg-white/90"
                                    >
                                        Accept all
                                    </button>
                                    <button
                                        onClick={() => handleAllHunksDecision(msg.id, 'reject')}
                                        className="flex-1 min-w-0 px-3 py-1.5 rounded border border-white/20 text-xs font-medium hover:bg-white/10"
                                    >
                                        Reject all
                                    </button>
                                </div>
                            )}

                            {hasHunks && (
                                <div className="mt-2 space-y-2">
                                    {msg.hunks.map((hunk, hunkIndex) => {
                                        const preview = buildHunkPreview(hunk);
                                        const isPending = hunk.status === HUNK_PENDING;
                                        const statusLabel = isPending
                                            ? 'Pending'
                                            : hunk.status === HUNK_ACCEPTED
                                                ? 'Accepted'
                                                : 'Rejected';

                                        return (
                                            <div
                                                key={hunk.id}
                                                className="rounded border border-white/10 overflow-hidden"
                                            >
                                                <div className="px-2 py-1 text-[11px] opacity-70 bg-white/5">
                                                    {`Hunk ${hunkIndex + 1} · ${hunk.op} · ${statusLabel}`}
                                                </div>

                                                {preview.lines.length > 0 && (
                                                    <div className="font-mono text-[11px]">
                                                        {preview.lines.map((line, lineIndex) => (
                                                            <div
                                                                key={`${hunk.id}-${lineIndex}`}
                                                                className={
                                                                    line.type === 'add'
                                                                        ? 'px-2 py-0.5 bg-emerald-500/10 text-emerald-200'
                                                                        : 'px-2 py-0.5 bg-red-500/10 text-red-200'
                                                                }
                                                            >
                                                                {(line.type === 'add' ? '+ ' : '- ') + (line.text || ' ')}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}

                                                {preview.truncated && (
                                                    <div className="px-2 py-1 text-[10px] opacity-60 bg-white/5">
                                                        Hunk preview truncated
                                                    </div>
                                                )}

                                                {isPending && (
                                                    <div className="p-2 flex gap-2">
                                                        <button
                                                            onClick={() => handleHunkDecision(msg.id, hunk.id, 'accept')}
                                                            className="flex-1 px-3 py-1.5 rounded bg-white text-black text-xs font-medium hover:bg-white/90"
                                                        >
                                                            Accept
                                                        </button>
                                                        <button
                                                            onClick={() => handleHunkDecision(msg.id, hunk.id, 'reject')}
                                                            className="flex-1 px-3 py-1.5 rounded border border-white/20 text-xs font-medium hover:bg-white/10"
                                                        >
                                                            Reject
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}

                            {msg.applied && (
                                <div className="mt-2 text-[11px] opacity-70">
                                    Patch applied
                                </div>
                            )}
                            {msg.discarded && (
                                <div className="mt-2 text-[11px] opacity-70">
                                    Patch discarded
                                </div>
                            )}
                        </div>
                    </div>
                );
            })}
            {isLoading && (
                <CopilotThinkingIndicator liveAssistant={liveAssistant} />
            )}
        </div>
    );
}
