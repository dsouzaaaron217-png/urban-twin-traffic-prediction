import { createFileRoute } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { API_BASE } from '@/services/api';

type Corridor = {
  city: string; area: string; coverage: number; first_timestamp: string;
  last_timestamp: string; history_days: number; ready: boolean; message: string;
};
type ReadinessResponse = { minimum_history_days: number; minimum_coverage: number; corridors: Corridor[] };

export const Route = createFileRoute('/readiness')({ component: ReadinessPage });

export function ReadinessPage() {
  const [data, setData] = useState<ReadinessResponse | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/api/v1/data/readiness`, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(`Readiness service returned ${response.status}`); return response.json(); })
      .then(setData).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Unable to load readiness.'); });
    return () => controller.abort();
  }, []);
  return <main className="page space-y-6">
    <div><p className="eyebrow">PHASE 1 DATA GATE</p><h1 className="text-2xl font-bold">Forecast Readiness</h1>
      <p className="text-sm text-muted-foreground">Forecasts unlock after 14 days of history with at least 80% polling coverage per corridor.</p></div>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {!data && !error && <p role="status">Loading corridor readiness…</p>}
    {data?.corridors.length === 0 && <p>No validated corridor observations yet.</p>}
    {data && data.corridors.length > 0 && <div className="overflow-x-auto rounded-lg border"><table className="w-full text-sm">
      <thead><tr><th className="p-3 text-left">Corridor</th><th className="p-3 text-left">Coverage</th><th className="p-3 text-left">History</th><th className="p-3 text-left">First observed</th><th className="p-3 text-left">Last observed</th><th className="p-3 text-left">Forecast status</th></tr></thead>
      <tbody>{data.corridors.map(item => <tr key={`${item.city}:${item.area}`} className="border-t">
        <td className="p-3">{item.area}, {item.city}</td><td className="p-3">{(item.coverage * 100).toFixed(1)}%</td>
        <td className="p-3">{item.history_days} / {data.minimum_history_days} days</td><td className="p-3">{new Date(item.first_timestamp).toLocaleString()}</td>
        <td className="p-3">{new Date(item.last_timestamp).toLocaleString()}</td><td className="p-3">{item.ready ? 'Ready' : item.message}</td>
      </tr>)}</tbody>
    </table></div>}
  </main>;
}
