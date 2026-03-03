import React from 'react';
import { HUNK_ACCEPTED, HUNK_PENDING, HUNK_REJECTED, buildHunkPreview, summarizeHunks } from './copilotShared';
import CopilotThinkingIndicator from './CopilotThinkingIndicator';

export default function CopilotMessageList({
    messages,
    activePatchMessageId,
    activatePatchMessage,
    handleAllHunksDecision,
    handleHunkDecision,
    isLoading,
    liveAssistant,
}) {
    return (
        <div className="mb-3 space-y-2 flex-1 overflow-auto">
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

function formatTokens(n) {
    if (n == null || typeof n !== 'number' || Number.isNaN(n)) return '0';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
}

function formatCost(cost) {
    if (cost == null || typeof cost !== 'number' || Number.isNaN(cost) || cost < 0) return null;
    if (cost >= 0.01) return `~$${cost.toFixed(2)}`;
    if (cost > 0) return `~$${cost.toFixed(4)}`;
    return '~$0.00';
}
