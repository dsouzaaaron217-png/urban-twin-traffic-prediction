import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/health', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'healthy' }) })
  );
  await page.route('**/api/monitored-locations**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
  await page.route('**/api/traffic?**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        city: 'Pune', area: 'Central Pune', timestamp: new Date().toISOString(),
        current_speed_kmh: 24, free_flow_speed_kmh: 40, congestion_percent: 40,
        current_travel_time_seconds: 180, free_flow_travel_time_seconds: 108,
        confidence: 0.8, source: 'e2e-fixture', quality: 'test',
      }),
    })
  );
  await page.route('**/api/traffic/nearby-segments**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ segments: [] }) })
  );
  await page.route('**/api/v1/alerts**', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }),
    })
  );
  await page.route('**/api/v1/model/metrics', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        model_version: null,
        status: 'insufficient_history',
        evaluation_by_horizon: {},
        fallback_by_horizon: {},
      }),
    })
  );
  await page.route('**/api/v1/forecasts/actuals**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) })
  );
  await page.route('**/api/v1/data/readiness', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ minimum_history_days: 14, minimum_coverage: 0.8, corridors: [] }),
    })
  );
});

test('navigation, alerts, evaluation and readiness empty states load without browser errors', async ({ page }) => {
  const browserErrors: string[] = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  page.on('requestfailed', request => {
    const failure = request.failure()?.errorText;
    if (failure && failure !== 'net::ERR_ABORTED') browserErrors.push(`${request.url()}: ${failure}`);
  });
  page.on('console', message => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });

  await page.goto('/alerts');
  await expect(page.getByRole('heading', { name: 'Traffic Alerts' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'No active alerts' })).toBeVisible();

  await page.getByRole('link', { name: 'Model Evaluation' }).click();
  await expect(page.getByRole('heading', { name: 'Model Evaluation' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Evaluation is not available' })).toBeVisible();

  await page.getByRole('link', { name: 'Forecast Readiness' }).click();
  await expect(page.getByRole('heading', { name: 'Forecast Readiness' })).toBeVisible();
  await expect(page.getByText('No validated corridor observations yet.')).toBeVisible();
  expect(browserErrors).toEqual([]);
});

test('route planner renders without overflow at mobile and desktop sizes', async ({ page }) => {
  const browserErrors: string[] = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  page.on('requestfailed', request => {
    const failure = request.failure()?.errorText;
    if (failure && failure !== 'net::ERR_ABORTED') browserErrors.push(`${request.url()}: ${failure}`);
  });
  page.on('console', message => {
    if (message.type() === 'error') browserErrors.push(message.text());
  });

  for (const viewport of [{ width: 390, height: 844 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(viewport);
    await page.goto('/route-planner');
    await expect(page.getByRole('heading', { name: 'Route Planner' })).toBeVisible();
    await expect(page.getByPlaceholder('Enter starting location…')).toBeVisible();
    await expect(page.getByPlaceholder('Enter destination…')).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
  }

  expect(browserErrors).toEqual([]);
});
