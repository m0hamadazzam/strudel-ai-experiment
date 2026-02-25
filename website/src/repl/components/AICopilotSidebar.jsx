import { ChevronLeftIcon, XMarkIcon } from '@heroicons/react/16/solid';
import cx from '@src/cx.mjs';
import { setAICopilotSidebarWidth, setIsAICopilotSidebarOpened, useSettings } from '@src/settings.mjs';
import { useEffect, useRef, useState } from 'react';

const MAX_PREVIEW_LINES = 120;
const MAX_PREVIEW_LINES_PER_OP = 40;

function splitDiffLines(text) {
    if (!text) return [];
    const normalized = text.replace(/\r\n/g, '\n');
    const lines = normalized.split('\n');
    if (lines[lines.length - 1] === '') {
        lines.pop();
    }
    return lines;
}

function buildPatchPreview(patchOps) {
    const previewLines = [];
    let truncated = false;

    for (const op of patchOps || []) {
        const removed = splitDiffLines(op.old_text || '');
        const added = splitDiffLines(op.new_text || '');

        const removedPreview = removed.slice(0, MAX_PREVIEW_LINES_PER_OP);
        const addedPreview = added.slice(0, MAX_PREVIEW_LINES_PER_OP);

        for (const line of removedPreview) {
            previewLines.push({ type: 'remove', text: line });
            if (previewLines.length >= MAX_PREVIEW_LINES) {
                truncated = true;
                return { previewLines, truncated };
            }
        }

        for (const line of addedPreview) {
            previewLines.push({ type: 'add', text: line });
            if (previewLines.length >= MAX_PREVIEW_LINES) {
                truncated = true;
                return { previewLines, truncated };
            }
        }

        if (removed.length > removedPreview.length || added.length > addedPreview.length) {
            truncated = true;
        }
    }

    return { previewLines, truncated };
}

function applyPatchToEditor(editorInstance, patchOps) {
    const editorView = editorInstance?.editor;
    if (!editorView || !Array.isArray(patchOps) || patchOps.length === 0) {
        return false;
    }

    const ordered = [...patchOps].sort((a, b) => a.start - b.start);
    const baseLength = editorView.state.doc.length;
    let previousEnd = -1;

    for (const op of ordered) {
        if (typeof op.start !== 'number' || typeof op.end !== 'number') {
            return false;
        }
        if (op.start < 0 || op.end < op.start || op.end > baseLength) {
            return false;
        }
        if (op.start < previousEnd) {
            return false;
        }
        previousEnd = op.end;
    }

    editorView.dispatch({
        changes: ordered.map((op) => ({
            from: op.start,
            to: op.end,
            insert: op.new_text || '',
        })),
    });

    return true;
}

