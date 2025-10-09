import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from 'react';

interface IssueViewerComment {
    author?: string | null;
    body: string;
    body_html: string;
    created_at?: string | null;
}

interface IssueViewerRecord {
    id: number;
    source: string;
    route: string;
    origin_url?: string | null;
    title: string;
    body: string;
    body_html: string;
    repo?: string | null;
    status?: string | null;
    priority?: string | null;
    labels: string[];
    created_at?: string | null;
    determinism: string;
    comments: IssueViewerComment[];
}

interface IssueSearchItem {
    id: number;
    source: string;
    route: string;
    origin_url?: string | null;
    title: string;
    status?: string | null;
    priority?: string | null;
    labels: string[];
    repo?: string | null;
    project?: string | null;
    created_at?: string | null;
}

