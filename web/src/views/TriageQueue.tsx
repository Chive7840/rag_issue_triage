import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { Link } from 'react-router-dom';

interface SearchResult {
    issue_id: number;
    title: string;
    score: number;
}

export default function TriageQueue() {
    const { data, isLoading } = useQuery({
       queryKey: ['queue'],
       queryFn: async () => {
           const response = await axios.get('/search', { params: { q: 'triage', k: 10 } });
           return response.data.results as SearchResult[];
       }
    });

    return (
        <section>
            <h2>Triage Queue</h2>
            {isLoading && <p>Loading suggestions...</p>}
            <ul>
                {data?.map((item) => (
                    <li key={item.issue_id}>
                        <Link to={`/issues/${item.issue_id}`}>{item.title}</Link>
                        <span className="score">{item.score.toFixed(3)}</span>
                    </li>
                ))}
            </ul>
        </section>
    );
}