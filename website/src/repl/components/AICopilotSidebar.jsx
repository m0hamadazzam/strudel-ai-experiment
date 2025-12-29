import { ChevronLeftIcon, XMarkIcon } from '@heroicons/react/16/solid';
import cx from '@src/cx.mjs';
import { setAICopilotSidebarWidth, setIsAICopilotSidebarOpened, useSettings } from '@src/settings.mjs';
import { useEffect, useRef, useState } from 'react';

export default function AICopilotSidebar() {
    const settings = useSettings();
    const { isAICopilotSidebarOpen, aiCopilotSidebarWidth } = settings;
    const [input, setInput] = useState('');
    const [messages, setMessages] = useState([]);
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

    const handleSend = () => {
        const text = input.trimEnd();
        if (!text.trim()) return;

        const userMsg = { role: 'user', content: text };
        const botMsg = {
            role: 'assistant',
            content: 'Got it. (stub) What do you want to change?'
        };

        setMessages((prev) => [...prev, userMsg, botMsg]);
        setInput('');

        requestAnimationFrame(() => {
            const el = textareaRef.current;
            if (!el) return;
            el.style.height = 'auto';
            el.style.overflowY = 'hidden';
        });

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
                                        </div>
                                    </div>
                                );
                            })}
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
                                disabled={!input.trim()}
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
