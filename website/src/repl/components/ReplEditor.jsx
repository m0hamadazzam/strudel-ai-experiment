import Loader from '@src/repl/components/Loader';
import { HorizontalPanel, VerticalPanel } from '@src/repl/components/panel/Panel';
import { Code } from '@src/repl/components/Code';
import UserFacingErrorMessage from '@src/repl/components/UserFacingErrorMessage';
import { Header } from './Header';
import { useSettings } from '@src/settings.mjs';
import AICopilotSidebar from './AICopilotSidebar';

export default function ReplEditor(Props) {
  const { context, ...editorProps } = Props;
  const { containerRef, editorRef, error, init, pending } = context;
  const settings = useSettings();
  const { panelPosition, isZen } = settings;

  return (
    <div className="h-full flex flex-col relative" {...editorProps}>
      <Loader active={pending} />
      <Header context={context} />

      {/* Main row: editor + existing right panel + AI sidebar */}
      <div className="grow flex relative overflow-hidden">
        {/* Editor must be allowed to shrink in flex layouts (critical for CodeMirror) */}
        <div className="flex-1 min-w-0">
          <Code containerRef={containerRef} editorRef={editorRef} init={init} />
        </div>

        {!isZen && panelPosition === 'right' && <VerticalPanel context={context} />}

        {/* Your new right sidebar */}
        {!isZen && <AICopilotSidebar context={context} />}
      </div>

      <UserFacingErrorMessage error={error} />

      {!isZen && panelPosition === 'bottom' && <HorizontalPanel context={context} />}
    </div>
  );
}
