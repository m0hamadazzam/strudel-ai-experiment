import { ChevronLeftIcon, XMarkIcon } from '@heroicons/react/16/solid';
import cx from '@src/cx.mjs';
import { setAICopilotSidebarWidth, setIsAICopilotSidebarOpened, useSettings } from '@src/settings.mjs';
import { useEffect, useRef, useState } from 'react';
import CopilotInput from './CopilotInput';
import CopilotMessageList from './CopilotMessageList';
import CopilotThinkingIndicator from './CopilotThinkingIndicator';
import { HUNK_ACCEPTED, HUNK_PENDING, HUNK_REJECTED, summarizeHunks, buildHunkPreview } from './copilotShared';

const PATCH_ACTION_EVENT = 'strudel-ai-patch-hunk-action';
const COPILOT_API_BASE = import.meta.env.PUBLIC_COPILOT_API_BASE || 'http://localhost:8000';

function copilotApiUrl(path) {
    return `${COPILOT_API_BASE}${path}`;
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

function sanitizeReasoningText(text) {
    if (!text) return '';
    return text.replace(/\*\*/g, '');
}

async function readNdjsonStream(response, onEvent) {
    const reader = response.body?.getReader();
    if (!reader) {
        throw new Error('Streaming response body is unavailable.');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

        let newlineIndex = buffer.indexOf('\n');
        while (newlineIndex !== -1) {
            const line = buffer.slice(0, newlineIndex).trim();
            buffer = buffer.slice(newlineIndex + 1);

            if (line) {
                onEvent(JSON.parse(line));
            }

            newlineIndex = buffer.indexOf('\n');
        }

        if (done) {
            break;
        }
    }

    const trailingLine = buffer.trim();
    if (trailingLine) {
        onEvent(JSON.parse(trailingLine));
    }
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
    const [liveAssistant, setLiveAssistant] = useState(null);
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
    const requestAbortRef = useRef(null);
    const feedbackInFlightRef = useRef(new Set());

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

    const accumulateSessionUsage = (usage) => {
        if (!usage || typeof usage.input_tokens !== 'number' || typeof usage.output_tokens !== 'number') {
            return;
        }

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
    };

    const buildAssistantMessage = (data, currentCode) => {
        const messageId = nextMessageId();
        const patchOps = Array.isArray(data.patch_ops) ? data.patch_ops : [];
        const hunks = buildPatchHunks(messageId, patchOps);
        return {
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
            usage: data.usage || null,
            interactionId: typeof data.interaction_id === 'number' ? data.interaction_id : null,
            feedbackSent: false,
            feedbackAttempted: false,
        };
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
        setLiveAssistant({
            phase: 'Preparing request',
            reasoning: '',
            isWebSearching: false,
        });

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
            const abortController = new AbortController();
            requestAbortRef.current = abortController;

            const response = await fetch(copilotApiUrl('/api/copilot/chat/stream'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                signal: abortController.signal,
                body: JSON.stringify({
                    message: text,
                    current_code: currentCode,
                    conversation_history: history,
                }),
            });

            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }

            let finalResponse = null;
            await readNdjsonStream(response, (event) => {
                if (!event || typeof event !== 'object') {
                    return;
                }

                if (event.type === 'status') {
                    setLiveAssistant((prev) => {
                        if (!prev) return prev;
                        const message = event.message || prev.phase;
                        return {
                            ...prev,
                            phase: message,
                            isWebSearching: event.phase === 'web_search',
                        };
                    });
                    return;
                }

                if (event.type === 'reasoning') {
                    setLiveAssistant((prev) => {
                        if (!prev) return prev;
                        return {
                            ...prev,
                            reasoning: `${prev.reasoning || ''}${event.delta || ''}`,
                        };
                    });
                    return;
                }

                if (event.type === 'final') {
                    finalResponse = event.response || null;
                    return;
                }

                if (event.type === 'error') {
                    throw new Error(event.message || 'The copilot stream failed.');
                }
            });

            if (!finalResponse) {
                throw new Error('Copilot stream ended without a final response.');
            }

            const botMsg = buildAssistantMessage(finalResponse, currentCode);
            accumulateSessionUsage(botMsg.usage);

            updateMessages((prev) => [...prev, botMsg]);

            if (botMsg.hunks.length > 0) {
                requestAnimationFrame(() => {
                    activatePatchMessage(botMsg.id, messagesRef.current, true);
                });
            }
        } catch (error) {
            if (error.name !== 'AbortError') {
                appendAssistantNotice(`Error: ${error.message}`);
            }
        } finally {
            requestAbortRef.current = null;
            setLiveAssistant(null);
            setIsLoading(false);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const markFeedbackSent = (messageId) => {
        updateMessages((prev) => prev.map((message) => (
            message.id === messageId ? { ...message, feedbackSent: true } : message
        )));
    };

    const markFeedbackAttempted = (messageId) => {
        updateMessages((prev) => prev.map((message) => (
            message.id === messageId ? { ...message, feedbackAttempted: true } : message
        )));
    };

    useEffect(() => {
        const completedMessages = messages.filter((message) => {
            if (!message?.interactionId || message.feedbackSent || message.feedbackAttempted || !Array.isArray(message.hunks) || message.hunks.length === 0) {
                return false;
            }
            const summary = summarizeHunks(message.hunks);
            return summary.pending === 0 && (summary.accepted > 0 || summary.rejected > 0);
        });

        for (const message of completedMessages) {
            if (feedbackInFlightRef.current.has(message.id)) {
                continue;
            }

            const summary = summarizeHunks(message.hunks);
            const status = summary.accepted > 0 && summary.rejected > 0
                ? 'partial'
                : summary.accepted > 0
                    ? 'accepted'
                    : 'rejected';

            feedbackInFlightRef.current.add(message.id);
            markFeedbackAttempted(message.id);
            fetch(copilotApiUrl(`/api/copilot/interactions/${message.interactionId}/feedback`), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                keepalive: true,
                body: JSON.stringify({ status }),
            })
                .then((response) => {
                    if (!response.ok) {
                        throw new Error(`Feedback API error: ${response.status}`);
                    }
                    markFeedbackSent(message.id);
                })
                .catch((error) => {
                    console.warn('Copilot feedback request failed', error);
                })
                .finally(() => {
                    feedbackInFlightRef.current.delete(message.id);
                });
        }
    }, [messages]);

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
            requestAbortRef.current?.abort();
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
            <style>{`
                @keyframes strudelThinkingScan {
                    0% { transform: translateX(-140%); opacity: 0; }
                    15% { opacity: 1; }
                    50% { transform: translateX(0%); opacity: 1; }
                    85% { opacity: 1; }
                    100% { transform: translateX(140%); opacity: 0; }
                }
            `}</style>
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

                        <CopilotMessageList
                            messages={messages}
                            activePatchMessageId={activePatchMessageId}
                            activatePatchMessage={activatePatchMessage}
                            handleAllHunksDecision={handleAllHunksDecision}
                            handleHunkDecision={handleHunkDecision}
                        />

                        {isLoading && <CopilotThinkingIndicator liveAssistant={liveAssistant} />}

                        <CopilotInput
                            input={input}
                            isLoading={isLoading}
                            placeholder={placeholder}
                            textareaRef={textareaRef}
                            onChange={handleInputChange}
                            onKeyDown={handleKeyDown}
                            onSend={handleSend}
                        />
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
