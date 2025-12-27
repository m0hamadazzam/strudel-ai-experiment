export default function AICopilotSidebar() {
    return (
        <aside className="w-[360px] h-full border-l border-white/10 bg-background text-foreground overflow-auto p-3">
            <div className="font-bold mb-2 text-foreground">AI Copilot</div>

            <div className="text-sm text-foreground/70 mb-3">
                Sidebar placeholder. Chat UI will go here.
            </div>

            <div className="flex gap-2">
                <input
                    className="flex-1 bg-black/30 text-foreground border border-white/10 rounded px-2 py-1 text-sm outline-none placeholder:text-foreground/40"
                    placeholder="Describe what you want…"
                />
                <button className="px-3 py-1 rounded bg-white/10 hover:bg-white/20 text-sm text-foreground">
                    Send
                </button>
            </div>
        </aside>
    );
}
