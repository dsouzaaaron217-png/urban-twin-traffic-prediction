import { describe, expect, it } from 'vitest';
import { metricColor } from '@/lib/map-metrics';
import type { TrafficSegment } from '@/types/traffic';

const segment: TrafficSegment = {
  coordinates: [], current_speed_kmh: 20, free_flow_speed_kmh: 50,
  congestion_percent: 70, current_travel_time_seconds: 180,
  free_flow_travel_time_seconds: 90, confidence: 0.4,
};

describe('map metric colors', () => {
  it('colors all four metrics using their own measurements', () => {
    expect(metricColor(segment, 'congestion')).toBe('#dc2626');
    expect(metricColor(segment, 'speed')).toBe('#dc2626');
    expect(metricColor(segment, 'travelTime')).toBe('#dc2626');
    expect(metricColor(segment, 'confidence')).toBe('#dc2626');
  });

  it('uses a neutral color when a selected metric is missing', () => {
    expect(metricColor({ ...segment, confidence: null }, 'confidence')).toBe('#64748b');
  });
});
