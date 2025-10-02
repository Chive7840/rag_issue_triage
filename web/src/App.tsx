import { Link, Route, Routes } from 'react-router-dom';
import TriageQueue from './views/TriageQueue';
import IssueDetail from './views/IssueDetail';
import SearchView from './views/SearchView';

export default function App() {
    return (
        <div className="app">
            <header>
                <h1>RAG Issue Triage Copilot</h1>
                <nav>
                    <Link to="/">Queue</Link>
                    <Link to="/search">Search</Link>
                </nav>
            </header>
            <main>
                <Routes>
                  <Route path="/" element={<TriageQueue />} />
                  <Route path="/issues/:id" element={<IssueDetail />} />
                  <Route path="/search" element={<SearchView />} />
                </Routes>
            </main>
        </div>
    );
}