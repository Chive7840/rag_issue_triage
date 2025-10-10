export interface ViewerPluginHandle {
    onRouteChange?(pathname: string): void;
    dispose(): void;
}

export interface ViewerPlugin {
    id: string;
    matches(pathname: string): boolean;
    mount(container: HTMLElement, initialPath: string): ViewerPluginHandle;
}

type ActivePlugin = {
    plugin: ViewerPlugin;
    handle: ViewerPluginHandle;
};

const registeredPlugins: ViewerPlugin[] = [];
let initialized = false;
let active: ActivePlugin | null = null;
let container: HTMLElement | null = null;
let originalDisplay: string | null = null;

function isFeatureEnabled(): boolean {
    if (typeof window === 'undefined') {
        return false;
    }
    const flag = (window as unknown as { originSafeViewer?: boolean }).originSafeViewer;
    return flag !== false;
}

function ensureContainer(): HTMLElement {
    if (container && document.body.contains(container)) {
        return container;
    }
    container = document.createElement('div');
    container.id = 'origin-safe-viewer-root';
    container.style.minHeight = '100vh';
    container.style.position = 'relative';
    container.style.zIndex = '100';
    document.body.appendChild(container);
    return container;
}

function hideHostApp(): void {
    const host = document.getElementById('root') as HTMLElement | null;
    if (!host) {
        return;
    }
    if (host.dataset.originSafeHidden === '1') {
        return;
    }
    originalDisplay = host.style.display || null;
    host.style.display = 'none';
    host.dataset.originSafeHidden = '1';
}

function restoreHostApp(): void {
    const host = document.getElementById('root') as HTMLElement | null;
    if (host && host.dataset.originSafeHidden === '1') {
        if (originalDisplay !== null) {
            host.style.display = originalDisplay;
        } else {
            host.style.removeProperty('display');
        }
        delete host.dataset.originSafeHidden;
    }
    originalDisplay = null;
    if (container && container.parentElement) {
        container.parentElement.removeChild(container);
    }
    container = null;
}

function notifyRouteChange(pathname: string): void {
    if (!isFeatureEnabled()) {
        return;
    }
    const plugin = registeredPlugins.find((candidate) => candidate.matches(pathname)) || null;
    if (!plugin) {
        if (active) {
            active.handle.dispose();
            active = null;
            restoreHostApp();
        }
        return;
    }
    const hostContainer = ensureContainer();
    if (!active || active.plugin.id !== plugin.id) {
        if (active) {
            active.handle.dispose();
        }
        hideHostApp();
        const handle = plugin.mount(hostContainer, pathname);
        active = { plugin, handle };
        return;
    }
    hideHostApp();
    active.handle.onRouteChange?.(pathname);
}

function ensureRouteObserver(): void {
    if (initialized || typeof window === 'undefined' || typeof history === 'undefined') {
        return;
    }
    initialized = true;
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;

    history.pushState = function pushState(...args) {
        const result = originalPushState.apply(this, args as Parameters<typeof history.pushState>);
        notifyRouteChange(window.location.pathname);
        return result;
    };

    history.replaceState = function replaceState(...args) {
        const result = originalReplaceState.apply(this, args as Parameters<typeof history.replaceState>);
        notifyRouteChange(window.location.pathname);
        return result;
    };

    window.addEventListener('popstate', () => notifyRouteChange(window.location.pathname));
    window.addEventListener('hashchange', () => notifyRouteChange(window.location.pathname));
}

export function registerViewerPlugin(plugin: ViewerPlugin): void {
    if (typeof window === 'undefined') {
        return;
    }
    if (registeredPlugins.some((existing) => existing.id === plugin.id)) {
        return;
    }
    registeredPlugins.push(plugin);
    ensureRouteObserver();
    notifyRouteChange(window.location.pathname);
}

// BEGIN CODEGEN BLOCK: ORIGIN SAFE VIEWER REGISTRATION
import { originSafeViewerPlugin } from '../plugins/origin-safe-viewer/plugin';

if (isFeatureEnabled()) {
    registerViewerPlugin(originSafeViewerPlugin);
}
// END CODEGEN BLOCK: ORIGIN SAFE VIEWER REGISTRATION