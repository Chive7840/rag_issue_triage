import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { ViewerPlugin, ViewerPluginHandle } from '../../app/register-plugins';
import { OriginSafeViewerApp } from './OriginSafeViewerApp';

let stylesInjected = false;

function ensureStyles(): void {
    if (stylesInjected) {
        return;
    }
    const style = document.createElement('style');
    style.id = 'origin-safe-viewer-styles';
    style.textContent = `
        #origin-safe-viewer-root {
            background: #0b1120;
            color: #e2e8f0;
            font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
        }
        .origin-safe-viewer {
            display: flex;
            flex-direction: column;
            min-height: 100vh;
            box-sizing: border-box;
        }
        .origin-safe-viewer * {
            box-sizing: border-box;
        }
        .origin-safe-viewer__header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem 1.5rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.3);
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(6px);
        }
        .origin-safe-viewer__title-group {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .origin-safe-viewer__title {
            margin: 0;
            font-size: 1.5rem;
            font-weight: 600;
        }
        .origin-safe-viewer__close {
            border: 1px solid rgba(148, 163, 184, 0.4);
            background: transparent;
            color: inherit;
            padding: 0.35rem 0.75rem;
            border-radius: 999px;
            cursor: pointer;
        }
        .origin-safe-viewer__close:hover {
            border-color: rgba(148, 163, 184, 0.7);
        }
        .origin-safe-viewer__origin-button {
            border: 1px solid rgba(148, 163, 184, 0.4);
            background: rgba(15, 23, 42, 0.7);
            color: rgba(148, 163, 184, 0.9);
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
        }
        .origin-safe-viewer__content {
            display: flex;
            flex: 1;
            min-height: 0;
        }
        .origin-safe-viewer__sidebar {
            width: 340px;
            padding: 1.5rem;
            border-right: 1px solid rgba(148, 163, 184, 0.3);
            background: rgba(15, 23, 42, 0.9);
            overflow-y: auto;
            gap: 1.5rem;
            display: flex;
            flex-direction: column;
        }
        .origin-safe-viewer__search h2,
        .origin-safe-viewer__results h2,
        .origin-safe-viewer__routes h2 {
            margin-top: 0;
            font-size: 1rem;
            font-weight: 600;
            color: #cbd5f5;
        }
        .origin-safe-viewer__search input,
        .origin-safe-viewer__search select {
            width: 100%;
            margin-top: 0.5rem;
            padding: 0.5rem 0.75rem;
            border-radius: 0.5rem;
            border: 1px solid rgba(148, 163, 184, 0.4);
            background: rgba(15, 23, 42, 0.6);
            color: inherit;
        }
        .origin-safe-viewer__search-submit {
            width: 100%;
            margin-top: 0.75rem;
            padding: 0.6rem 0.75rem;
            border-radius: 0.5rem;
            border: none;
            background: linear-gradient(120deg, #6366f1, #8b5cf6);
            color: #fff;
            cursor: pointer;
        }
        .origin-safe-viewer__search-submit:disabled {
            opacity: 0.6;
            cursor: default;
        }
        .origin-safe-viewer__results ul,
        .origin-safe-viewer__routes ul {
            list-style: none;
            padding: 0;
            margin: 0;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }
        .origin-safe-viewer__results button,
        .origin-safe-viewer__routes button {
            width: 100%;
            text-align: left;
            border: 1px solid transparent;
            background: rgba(15, 23, 42, 0.6);
            color: inherit;
            padding: 0.5rem 0.75rem;
            border-radius: 0.5rem;
            cursor: pointer;
        }
        .origin-safe-viewer__results button.active,
        .origin-safe-viewer__routes button.active {
            border-color: rgba(99, 102, 241, 0.7);
            background: rgba(99, 102, 241, 0.2);
        }
        .origin-safe-viewer__result-title {
            display: block;
            font-weight: 600;
        }
        .origin-safe-viewer__result-meta {
            display: block;
            font-size: 0.85rem;
            color: rgba(148, 163, 184, 0.8);
        }
        .origin-safe-viewer__main {
            flex: 1;
            padding: 2rem;
            overflow-y: auto;
        }
        .origin-safe-viewer__issue h2 {
            margin-top: 0;
            font-size: 1.75rem;
        }
        .origin-safe-viewer__banner {
            font-size: 0.9rem;
            color: #f59e0b;
            margin-bottom: 0.75rem;
        }
        .origin-safe-viewer__meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 1rem;
        }
        .origin-safe-viewer__pill {
            padding: 0.35rem 0.75rem;
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.15);
            font-size: 0.85rem;
        }
        .origin-safe-viewer__labels {
            list-style: none;
            display: flex;
            gap: 0.5rem;
            padding: 0;
            margin: 0 0 1.25rem 0;
        }
        .origin-safe-viewer__labels li {
            padding: 0.35rem 0.75rem;
            border-radius: 999px;
            background: rgba(94, 234, 212, 0.25);
        }
        .origin-safe-viewer__body {
            line-height: 1.6;
            background: rgba(15, 23, 42, 0.6);
            padding: 1rem;
            border-radius: 0.75rem;
            margin-bottom: 2rem;
        }
        .origin-safe-viewer__body p {
            margin: 0 0 1rem 0;
        }
        .origin-safe-viewer__comments ul {
            list-style: none;
            padding: 0;
            margin: 0;
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }
        .origin-safe-viewer__comment-header {
            display: flex;
            justify-content: space-between;
            font-size: 0.9rem;
            margin-bottom: 0.25rem;
        }
        .origin-safe-viewer__comment-body {
            background: rgba(15, 23, 42, 0.6);
            padding: 0.75rem;
            border-radius: 0.75rem;
            line-height: 1.5;
        }
        .origin-safe-viewer__origin-url {
            font-size: 0.85rem;
            color: rgba(148, 163, 184, 0.9);
        }
        .origin-safe-viewer__error {
            color: #f87171;
            font-size: 0.9rem;
        }
        .origin-safe-viewer__empty {
            color: rgba(148, 163, 184, 0.9);
            font-size: 0.9rem;
        }
        @media (max-width: 960px) {
            .origin-safe-viewer__content {
                flex-direction: column;
            }
            .origin-safe-viewer__sidebar {
                width: 100%;
                border-right: none;
                border-bottom: 1px solid rgba(148, 163, 184, 0.3);
            }
        }
    `;
    document.head.appendChild(style);
    stylesInjected = true;
}

export const originSafeViewerPlugin: ViewerPlugin = {
    id: 'origin-safe-viewer',
    matches(pathname: string): boolean {
        return pathname.startsWith('/gh/') || pathname.startsWith('/jira/');
    },
    mount(container: HTMLElement, initialPath: string): ViewerPluginHandle {
        ensureStyles();
        const root = createRoot(container);
        let updateRoute: ((path: string) => void) | null = null;

        function Host() {
            const [route, setRoute] = useState(initialPath);
            useEffect(() => {
                updateRoute = setRoute;
                return () => {
                    updateRoute = null;
                };
            }, []);
            return <OriginSafeViewerApp route={route} />;
        }

        root.render(<Host />);

        return {
            onRouteChange(newPath: string) {
                updateRoute?.(newPath);
            },
            dispose() {
                root.unmount();
            },
        };
    },
};

export default originSafeViewerPlugin;