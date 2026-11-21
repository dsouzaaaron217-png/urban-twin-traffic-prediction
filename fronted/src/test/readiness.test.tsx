import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { ReadinessPage } from '@/routes/readiness';

const readiness = {
  minimum_history_days: 14,
  minimum_coverage: 0.8,
  corridors: [{
    city: 'Mangaluru', area: 'Hampankatta', coverage: 0.5,
    first_timestamp: '2026-11-01T00:00:00Z', last_timestamp: '2026-11-02T00:00:00Z',
    history_days: 2, ready: false, message: 'Collecting data: 2 of 14 days',
  }],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('Forecast readiness page', () => {
  it('shows the loading state while the API request is pending', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    render(<ReadinessPage />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading corridor readiness');
  });

  it('shows corridor coverage and collecting status from the API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => readiness }));
    render(<ReadinessPage />);
    expect(await screen.findByText('Hampankatta, Mangaluru')).toBeInTheDocument();
    expect(screen.getByText('50.0%')).toBeInTheDocument();
    expect(screen.getByText('Collecting data: 2 of 14 days')).toBeInTheDocument();
  });

  it('shows the empty state when there are no corridors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...readiness, corridors: [] }) }));
    render(<ReadinessPage />);
    expect(await screen.findByText('No validated corridor observations yet.')).toBeInTheDocument();
  });

  it('shows an error state when the API is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    render(<ReadinessPage />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Readiness service returned 503'));
  });
});
