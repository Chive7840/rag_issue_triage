/// <reference types="vite/types/importMeta.d.ts" />

import axios from 'axios';

const baseURL = (() => {

    const explicit = import.meta.env.VITE_API_BASE_URL?.trim();
    if (explicit) {
        return explicit.replace(/\/$/, '');
    }

    if (import.meta.env.DEV){

        return '';
    }

    try {
        const current = new URL(window.location.origin);
        const overridePort = import.meta.env.VITE_API_PORT?.trim();
        if (overridePort) {
            current.port = overridePort;
            return current.origin;
        }

        if (current.port == '4173') {
            current.port = '8000';
            return current.origin;
        }

        return current.origin;
    } catch (error) {
        console.warn('Unable to determine API base URL, falling back to same origin.', error);
        return '';
    }
})();

const apiClient = axios.create({
    baseURL: baseURL || undefined,
});

export function resolveApiUrl(path: string): string {
    if  (!path) {
        return baseURL || path;
    }
    if (/^https?:\/\//i.test(path)) {
        return path;
    }
    const normalized = path.startsWith('/') ? path : `/${path}`;
    if (!baseURL) {
        return normalized;
    }
    return `${baseURL}${normalized}`;
}

export { baseURL as apiBaseURL };

export default apiClient;
