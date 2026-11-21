import { createFileRoute } from '@tanstack/react-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Bell, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getTrafficAlerts } from '@/services/api';
import type { TrafficAlert } from '@/types/traffic';
import { strings } from '@/strings';

export const Route = createFileRoute('/alerts')({ component: AlertsPage });

export function AlertsPage() {
  const [items, setItems] = useState<TrafficAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [stale, setStale] = useState(false);
  const hasData = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      const page = await getTrafficAlerts(50, 0, signal);
      setItems(page.items);
      hasData.current = true;
      setStale(false);
    } catch (reason) {
      if (signal?.aborted) return;
      setError(reason instanceof Error ? reason.message : strings.alerts.loadError);
      setStale(hasData.current);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return <main className="page space-y-6" aria-labelledby="alerts-title">
    <header className="page-heading">
      <div><p className="eyebrow">TRAFFIC INTELLIGENCE</p><h1 id="alerts-title">{strings.alerts.title}</h1>
        <p>{strings.alerts.description}</p></div>
      <Button variant="outline" onClick={() => void load()} disabled={loading} aria-label="Refresh alerts">
        <RefreshCw className={loading ? 'animate-spin' : ''} size={16} /> {strings.state.refresh}
      </Button>
    </header>
    {stale && <p role="status" className="api-notice">{strings.state.stale}</p>}
    {error && items.length === 0 && <section role="alert" className="panel p-5 space-y-3">
      <p>{error || strings.alerts.loadError}</p><Button onClick={() => void load()}>{strings.state.retry}</Button>
    </section>}
    {loading && items.length === 0 && <p role="status">{strings.state.loading}</p>}
    {!loading && !error && items.length === 0 && <section className="panel empty-state" aria-live="polite">
      <span className="empty-icon"><Bell size={22} /></span><h2>{strings.alerts.emptyTitle}</h2>
      <p>{strings.alerts.emptyDescription}</p>
    </section>}
    {items.length > 0 && <section className="space-y-3" aria-label="Current traffic alerts">
      {items.map(item => <article key={item.id} className="panel flex items-start gap-3 p-4">
        <span aria-hidden="true" className="rounded-full bg-warning-soft p-2 text-warning"><AlertTriangle size={18} /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold">{item.type.replaceAll('_', ' ')}</h2>
            <span className="rounded border px-2 py-0.5 text-xs font-medium">{item.severity}</span></div>
          <p className="mt-1 text-sm text-muted-foreground">{item.message}</p>
          {(item.city || item.area) && <p className="mt-1 text-xs">{[item.area, item.city].filter(Boolean).join(', ')}</p>}
          <time className="mt-2 block text-xs text-muted-foreground" dateTime={item.generated_at}>{new Date(item.generated_at).toLocaleString()}</time>
        </div>
      </article>)}
    </section>}
  </main>;
}
