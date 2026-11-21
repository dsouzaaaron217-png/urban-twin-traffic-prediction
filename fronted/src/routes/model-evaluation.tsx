import { createFileRoute } from '@tanstack/react-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getPhase3ModelMetrics, type Phase3ModelMetrics } from '@/services/api';
import { strings } from '@/strings';
import { ForecastActualPanel } from '@/components/traffic/ForecastActualPanel';

export const Route = createFileRoute('/model-evaluation')({ component: ModelEvaluationPage });

const horizons = ['15m', '30m', '60m'] as const;
const percent = (value?: number) => Number.isFinite(value) ? `${(value as number).toFixed(2)}%` : strings.state.unavailable;
const f1Score = (value?: number) => Number.isFinite(value) ? `${(((value as number) <= 1 ? (value as number) * 100 : (value as number))).toFixed(1)}%` : strings.state.unavailable;

export function ModelEvaluationPage() {
  const [metrics, setMetrics] = useState<Phase3ModelMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [stale, setStale] = useState(false);
  const hasData = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      setMetrics(await getPhase3ModelMetrics(signal));
      hasData.current = true;
      setStale(false);
    } catch (reason) {
      if (signal?.aborted) return;
      setError(reason instanceof Error ? reason.message : strings.evaluation.loadError);
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

  const evaluations = metrics?.evaluation_by_horizon || {};
  const hasEvaluation = horizons.some(h => evaluations[h]?.model_metrics);

  return <main className="page space-y-6" aria-labelledby="evaluation-title">
    <header className="page-heading">
      <div><p className="eyebrow">MODEL QUALITY</p><h1 id="evaluation-title">{strings.evaluation.title}</h1>
        <p>{strings.evaluation.description}</p></div>
      <Button variant="outline" onClick={() => void load()} disabled={loading} aria-label="Refresh model evaluation">
        <RefreshCw className={loading ? 'animate-spin' : ''} size={16} /> {strings.state.refresh}
      </Button>
    </header>
    {metrics && <section className="panel p-4 flex flex-wrap gap-x-8 gap-y-3 text-sm" aria-label="Active model information">
      <span><strong>{strings.evaluation.activeVersion}:</strong> {metrics.model_version || strings.state.unavailable}</span>
      <span><strong>{strings.evaluation.status}:</strong> {metrics.status}</span>
      {metrics.training_range && <span><strong>{strings.evaluation.trainingRange}:</strong> {metrics.training_range[0] || '—'} to {metrics.training_range[1] || '—'}</span>}
      {metrics.drift?.alert && <span role="status" className="text-warning">{metrics.drift.message || strings.evaluation.driftAlert}</span>}
    </section>}
    {stale && <p role="status" className="api-notice">{strings.state.stale}</p>}
    {error && !metrics && <section role="alert" className="panel p-5 space-y-3"><p>{error}</p><Button onClick={() => void load()}>{strings.state.retry}</Button></section>}
    {loading && !metrics && <p role="status">{strings.state.loading}</p>}
    {!loading && metrics && !hasEvaluation && <section className="panel empty-state" aria-live="polite">
      <span className="empty-icon"><Activity size={22} /></span><h2>{strings.evaluation.emptyTitle}</h2>
      <p>{strings.evaluation.emptyDescription}</p>
    </section>}
    {metrics && hasEvaluation && <section className="grid gap-4 xl:grid-cols-3" aria-label="Evaluation by forecast horizon">
      {horizons.map(horizon => {
        const result = evaluations[horizon];
        const selected = result?.model_metrics;
        const baseline = result?.persistence_baseline || result?.historical_avg_baseline;
        return <article key={horizon} className="panel p-4 space-y-4">
          <header><p className="eyebrow">{strings.evaluation.horizon}</p><h2 className="text-xl font-bold">{horizon}</h2></header>
          {selected ? <>
            <p className="text-sm"><strong>{strings.evaluation.model}:</strong> {result?.selected_model_name || strings.state.unavailable}</p>
            {result?.fallback_reason && <p className="rounded border border-warning/40 bg-warning-soft p-2 text-sm">{strings.evaluation.fallback}: {result.fallback_reason}</p>}
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div><dt className="text-muted-foreground">{strings.evaluation.mae}</dt><dd className="font-semibold">{percent(selected.mae_percent)}</dd></div>
              <div><dt className="text-muted-foreground">{strings.evaluation.rmse}</dt><dd className="font-semibold">{percent(selected.rmse_percent)}</dd></div>
              <div><dt className="text-muted-foreground">{strings.evaluation.mape}</dt><dd className="font-semibold">{percent(selected.mape)}</dd></div>
              <div><dt className="text-muted-foreground">{strings.evaluation.f1}</dt><dd className="font-semibold">{f1Score(selected.congestion_macro_f1)}</dd></div>
              <div><dt className="text-muted-foreground">{strings.evaluation.samples}</dt><dd className="font-semibold">{result?.test_samples ?? strings.state.unavailable}</dd></div>
              <div><dt className="text-muted-foreground">{strings.evaluation.baseline}</dt><dd className="font-semibold">{result?.best_baseline_name || '—'}</dd></div>
            </dl>
            {baseline && <p className="border-t pt-3 text-xs text-muted-foreground">Baseline MAE {percent(baseline.mae_percent)} · RMSE {percent(baseline.rmse_percent)}</p>}
          </> : <p role="status" className="text-sm text-muted-foreground">{strings.state.insufficientHistory}</p>}
        </article>;
      })}
    </section>}
    <ForecastActualPanel />
  </main>;
}
