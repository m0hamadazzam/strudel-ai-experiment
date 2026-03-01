import { ChevronLeftIcon, XMarkIcon } from '@heroicons/react/16/solid';
import cx from '@src/cx.mjs';
import { setAICopilotSidebarWidth, setIsAICopilotSidebarOpened, useSettings } from '@src/settings.mjs';
import { useEffect, useRef, useState } from 'react';

const MAX_PREVIEW_LINES_PER_HUNK = 40;
const PATCH_ACTION_EVENT = 'strudel-ai-patch-hunk-action';

const HUNK_PENDING = 'pending';
const HUNK_ACCEPTED = 'accepted';
const HUNK_REJECTED = 'rejected';

function splitDiffLines(text) {
    if (!text) return [];
    const normalized = text.replace(/\r\n/g, '\n');
    const lines = normalized.split('\n');
    if (lines[lines.length - 1] === '') {
        lines.pop();
    }
    return lines;
}

function summarizeHunks(hunks) {
    const summary = { pending: 0, accepted: 0, rejected: 0 };
    for (const hunk of hunks || []) {
        if (hunk.status === HUNK_ACCEPTED) summary.accepted += 1;
        else if (hunk.status === HUNK_REJECTED) summary.rejected += 1;
        else summary.pending += 1;
    }
    return summary;
}