export default function AICopilotSidebar({ context }) {
    const settings = useSettings();
    const { isAICopilotSidebarOpen, aiCopilotSidebarWidth } = settings;
    const [input, setInput] = useState('');
    const [messages, setMessages] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const textareaRef = useRef(null);
    const [isResizing, setIsResizing] = useState(false);
    const sidebarRef = useRef(null);

    const autoResizeTextarea = () => {
        const el = textareaRef.current;
        if (!el) return;

        el.style.height = 'auto';

        const next = el.scrollHeight;
        const max = 160; // matches Tailwind max-h-40 (~160px)

        el.style.height = `${Math.min(next, max)}px`;
        el.style.overflowY = next > max ? 'auto' : 'hidden';
    };

    const handleInputChange = (e) => {
        setInput(e.target.value);
        requestAnimationFrame(autoResizeTextarea);
    };

    const handleApplyPatch = (index, msg) => {
        const editorInstance = context?.editorRef?.current;
        if (!editorInstance) {
            setMessages((prev) => [
                ...prev,
                { role: 'assistant', content: 'Unable to apply patch: editor is not ready.' },
            ]);
            return;
        }

        const liveCode = editorInstance.code ?? context?.activeCode ?? '';
        if (typeof msg.baseCode === 'string' && liveCode !== msg.baseCode) {
            setMessages((prev) => [
                ...prev,
                {
                    role: 'assistant',
                    content: 'Cannot apply this patch because the editor changed since it was generated. Ask Copilot again on the latest code.',
                },
            ]);
            return;
        }

        let applied = false;
        if (Array.isArray(msg.patchOps) && msg.patchOps.length > 0) {
            applied = applyPatchToEditor(editorInstance, msg.patchOps);
        }

        if (!applied && msg.code) {
            editorInstance.setCode(msg.code);
            applied = true;
        }

        if (!applied) {
            setMessages((prev) => [
                ...prev,
                { role: 'assistant', content: 'No changes to apply.' },
            ]);
            return;
        }

        setMessages((prev) =>
            prev.map((m, i) =>
                i === index
                    ? { ...m, needsApproval: false, applied: true, discarded: false }
                    : m
            )
        );
    };

    const handleDiscardPatch = (index) => {
        setMessages((prev) =>
            prev.map((m, i) =>
                i === index
                    ? { ...m, needsApproval: false, applied: false, discarded: true }
                    : m
            )
        );
    };

    const handleSend = async () => {
        const text = input.trimEnd();
        if (!text.trim() || isLoading) return;

        const userMsg = { role: 'user', content: text };
        setMessages((prev) => [...prev, userMsg]);
        setInput('');
        setIsLoading(true);

        requestAnimationFrame(() => {
            const el = textareaRef.current;
            if (!el) return;
            el.style.height = 'auto';
            el.style.overflowY = 'hidden';
        });

        try {
            const currentCode = context?.editorRef?.current?.code ?? context?.activeCode ?? '';
            const response = await fetch('http://localhost:8000/api/copilot/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: text,
                    current_code: currentCode,
                }),
            });

            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }

            const data = await response.json();
            const patchOps = Array.isArray(data.patch_ops) ? data.patch_ops : [];
            const patchStats = data.patch_stats || null;
            const hasPatch = patchOps.length > 0;
            const { previewLines, truncated } = buildPatchPreview(patchOps);
            const content = data.explanation || (hasPatch ? 'Proposed patch ready for review.' : 'No changes suggested.');
            const botMsg = {
                role: 'assistant',
                content,
                code: data.code || '',
                patchOps,
                patchStats,
                previewLines,
                previewTruncated: truncated,
                baseCode: currentCode,
                needsApproval: hasPatch,
            };

            setMessages((prev) => [...prev, botMsg]);
        } catch (error) {
            const errorMsg = {
                role: 'assistant',
                content: `Error: ${error.message}`,
            };
            setMessages((prev) => [...prev, errorMsg]);
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
                            <div className="font-bold">AI Copilot</div>
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
                            {messages.map((msg, index) => {
                                const isUser = msg.role === 'user';
                                const hasPatch = Array.isArray(msg.patchOps) && msg.patchOps.length > 0;
                                const needsApproval = msg.needsApproval && (hasPatch || msg.code);
                                const hasPatchStats = msg.patchStats && typeof msg.patchStats.operations === 'number';

                                return (
                                    <div
                                        key={index}
                                        className={
                                            `flex ${isUser ?
                                                'justify-end' : 'justify-start'}`
                                        }
                                    >
                                        <div
                                            className={
                                                `max-w-[85%] rounded px-2 py-1 
                                            text-sm whitespace-pre-wrap ${isUser ?
                                                    'bg-white/10' : 'bg-background'
                                                }`
                                            }
                                        >
                                            {msg.content}
                                            {hasPatchStats && (
                                                <div className="mt-2 text-[11px] opacity-70">
                                                    {`${msg.patchStats.operations} edits · +${msg.patchStats.additions} / -${msg.patchStats.deletions}`}
                                                </div>
                                            )}
                                            {Array.isArray(msg.previewLines) && msg.previewLines.length > 0 && (
                                                <div className="mt-2 rounded border border-white/10 overflow-hidden font-mono text-[11px]">
                                                    {msg.previewLines.map((line, lineIndex) => (
                                                        <div
                                                            key={`${index}-${lineIndex}`}
                                                            className={
                                                                line.type === 'add'
                                                                    ? 'px-2 py-0.5 bg-emerald-500/10 text-emerald-200'
                                                                    : 'px-2 py-0.5 bg-red-500/10 text-red-200'
                                                            }
                                                        >
                                                            {(line.type === 'add' ? '+ ' : '- ') + (line.text || ' ')}
                                                        </div>
                                                    ))}
                                                    {msg.previewTruncated && (
                                                        <div className="px-2 py-1 text-[10px] opacity-60 bg-white/5">
                                                            Diff preview truncated
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                            {needsApproval && (
                                                <div className="mt-2 flex gap-2">
                                                    <button
                                                        onClick={() => handleApplyPatch(index, msg)}
                                                        className="flex-1 px-3 py-1.5 rounded bg-white text-black text-xs font-medium hover:bg-white/90"
                                                    >
                                                        Apply patch
                                                    </button>
                                                    <button
                                                        onClick={() => handleDiscardPatch(index)}
                                                        className="flex-1 px-3 py-1.5 rounded border border-white/20 text-xs font-medium hover:bg-white/10"
                                                    >
                                                        Discard
                                                    </button>
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
