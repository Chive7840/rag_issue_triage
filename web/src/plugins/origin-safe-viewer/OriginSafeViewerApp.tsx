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
    project?: string | null;
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

interface IssueSearchResponse {
    items: IssueSearchItem[];
}

type SearchForm = {
    q: string;
    source: string;
    repo: string;
    project: string;
    label: string;
    state: string;
    priority: string;
};

const defaultSearchForm: SearchForm = {
    q: '',
    source: '',
    repo: '',
    project: '',
    label: '',
    state: '',
    priority: '',
};

interface OriginSafeViewerAppProps {
    route: string;
}

function formatDate(value?: string | null): string {
    if (!value) {
        return '';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return value;
    }
    return parsed.toLocaleString();
}

export function OriginSafeViewerApp({ route }: OriginSafeViewerAppProps) {
    const [issue, setIssue] = useState<IssueViewerRecord | null>(null);
    const [issueError, setIssueError] = useState<string | null>(null);
    const [issueLoading, setIssueLoading] = useState<boolean>(false);
    const [routes, setRoutes] = useState<string[]>([]);
    const [routesError, setRoutesError] = useState<string | null>(null);
    const [searchForm, setSearchForm] = useState<SearchForm>(defaultSearchForm);
    const [searchRequest, setSearchRequest] = useState<SearchForm>(defaultSearchForm);
    const [searchResults, setSearchResults] = useState<IssueSearchItem[]>([]);
    const [searchLoading, setSearchLoading] = useState<boolean>(false);
    const [searchError, setSearchError] = useState<string | null>(null);
    const contentRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        let cancelled = false;
        setIssueLoading(true);
        setIssueError(null);
        const controller = new AbortController();
        const encoded = encodeURIComponent(route);
        fetch(`/api/issues/by-route/${encoded}`, { signal: controller.signal })
            .then(async (response) => {
                if (!response.ok) {
                    if (response.status === 404) {
                        const body = await response.json().catch(() => ({ error: 'Not found' }));
                        const errorMessage = typeof body?.hint === 'string' ? `${body.error}: ${body.hint}` : body.error || 'Issue not found';
                        throw new Error(errorMessage);
                    }
                    throw new Error(`Failed to load issue (${response.status})`);
                }
                return response.json() as Promise<IssueViewerRecord>;
            })
            .then((data) => {
                if (!cancelled) {
                    setIssue(data);
                }
            })
            .catch((error: Error) => {
                if (!cancelled) {
                    setIssue(null);
                    setIssueError(error.message);
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setIssueLoading(false);
                }
            });
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [route]);

    useEffect(() => {
        let cancelled = false;
        fetch('/api/routes')
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`Failed to load routes (${response.status})`);
                }
                return response.json() as Promise<{ route: string }[]>;
            })
            .then((data) => {
                if (!cancelled) {
                    setRoutes(data.map((item) => item.route));
                }
            })
            .catch((error: Error) => {
                if (!cancelled) {
                    setRoutesError(error.message);
                }
            });
        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        let cancelled = false;
        setSearchLoading(true);
        setSearchError(null);
        const params = new URLSearchParams();
        (Object.keys(searchRequest) as (keyof SearchForm)[]).forEach((key) => {
            const value = searchRequest[key]?.trim();
            if (value) {
                params.append(key, value);
            }
        });
        const query = params.toString();
        const url = query ? `/api/issues/search?${query}` : '/api/issues/search';
        fetch(url)
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`Failed to load search (${response.status})`);
                }
                return response.json() as Promise<IssueSearchResponse>;
            })
            .then((data) => {
                if (!cancelled) {
                    setSearchResults(data.items);
                }
            })
            .catch((error: Error) => {
                if (!cancelled) {
                    setSearchError(error.message);
                    setSearchResults([]);
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setSearchLoading(false);
                }
            });
        return () => {
            cancelled = true;
        };
    }, [searchRequest]);

    useEffect(() => {
        const node = contentRef.current;
        if (!node) {
            return undefined;
        }
        const handler = (event: MouseEvent) => {
            const target = event.target as HTMLElement | null;
            if (!target) {
                return;
            }
            const anchor = target.closest('a');
            if (!(anchor instanceof HTMLAnchorElement)) {
                return;
            }
            let href = anchor.getAttribute('href');
            if (!href) {
                return;
            }
            if (href.startsWith(window.location.origin)) {
                href = href.slice(window.location.origin.length) || '/';
            }
            if (href.startsWith('/gh/') || href.startsWith('/jira/')) {
                event.preventDefault();
                window.history.pushState({}, '', href);
            }
        };
        node.addEventListener('click', handler);
        return () => {
            node.removeEventListener('click', handler);
        };
    }, []);

    const activeRoute = route;

    const sidebarRoutes = useMemo(() => {
        if (!routes.length) {
            return [];
        }
        return routes.slice(0, 100);
    }, [routes]);

    const handleSearchSubmit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setSearchRequest({ ...searchForm });
    };

    const handleInputChange = (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        const { name, value } = event.target;
        setSearchForm((current) => ({ ...current, [name]: value }));
    };

    const exitViewer = () => {
        window.history.pushState({}, '', '/');
    };

    return (
        <div className="origin-safe-viewer" ref={contentRef}>
            <header className="origin-safe-viewer__header">
                <div className="origin-safe-viewer__title-group">
                    <button type="button" className="origin-safe-viewer__close" onClick={exitViewer}>
                        ← Back
                    </button>
                    <h1 className="origin-safe-viewer__title">Origin-safe Issue Viewer</h1>
                </div>
                <div className="origin-safe-viewer__header-meta">
                    <button
                        className="origin-safe-viewer__origin-button"
                        type="button"
                        disabled
                        title="Disabled in demo. Synthetic dataset."
                    >
                        Open in origin
                    </button>
                </div>
            </header>
            <div className="origin-safe-viewer__content">
                <aside className="origin-safe-viewer__sidebar">
                    <form className="origin-safe-viewer__search" onSubmit={handleSearchSubmit}>
                        <h2>Search issues</h2>
                        <input
                            name="q"
                            value={searchForm.q}
                            onChange={handleInputChange}
                            placeholder="Free text"
                        />
                        <input
                            name="source"
                            value={searchForm.source}
                            onChange={handleInputChange}
                            placeholder="Source (github, jira)"
                        />
                        <input
                            name="repo"
                            value={searchForm.repo}
                            onChange={handleInputChange}
                            placeholder="Repo"
                        />
                        <input
                            name="project"
                            value={searchForm.project}
                            onChange={handleInputChange}
                            placeholder="Project"
                        />
                        <input
                            name="label"
                            value={searchForm.label}
                            onChange={handleInputChange}
                            placeholder="Label"
                        />
                        <input
                            name="state"
                            value={searchForm.state}
                            onChange={handleInputChange}
                            placeholder="State"
                        />
                        <input
                            name="priority"
                            value={searchForm.priority}
                            onChange={handleInputChange}
                            placeholder="Priority"
                        />
                        <button type="submit" className="origin-safe-viewer__search-submit" disabled={searchLoading}>
                            {searchLoading ? 'Searching…' : 'Search'}
                        </button>
                        {searchError ? <p className="origin-safe-viewer__error">{searchError}</p> : null}
                    </form>
                    <section className="origin-safe-viewer__results">
                        <h2>Triage results</h2>
                        {searchResults.length === 0 && !searchLoading ? (
                            <p className="origin-safe-viewer__empty">No issues matched the filters.</p>
                        ) : null}
                        <ul>
                            {searchResults.map((item) => (
                                <li key={`${item.source}-${item.id}`}>
                                    <button
                                        type="button"
                                        className={item.route === activeRoute ? 'active' : ''}
                                        onClick={() => window.history.pushState({}, '', item.route)}
                                    >
                                        <span className="origin-safe-viewer__result-title">{item.title}</span>
                                        <span className="origin-safe-viewer__result-meta">
                                            {item.source} · {item.status || 'unknown'}
                                        </span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    </section>
                    <section className="origin-safe-viewer__routes">
                        <h2>Available routes</h2>
                        {routesError ? <p className="origin-safe-viewer__error">{routesError}</p> : null}
                        <ul>
                            {sidebarRoutes.map((item) => (
                                <li key={item}>
                                    <button
                                        type="button"
                                        className={item === activeRoute ? 'active' : ''}
                                        onClick={() => window.history.pushState({}, '', item)}
                                    >
                                        {item}
                                    </button>
                                </li>
                            ))}
                        </ul>
                    </section>
                </aside>
                <main className="origin-safe-viewer__main">
                    {issueLoading ? <p>Loading issue…</p> : null}
                    {issueError ? <p className="origin-safe-viewer__error">{issueError}</p> : null}
                    {!issueLoading && !issueError && issue ? (
                        <article className="origin-safe-viewer__issue">
                            <p className="origin-safe-viewer__banner">{issue.determinism}</p>
                            <h2>{issue.title}</h2>
                            <div className="origin-safe-viewer__meta">
                                <span className="origin-safe-viewer__pill">{issue.source}</span>
                                {issue.status ? <span className="origin-safe-viewer__pill">Status: {issue.status}</span> : null}
                                {issue.priority ? <span className="origin-safe-viewer__pill">Priority: {issue.priority}</span> : null}
                                <span className="origin-safe-viewer__pill">Route: {issue.route}</span>
                                {issue.repo ? <span className="origin-safe-viewer__pill">Repo: {issue.repo}</span> : null}
                                {issue.project ? <span className="origin-safe-viewer__pill">Project: {issue.project}</span> : null}
                                {issue.created_at ? (
                                    <span className="origin-safe-viewer__pill">Created: {formatDate(issue.created_at)}</span>
                                ) : null}
                            </div>
                            {issue.labels.length ? (
                                <ul className="origin-safe-viewer__labels">
                                    {issue.labels.map((label) => (
                                        <li key={label}>{label}</li>
                                    ))}
                                </ul>
                            ) : null}
                            {issue.origin_url ? (
                                <p className="origin-safe-viewer__origin-url">Origin URL: {issue.origin_url}</p>
                            ) : null}
                            <section
                                className="origin-safe-viewer__body"
                                dangerouslySetInnerHTML={{ __html: issue.body_html }}
                            />
                            <section className="origin-safe-viewer__comments">
                                <h3>Comments</h3>
                                {issue.comments.length === 0 ? <p>No comments found.</p> : null}
                                <ul>
                                    {issue.comments.map((comment, index) => (
                                        <li key={`${comment.author || 'comment'}-${index}`}>
                                            <div className="origin-safe-viewer__comment-header">
                                                <span className="origin-safe-viewer__comment-author">
                                                    {comment.author || 'Unknown author'}
                                                </span>
                                                {comment.created_at ? (
                                                    <span className="origin-safe-viewer__comment-time">
                                                        {formatDate(comment.created_at)}
                                                    </span>
                                                ) : null}
                                            </div>
                                            <div
                                                className="origin-safe-viewer__comment-body"
                                                dangerouslySetInnerHTML={{ __html: comment.body_html }}
                                            />
                                        </li>
                                    ))}
                                </ul>
                            </section>
                        </article>
                    ) : null}
                </main>
            </div>
        </div>
    );
}

export default OriginSafeViewerApp;