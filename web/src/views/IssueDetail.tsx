import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from 'react';
import { useParams } from 'react-router-dom';
import apiClient from '../apiClient';

interface RetrievalResult {
    issue_id: number;
    title: string;
    score: number;
    route?: string;
    url?: string;
}

interface Proposal {
    labels: string[];
    assignee_candidates: string[];
    summary: string;
    similar: RetrievalResult[];
}

export default function IssueDetail() {
    const { id } = useParams();
    const issueId = Number(id);
    const queryClient = useQueryClient();
    const [labels, setLabels] = useState('');
    const [comment, setComment] = useState('');
    const [assignee, setAssignee] = useState('');

    const { data, isLoading } = useQuery({
        queryKey: ['proposal', issueId],
        queryFn: async () => {
            const response = await apiClient.post('/triage/propose', { issue_id: issueId });
            return response.data as Proposal;
        },
        enabled: Number.isFinite(issueId)
    });

    const approveMutation = useMutation({
        mutationFn: async () => {
            await apiClient.post('/triage/approve', {
                issue_id: issueId,
                labels: labels ? labels.split(',').map((value) => value.trim()) : data?.labels ?? [],
                assignee: assignee || undefined,
                comment: comment || undefined
            });
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['proposal', issueId] }).then(); //TODO: check if adding .then() matters
            setComment('');
        }
    });

    if (isLoading || !data) {
        return <p>Loading proposal...</p>;
    }

    return (
        <section>
            <h2>Issue #{issueId}</h2>
            <p>{data.summary}</p>
            <h3>Suggested Labels</h3>
            <ul>
                {data.labels.map((label) => (
                    <li key={label}>{label}</li>
                ))}
            </ul>
            <h3>Similar Issues</h3>
            <ul>
                {data.similar.map((item) => (
                    <li key={item.issue_id}>
                        {item.route || item.url ? (
                            <button
                                type="button"
                                className="link-button"
                                onClick={() => {
                                    if (item.route) {
                                        window.history.pushState({}, '', item.route);
                                        return;
                                    }
                                    if (item.url) {
                                        window.open(item.url, '_blank', 'noreferrer');
                                    }
                                }}
                            >
                                {item.title}
                            </button>
                        ) : (
                            item.title
                        )}
                        <span className="score">{item.score.toFixed(3)}</span>
                    </li>
                ))}
            </ul>
            <form
                onSubmit={(event: FormEvent<HTMLFormElement>) => {
                    event.preventDefault();
                    approveMutation.mutate();
                }}
            >
                <label>
                    Labels
                    <input value={labels} onChange={(event) =>
                        setLabels(event.target.value)} placeholder="bug, triage" />
                </label>
                <label>
                    Assignee
                    <input value={assignee} onChange={(event) =>
                        setAssignee(event.target.value)} placeholder="octocat" />
                </label>
                <label>
                    Comment
                    <textarea value={comment} onChange={(event) =>
                        setComment(event.target.value)} />
                </label>
                <button type="submit" disabled={approveMutation.isPending}>
                    Approve
                </button>
            </form>
        </section>
    );
}