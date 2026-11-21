# Product Requirements Document

## Product

TrafficWatch is a student-scale urban traffic monitoring and prediction prototype. It combines observed traffic records, corridor readiness, short-horizon forecasts, route alternatives, and model evaluation in a web dashboard.

## Users and main tasks

- A commuter or reviewer selects a supported city/corridor, inspects available traffic observations, and checks whether a forecast is ready.
- A project maintainer imports validated observations, reviews model metrics and alerts, and configures provider access on the backend.

## Current product behavior

- The web client provides dashboard, analytics, predictions, congestion hotspots, saved locations, route planning, forecast readiness, alerts, and model evaluation views.
- The map exposes congestion, speed, travel-time, and confidence layers, and playback uses saved observed history.
- Forecasts are gated by available history and show fallback/readiness details. Unsupported route-level future ETAs and best-departure suggestions are reported as unavailable.
- City-scoped place suggestions use the configured backend TomTom Search integration. Without a provider key, the app shows an unavailable/no-results state.
- Synthetic values are marked as demo data and must not be presented as measured observations or real model accuracy.

## Product constraints and limitations

- Forecast quality depends on real validated corridor history; a large number of rows alone is not enough.
- Pune and eligible Karnataka corridors are distinct locations; one city's data does not represent another.
- Current map rendering uses Leaflet with OpenStreetMap tiles. A MapLibre migration is not included in the current implementation.
- Route alternatives use the existing provider. Forecasted route ETA and best time to leave are not available until route-level horizon ETAs have measured validation.
- This prototype is not safety-critical navigation and should not be used as the sole basis for travel decisions.

## Definition of completion

The project is ready for a demonstration when the automated checks pass, the app starts from the documented command, forecast status and provenance are visible, and limitations remain explicit. Production readiness additionally requires verified provider-account terms, responsive visual review, and deployment-specific security review.
