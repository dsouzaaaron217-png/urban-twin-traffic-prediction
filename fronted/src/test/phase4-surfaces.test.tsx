import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AlertsPage } from '@/routes/alerts';
import { ModelEvaluationPage } from '@/routes/model-evaluation';
import { ForecastActualPanel } from '@/components/traffic/ForecastActualPanel';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('Phase 4 alert and evaluation surfaces', () => {
  it('shows a verified empty alert state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
    }));
    render(<AlertsPage />);
    expect(await screen.findByText('No active alerts')).toBeInTheDocument();
  });

  it('shows alert errors with a retry action', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    render(<AlertsPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('503');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('shows the insufficient-history state when no evaluation has been measured', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, json: async () => ({
        model_version: null, status: 'blocked', evaluation_by_horizon: {}, fallback_by_horizon: {},
      }),
    }));
    render(<ModelEvaluationPage />);
    expect(await screen.findByText('Evaluation is not available')).toBeInTheDocument();
  });

  it('renders measured test metrics by horizon', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, json: async () => ({
        model_version: 'model-test-v1', status: 'ready', fallback_by_horizon: {},
        evaluation_by_horizon: {
          '15m': { selected_model_name: 'Persistence', test_samples: 42,
            model_metrics: { mae_percent: 3.1, rmse_percent: 4.4, mape: 8.2, congestion_macro_f1: 0.76 } },
        },
      }),
    }));
    render(<ModelEvaluationPage />);
    expect(await screen.findByText('model-test-v1')).toBeInTheDocument();
    expect(screen.getByText('3.10%')).toBeInTheDocument();
    expect(screen.getByText('76.0%')).toBeInTheDocument();
  });

  it('shows actual-versus-predicted error only for matched observations', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, json: async () => ({
        total: 1, limit: 500, offset: 0,
        items: [{ id: 1, city: 'Pune', area: 'Central Road', horizon_minutes: 15,
          origin_timestamp: '2026-11-20T10:00:00Z', target_timestamp: '2026-11-20T10:15:00Z',
          generated_at: '2026-11-20T10:00:00Z', predicted_congestion_percent: 35,
          actual_timestamp: '2026-11-20T10:15:00Z', actual_congestion_percent: 40,
          model_version: 'model-v1', data_source: 'tomtom', data_quality: 'verified' }],
      }),
    }));
    render(<ForecastActualPanel />);
    const errorSummary = await screen.findByText(/Mean absolute error:/);
    expect(errorSummary.parentElement).toHaveTextContent('5.00 percentage points');
    expect(screen.getByText('40.0%')).toBeInTheDocument();
  });
});
