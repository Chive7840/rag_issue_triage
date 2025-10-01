import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            '/search': 'http://api:8000',
            '/triage': 'http://api:8000',
            '/webhooks': 'http://api:8000'
        }
    }
});