function buildHunkPreview(hunk) {
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

function buildPatchHunks(messageId, patchOps) {
    return (patchOps || []).map((op, index) => ({
        id: `${messageId}-hunk-${index + 1}`,
        op: op.op || 'replace',
        start: op.start,
        end: op.end,
        oldText: op.old_text || '',
        newText: op.new_text || '',
        status: HUNK_PENDING,
    }));
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

function findLatestPendingPatchMessage(messages) {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
        const message = messages[i];
        if (Array.isArray(message.hunks) && message.hunks.some((hunk) => hunk.status === HUNK_PENDING)) {
            return message;
        }
    }
    return null;
}

function updateMessageAfterHunkDecision(message, hunkId, nextStatus) {
    if (!Array.isArray(message.hunks)) {
        return message;
    }

    let changed = false;
    const hunks = message.hunks.map((hunk) => {
        if (hunk.id !== hunkId || hunk.status !== HUNK_PENDING) {
            return hunk;
        }
        changed = true;
        return { ...hunk, status: nextStatus };
    });

    if (!changed) {
        return message;
    }

    const summary = summarizeHunks(hunks);
    return {
        ...message,
        hunks,
        needsApproval: summary.pending > 0,
        applied: summary.pending === 0 && summary.accepted > 0,
        discarded: summary.pending === 0 && summary.accepted === 0 && summary.rejected > 0,
    };
}

export default function AICopilotSidebar({ context }) {
    const settings = useSettings();
    const { isAICopilotSidebarOpen, aiCopilotSidebarWidth } = settings;

    const [input, setInput] = useState('');
    const [messages, setMessages] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [isResizing, setIsResizing] = useState(false);
    const [activePatchMessageId, setActivePatchMessageId] = useState(null);
    const [sessionUsage, setSessionUsage] = useState({
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        estimated_cost_usd: null,
    });

    const textareaRef = useRef(null);
    const sidebarRef = useRef(null);
    const messageCounterRef = useRef(0);
    const messagesRef = useRef(messages);
    const activePatchMessageIdRef = useRef(activePatchMessageId);
    const applyHunkStatusRef = useRef(() => {});
    const appendAssistantNoticeRef = useRef(() => {});

    useEffect(() => {
        messagesRef.current = messages;
    }, [messages]);

    useEffect(() => {
        activePatchMessageIdRef.current = activePatchMessageId;
    }, [activePatchMessageId]);

    const nextMessageId = () => {
        messageCounterRef.current += 1;
        return `msg-${messageCounterRef.current}`;
    };

    const updateMessages = (updater) => {
        setMessages((prev) => {
            const next = typeof updater === 'function' ? updater(prev) : updater;
            messagesRef.current = next;
            return next;
        });
    };

    const getLiveCode = () => context?.editorRef?.current?.code ?? context?.activeCode ?? '';

    const appendAssistantNotice = (content) => {
        updateMessages((prev) => [
            ...prev,
            {
                id: nextMessageId(),
                role: 'assistant',
                content,
            },
        ]);
    };

    const clearPatchReviewInEditor = () => {
        const editorInstance = context?.editorRef?.current;
        if (editorInstance?.clearPatchReview) {
            editorInstance.clearPatchReview();
        }
        setActivePatchMessageId(null);
    };

    const activatePatchMessage = (messageId, messagesSnapshot = messagesRef.current, silent = false) => {
        const editorInstance = context?.editorRef?.current;
        if (!editorInstance?.setPatchReview) {
            if (!silent) {
                appendAssistantNotice('Editor patch preview is not available right now.');
            }
            return false;
        }

        const target = messagesSnapshot.find((message) => message.id === messageId);
        if (!target || !Array.isArray(target.hunks)) {
            return false;
        }

        const pendingHunks = target.hunks.filter((hunk) => hunk.status === HUNK_PENDING);
        if (pendingHunks.length === 0) {
            if (activePatchMessageIdRef.current === messageId) {
                clearPatchReviewInEditor();
            }
            return false;
        }

        if (activePatchMessageIdRef.current !== messageId) {
            const liveCode = getLiveCode();
            if (typeof target.baseCode === 'string' && liveCode !== target.baseCode) {
                if (!silent) {
                    appendAssistantNotice('Cannot review this patch in editor because the code changed since it was generated.');
                }
                return false;
            }
        }

        editorInstance.setPatchReview(pendingHunks);
        setActivePatchMessageId(messageId);
        return true;
    };

    const applyHunkStatus = (hunkId, nextStatus) => {
        updateMessages((prev) => prev.map((message) => updateMessageAfterHunkDecision(message, hunkId, nextStatus)));
    };

    useEffect(() => {
        applyHunkStatusRef.current = applyHunkStatus;
        appendAssistantNoticeRef.current = appendAssistantNotice;
    });

    const handleHunkDecision = (messageId, hunkId, action) => {
        const editorInstance = context?.editorRef?.current;
        if (!editorInstance?.acceptPatchHunk || !editorInstance?.rejectPatchHunk) {
            appendAssistantNotice('Unable to apply this hunk because the editor is not ready.');
            return;
        }

        const wasInactive = activePatchMessageIdRef.current !== messageId;
        if (wasInactive) {
            const activated = activatePatchMessage(messageId);
            if (!activated) {
                return;
            }
        }

        const tryApply = () => {
            const applied = action === 'accept'
                ? editorInstance.acceptPatchHunk(hunkId)
                : editorInstance.rejectPatchHunk(hunkId);

            if (!applied) {
                appendAssistantNotice('This hunk could not be applied. The code may have drifted. Ask Copilot again on the latest code.');
                return;
            }

            applyHunkStatus(hunkId, action === 'accept' ? HUNK_ACCEPTED : HUNK_REJECTED);
        };

        // If we just activated the patch, defer apply so the editor state is committed first
        if (wasInactive) {
            requestAnimationFrame(() => {
                tryApply();
            });
        } else {
            tryApply();
        }
    };

    const handleAllHunksDecision = (messageId, action) => {
        const editorInstance = context?.editorRef?.current;
        if (!editorInstance?.acceptPatchHunk || !editorInstance?.rejectPatchHunk) {
            appendAssistantNotice('Unable to apply hunks because the editor is not ready.');
            return;
        }

        const target = messagesRef.current.find((m) => m.id === messageId);
        if (!target?.hunks?.length) return;
        const pending = target.hunks.filter((h) => h.status === HUNK_PENDING);
        if (pending.length === 0) return;

        const wasInactive = activePatchMessageIdRef.current !== messageId;
        if (wasInactive) {
            const activated = activatePatchMessage(messageId);
            if (!activated) return;
        }

        const tryApplyAll = () => {
            const pendingIds = target.hunks.filter((h) => h.status === HUNK_PENDING).map((h) => h.id);
            if (pendingIds.length === 0) return;
            const sortedForAccept =
                action === 'accept'
                    ? target.hunks.filter((h) => h.status === HUNK_PENDING).sort((a, b) => a.start - b.start)
                    : target.hunks.filter((h) => h.status === HUNK_PENDING);
            const idsToApply = sortedForAccept.map((h) => h.id);
            let anyFailed = false;
            for (const hunkId of idsToApply) {
                const applied =
                    action === 'accept'
                        ? editorInstance.acceptPatchHunk(hunkId)
                        : editorInstance.rejectPatchHunk(hunkId);
                if (applied) {
                    applyHunkStatus(hunkId, action === 'accept' ? HUNK_ACCEPTED : HUNK_REJECTED);
                } else {
                    anyFailed = true;
                }
            }
            if (anyFailed) {
                appendAssistantNotice('Some hunks could not be applied. The code may have drifted.');
            }
        };

        if (wasInactive) {
            requestAnimationFrame(() => tryApplyAll());
        } else {
            tryApplyAll();
        }
    };

    const autoResizeTextarea = () => {
        const el = textareaRef.current;
        if (!el) return;

        el.style.height = 'auto';
        const next = el.scrollHeight;
        const max = 160;

        el.style.height = `${Math.min(next, max)}px`;
        el.style.overflowY = next > max ? 'auto' : 'hidden';
    };

    const handleInputChange = (e) => {
        setInput(e.target.value);
        requestAnimationFrame(autoResizeTextarea);
    };

    const handleSend = async () => {
        const text = input.trimEnd();
        if (!text.trim() || isLoading) return;

        updateMessages((prev) => [...prev, { id: nextMessageId(), role: 'user', content: text }]);
        setInput('');
        setIsLoading(true);

        requestAnimationFrame(() => {
            const el = textareaRef.current;
            if (!el) return;
            el.style.height = 'auto';
            el.style.overflowY = 'hidden';
        });

        try {
            const currentCode = getLiveCode();
            const history = messagesRef.current
                .filter((m) => m.role === 'user' || (m.role === 'assistant' && m.content))
                .map((m) => ({
                    role: m.role,
                    content: m.content,
                    ...(m.role === 'assistant' && m.code ? { code: m.code } : {}),
                }));
            const response = await fetch('http://localhost:8000/api/copilot/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: text,
                    current_code: currentCode,
                    conversation_history: history,
                }),
            });

            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }

            const data = await response.json();
            const messageId = nextMessageId();
            const patchOps = Array.isArray(data.patch_ops) ? data.patch_ops : [];
            const hunks = buildPatchHunks(messageId, patchOps);
            const usage = data.usage || null;
            const botMsg = {
                id: messageId,
                role: 'assistant',
                content: data.explanation || (hunks.length > 0 ? 'Proposed patch ready for review.' : 'No changes suggested.'),
                code: data.code || '',
                patchStats: data.patch_stats || null,
                baseCode: currentCode,
                hunks,
                needsApproval: hunks.length > 0,
                applied: false,
                discarded: false,
                usage: usage || null,
            };

            if (usage && typeof usage.input_tokens === 'number' && typeof usage.output_tokens === 'number') {
                setSessionUsage((prev) => {
                    const inSum = prev.input_tokens + (usage.input_tokens || 0);
                    const outSum = prev.output_tokens + (usage.output_tokens || 0);
                    const prevCost = prev.estimated_cost_usd != null && !Number.isNaN(prev.estimated_cost_usd) ? prev.estimated_cost_usd : 0;
                    const addCost = usage.estimated_cost_usd != null && !Number.isNaN(usage.estimated_cost_usd) ? usage.estimated_cost_usd : 0;
                    return {
                        input_tokens: inSum,
                        output_tokens: outSum,
                        total_tokens: inSum + outSum,
                        estimated_cost_usd: prevCost + addCost,
                    };
                });
            }

            updateMessages((prev) => [...prev, botMsg]);

            if (hunks.length > 0) {
                requestAnimationFrame(() => {
                    activatePatchMessage(botMsg.id, messagesRef.current, true);
                });
            }
        } catch (error) {
            appendAssistantNotice(`Error: ${error.message}`);
        } finally {
            setIsLoading(false);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    useEffect(() => {
        const handlePatchActionFromEditor = (event) => {
            const detail = event?.detail || {};
            if (detail.source !== 'editor' || !detail.hunkId || !detail.action) {
                return;
            }

            if (!detail.applied && detail.action === 'accept') {
                appendAssistantNoticeRef.current('A hunk failed to apply in the editor. The code may have changed.');
                return;
            }

            applyHunkStatusRef.current(
                detail.hunkId,
                detail.action === 'accept' ? HUNK_ACCEPTED : HUNK_REJECTED,
            );
        };

        window.addEventListener(PATCH_ACTION_EVENT, handlePatchActionFromEditor);
        return () => {
            window.removeEventListener(PATCH_ACTION_EVENT, handlePatchActionFromEditor);
        };
    }, []);

    useEffect(() => {
        if (!activePatchMessageId) {
            return;
        }

        const activeMessage = messages.find((message) => message.id === activePatchMessageId);
        const hasPending = !!activeMessage?.hunks?.some((hunk) => hunk.status === HUNK_PENDING);
        if (hasPending) {
            return;
        }

        const nextPending = findLatestPendingPatchMessage(messages);
        if (nextPending) {
            activatePatchMessage(nextPending.id, messages, true);
        } else {
            clearPatchReviewInEditor();
        }
    }, [messages, activePatchMessageId]);

    const contextRef = useRef(context);
    contextRef.current = context;
    useEffect(() => {
        return () => {
            const editorInstance = contextRef.current?.editorRef?.current;
            if (editorInstance?.clearPatchReview) {
                editorInstance.clearPatchReview();
            }
        };
    }, []);

    useEffect(() => {
        if (!isResizing) return;

        const handleMouseMove = (e) => {
            if (!sidebarRef.current) return;
            const newWidth = window.innerWidth - e.clientX;
            const minWidth = 240;
            const maxWidth = 800;
            const clampedWidth = Math.max(minWidth, Math.min(maxWidth, newWidth));
            setAICopilotSidebarWidth(clampedWidth);
        };

        const handleMouseUp = () => {
            setIsResizing(false);
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);

        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isResizing]);

    const handleResizeStart = (e) => {
        e.preventDefault();
        setIsResizing(true);
    };

    const placeholder = aiCopilotSidebarWidth < 300 ? 'Describe…' : 'Describe what you want';

    return (
        <nav
            ref={sidebarRef}
            className={cx(
                'bg-lineHighlight group overflow-x-auto h-full border-l border-white/10 relative',
                isAICopilotSidebarOpen ? '' : 'min-w-12 max-w-12'
            )}
            style={isAICopilotSidebarOpen ? { width: `${aiCopilotSidebarWidth}px` } : {}}
        >
            {isAICopilotSidebarOpen ? (
                <>
                    <div
                        onMouseDown={handleResizeStart}
                        className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-white/20 z-10"
                    />
                    <aside className="h-full bg-background text-foreground overflow-auto p-3 flex flex-col">
                        <div className="flex justify-between items-center mb-2">
                            <div className="flex flex-col gap-0.5">
                                <div className="font-bold">AI Copilot</div>
                                {(sessionUsage.total_tokens > 0) && (
                                    <div className="text-[11px] flex flex-wrap items-baseline gap-x-1.5">
                                        <span className="opacity-70">Session:</span>
                                        <span className="text-cyan-400/90 font-medium">{formatTokens(sessionUsage.total_tokens)}</span>
                                        <span className="opacity-70">tokens</span>
                                        {sessionUsage.estimated_cost_usd != null && !Number.isNaN(sessionUsage.estimated_cost_usd) && (
                                            <span className="text-amber-400/90 font-medium ml-0.5">{formatCost(sessionUsage.estimated_cost_usd)}</span>
                                        )}
                                    </div>
                                )}
                            </div>
                            <button
                                onClick={() => setIsAICopilotSidebarOpened(false)}
                                className={cx(
                                    'text-foreground max-h-8 min-h-8 max-w-8 min-w-8 items-center justify-center p-1.5 flex',
                                )}
                                aria-label="Close AI Copilot"
                            >
                                <XMarkIcon />
                            </button>
                        </div>

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
                                <div className="flex justify-start">
                                    <div className="max-w-[85%] rounded px-2 py-1 text-sm bg-background">
                                        <span className="opacity-50">Generating code...</span>
                                    </div>
                                </div>
                            )}
                        </div>

                        <div className="relative">
                            <textarea
                                ref={textareaRef}
                                value={input}
                                onChange={handleInputChange}
                                onKeyDown={handleKeyDown}
                                rows={1}
                                className="
                                w-full resize-none bg-black/30 text-foreground border
                                border-white/10 rounded-2xl px-4 pt-3 pb-3 pr-12
                                text-sm outline-none placeholder:text-foreground/40
                                overflow-hidden max-h-40
                            "
                                placeholder={placeholder}
                            />

                            <button
                                onClick={handleSend}
                                disabled={!input.trim() || isLoading}
                                className="
                                absolute right-2 bottom-3 h-8 w-8 rounded-full
                                bg-white text-black disabled:opacity-40
                                disabled:cursor-not-allowed flex items-center
                                justify-center
                            "
                                aria-label="Send"
                                title="Send"
                            >
                                <svg
                                    viewBox="0 0 24 24"
                                    className="h-4 w-4"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="2"
                                >
                                    <path d="M12 19V5" />
                                    <path d="M5 12l7-7 7 7" />
                                </svg>
                            </button>
                        </div>
                    </aside>
                </>
            ) : (
                <button
                    onClick={() => setIsAICopilotSidebarOpened(true)}
                    aria-label="open AI copilot panel"
                    className={cx(
                        'flex flex-col hover:bg-lineBackground items-center cursor-pointer justify-center w-full h-full',
                    )}
                >
                    <ChevronLeftIcon className="text-foreground opacity-50 w-6 h-6" />
                </button>
            )}
        </nav>
    );
}
