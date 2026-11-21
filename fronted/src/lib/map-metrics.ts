import type { TrafficSegment } from '@/types/traffic';
import { getTrafficColor } from './traffic-utils';

export type TrafficMetric = 'congestion' | 'speed' | 'travelTime' | 'confidence';

/** Traffic colors always map to a textual legend; unknown measurements stay neutral. */
export function metricColor(segment: TrafficSegment, metric: TrafficMetric): string {
  const unavailable = '#64748b';
  if (metric === 'congestion') return getTrafficColor(segment.congestion_percent);
  if (metric === 'speed') {
    if (segment.current_speed_kmh == null || !segment.free_flow_speed_kmh) return unavailable;
    const ratio = segment.current_speed_kmh / segment.free_flow_speed_kmh;
    return ratio < 0.5 ? '#dc2626' : ratio < 0.8 ? '#eab308' : '#059669';
  }
  if (metric === 'travelTime') {
    if (segment.current_travel_time_seconds == null || !segment.free_flow_travel_time_seconds) return unavailable;
    const ratio = segment.current_travel_time_seconds / segment.free_flow_travel_time_seconds;
    return ratio > 1.5 ? '#dc2626' : ratio > 1.15 ? '#eab308' : '#059669';
  }
  if (segment.confidence == null || !Number.isFinite(segment.confidence)) return unavailable;
  return segment.confidence < 0.5 ? '#dc2626' : segment.confidence < 0.8 ? '#eab308' : '#059669';
}
