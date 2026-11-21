import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getForecastActuals } from '@/services/api';
import type { ForecastActual } from '@/types/traffic';
import { strings } from '@/strings';

const ForecastActualGraph = lazy(() => import('./ForecastActualGraph').then(module => ({ default: module.ForecastActualGraph })));

export function ForecastActualPanel() {
  const [rows, setRows] = useState<ForecastActual[]>([]);
  const [selectedCorridor, setSelectedCorridor] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [stale, setStale] = useState(false);
  const hasRows = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      const page = await getForecastActuals(500, 0, signal);
      const matched = page.items.filter(row => row.actual_congestion_percent !== null && Number.isFinite(row.actual_congestion_percent));
      setRows(matched);
      hasRows.current = matched.length > 0;
      setStale(false);
      setSelectedCorridor(current => current || (matched[0] ? `${matched[0].city}\u0000${matched[0].area}` : ''));
    } catch (reason) {
      if (signal?.aborted) return;
      setError(reason instanceof Error ? reason.message : strings.verification.loadError);
      setStale(hasRows.current);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const corridors = useMemo(() => [...new Map(rows.map(row => [`${row.city}\u0000${row.area}`, { key: `${row.city}\u0000${row.area}`, label: `${row.area}, ${row.city}` }])).values()], [rows]);
  const corridorRows = rows.filter(row => `${row.city}\u0000${row.area}` === selectedCorridor);
  const meanAbsoluteError = corridorRows.length
    ? corridorRows.reduce((sum, row) => sum + Math.abs(row.predicted_congestion_percent - (row.actual_congestion_percent ?? 0)), 0) / corridorRows.length
    : null;

  return <section className="panel p-4 space-y-4" aria-labelledby="forecast-verification-title">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 id="forecast-verification-title" className="text-lg font-bold">{strings.verification.title}</h2>
        <p className="text-sm text-muted-foreground">{strings.verification.description}</p></div>
      <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading} aria-label="Refresh forecast verification">
        <RefreshCw className={loading ? 'animate-spin' : ''} size={14} /> {strings.state.refresh}
      </Button>
    </header>
    {corridors.length > 0 && <label className="field max-w-md">{strings.verification.selectCorridor}
      <select value={selectedCorridor} onChange={event => setSelectedCorridor(event.target.value)} aria-label={strings.verification.selectCorridor}>
        {corridors.map(corridor => <option key={corridor.key} value={corridor.key}>{corridor.label}</option>)}
      </select>
    </label>}
    {error && rows.length === 0 && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {stale && <p role="status" className="api-notice">{strings.state.stale}</p>}
    {loading && rows.length === 0 && <p role="status">{strings.state.loading}</p>}
    {!loading && !error && rows.length === 0 && <div className="empty-state py-8">
      <h3>{strings.verification.emptyTitle}</h3><p>{strings.verification.emptyDescription}</p>
    </div>}
    {corridorRows.length > 0 && <>
      <p className="text-sm"><strong>{strings.verification.meanAbsoluteError}:</strong> {meanAbsoluteError?.toFixed(2)} percentage points · {corridorRows.length} {strings.verification.matchedPairs}</p>
      <Suspense fallback={<p role="status">{strings.verification.loadingChart}</p>}><ForecastActualGraph rows={corridorRows} /></Suspense>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead><tr className="border-b"><th className="p-2">{strings.verification.targetTime}</th><th className="p-2">{strings.verification.horizon}</th><th className="p-2">{strings.verification.predictedCongestion}</th><th className="p-2">{strings.verification.observedCongestion}</th><th className="p-2">{strings.verification.absoluteError}</th></tr></thead>
          <tbody>{corridorRows.map(row => <tr key={row.id} className="border-b">
            <td className="p-2"><time dateTime={row.target_timestamp}>{new Date(row.target_timestamp).toLocaleString()}</time></td>
            <td className="p-2">{row.horizon_minutes} min</td>
            <td className="p-2"><span aria-label={strings.verification.predicted}>{row.predicted_congestion_percent.toFixed(1)}%</span></td>
            <td className="p-2"><span aria-label={strings.verification.observed}>{row.actual_congestion_percent?.toFixed(1)}%</span></td>
            <td className="p-2">{Math.abs(row.predicted_congestion_percent - (row.actual_congestion_percent ?? 0)).toFixed(1)} pp</td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
  </section>;
}
