import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import apiClient from "../apiClient";

interface SearchResult {
    issue_id: number;
    title: string;
    score: number;
    url?: string;
}

export default function SearchView() {
    const [query, setQuery] = useState('duplicate bug');
    const { data, refetch, isFetching } = useQuery({
        queryKey: ['search', query],
        queryFn: async () => {
            const response = await apiClient.get('/search', {
                params: { q: query, k: 10, hybrid: true }
            });
            return response.data.results as SearchResult[];
        }
    });

    return (
        <section>
            <h2>Search</h2>
            <form
                onSubmit={(event) => {
                    event.preventDefault();
                    refetch();
                }}
            >
                <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                />
                <button type="submit" disabled={isFetching}>
                    Search
                </button>
            </form>
            <ul>
                {data?.map((item) => (
                    <li key={item.issue_id}>
                        {item.url ? (
                            <a href={item.url} target="_blank" rel="noreferrer">
                                {item.title}
                            </a>
                        ) : (
                            item.title
                        )}
                        <span className="score">{item.score.toFixed(3)}</span>
                    </li>
                ))}
            </ul>
        </section>
    );
}