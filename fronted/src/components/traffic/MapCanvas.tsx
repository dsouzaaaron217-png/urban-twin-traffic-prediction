import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  GeoJSON,
  Popup,
  useMap,
  useMapEvents,
  ZoomControl,
} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { RefreshCw, AlertCircle, MapPin, Radio, Compass, History, Play, Pause } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useTraffic, locationKey } from './TrafficProvider';
import type { TrafficReading, TrafficSegment } from '@/types/traffic';
import { getHistory } from '@/services/api';
import { strings } from '@/strings';
import { metricColor, type TrafficMetric } from '@/lib/map-metrics';

import { getTrafficColor, getTrafficCondition } from '@/lib/traffic-utils';
export { getTrafficColor, getTrafficCondition };

function getLineWeights(zoom: number) {
  if (zoom <= 12) return { outline: 7, inner: 4 };
  if (zoom <= 14) return { outline: 9, inner: 6 };
  if (zoom <= 16) return { outline: 11, inner: 7 };
  return { outline: 13, inner: 8 };
}

function MapController({
  onZoomChange,
  onMapClick,
}: {
  onZoomChange: (z: number) => void;
  onMapClick?: () => void;
}) {
  const { location, selectLocation } = useTraffic();
  const map = useMap();
  const prevCoordRef = useRef<[number, number]>([location.latitude, location.longitude]);

  // Center smoothly ONLY when coordinate actually changes (prevent auto-refresh jumping)
  useEffect(() => {
    const [prevLat, prevLng] = prevCoordRef.current;
    const latDiff = Math.abs(prevLat - location.latitude);
    const lngDiff = Math.abs(prevLng - location.longitude);

    if (latDiff > 0.0001 || lngDiff > 0.0001) {
      prevCoordRef.current = [location.latitude, location.longitude];
      map.flyTo([location.latitude, location.longitude], Math.max(map.getZoom(), 14), {
        duration: 0.8,
      });
    }
  }, [location.latitude, location.longitude, map]);

  useMapEvents({
    zoomend: e => {
      onZoomChange(e.target.getZoom());
    },
    click: e => {
      onMapClick?.();
      selectLocation({
        city: 'Map selection',
        area: `${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)}`,
        latitude: e.latlng.lat,
        longitude: e.latlng.lng,
      });
    },
  });

  return null;
}

function SelectedSegmentController({
  selectedSegmentIndex,
  segments,
}: {
  selectedSegmentIndex?: number | null;
  segments: TrafficSegment[];
}) {
  const map = useMap();
  useEffect(() => {
    if (
      selectedSegmentIndex !== null &&
      selectedSegmentIndex !== undefined &&
      segments[selectedSegmentIndex]?.coordinates?.length
    ) {
      const coords = segments[selectedSegmentIndex].coordinates;
      const mid = coords[Math.floor(coords.length / 2)];
      if (mid) map.panTo([mid[0], mid[1]], { animate: true, duration: 0.5 });
    }
  }, [selectedSegmentIndex, segments, map]);
  return null;
}

function MapAutoResize({ expanded, isFullscreen }: { expanded?: boolean; isFullscreen?: boolean }) {
  const map = useMap();
  useEffect(() => {
    map.invalidateSize();
    const container = map.getContainer();
    if (!container) return;

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        map.invalidateSize();
      });
      resizeObserver.observe(container);
    }

    const onFullscreenChange = () => {
      setTimeout(() => map.invalidateSize(), 150);
    };
    document.addEventListener('fullscreenchange', onFullscreenChange);

    const onWindowResize = () => {
      map.invalidateSize();
    };
    window.addEventListener('resize', onWindowResize);

    return () => {
      resizeObserver?.disconnect();
      document.removeEventListener('fullscreenchange', onFullscreenChange);
      window.removeEventListener('resize', onWindowResize);
    };
  }, [map]);

  useEffect(() => {
    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 150);
    return () => clearTimeout(timer);
  }, [expanded, isFullscreen, map]);

  return null;
}

export interface MapCanvasProps {
  selectedSegmentIndex?: number | null | undefined;
  onSelectSegment?: ((index: number | null) => void) | undefined;
  className?: string;
  expanded?: boolean;
  isFullscreen?: boolean;
  height?: string | number | undefined;
}

export default function MapCanvas({
  selectedSegmentIndex = null,
  onSelectSegment,
  className = '',
  expanded = false,
  isFullscreen = false,
  height,
}: MapCanvasProps = {}) {
  const {
    location,
    selectLocation,
    segments,
    segmentsLoading,
    segmentsError,
    refresh,
    lastRefreshedAt,
    lastUpdated,
    monitoredLocations,
    isStale,
  } = useTraffic();

  const [currentZoom, setCurrentZoom] = useState(14);
  const [metric, setMetric] = useState<TrafficMetric>('congestion');
  const [playbackOpen, setPlaybackOpen] = useState(false);
  const [playbackRows, setPlaybackRows] = useState<TrafficReading[]>([]);
  const [playbackIndex, setPlaybackIndex] = useState(0);
  const [playbackPlaying, setPlaybackPlaying] = useState(false);
  const [playbackLoading, setPlaybackLoading] = useState(false);
  const [playbackError, setPlaybackError] = useState('');
  const weights = getLineWeights(currentZoom);
  const playbackRow = playbackRows[playbackIndex];
  const segmentGeoJson = useMemo(() => ({
    type: 'FeatureCollection' as const,
    features: segments.flatMap((segment, index) => segment.coordinates?.length >= 2 ? [{
      type: 'Feature' as const,
      properties: { segmentIndex: index },
      geometry: {
        type: 'LineString' as const,
        coordinates: segment.coordinates.map(([latitude, longitude]) => [longitude, latitude]),
      },
    }] : []),
  }), [segments]);
  const activeSegment = selectedSegmentIndex === null ? undefined : segments[selectedSegmentIndex];
  const activeSegmentMidpoint = activeSegment?.coordinates?.[Math.floor((activeSegment.coordinates.length || 1) / 2)];

  const loadPlayback = async () => {
    setPlaybackOpen(true);
    setPlaybackError('');
    if (playbackRows.length > 0) return;
    setPlaybackLoading(true);
    try {
      const params = new URLSearchParams({ city: location.city, area: location.area, limit: '500' });
      const rows = await getHistory(params);
      setPlaybackRows(rows);
      setPlaybackIndex(0);
      if (rows.length === 0) setPlaybackError(strings.map.noHistory);
    } catch (reason) {
      setPlaybackError(reason instanceof Error ? reason.message : 'Unable to load stored observations.');
    } finally {
      setPlaybackLoading(false);
    }
  };

  useEffect(() => {
    setPlaybackRows([]);
    setPlaybackIndex(0);
    setPlaybackPlaying(false);
    setPlaybackError('');
  }, [location.city, location.area]);

  useEffect(() => {
    if (!playbackPlaying || playbackRows.length < 2) return;
    const timer = setInterval(() => {
      setPlaybackIndex(current => Math.min(current + 1, playbackRows.length - 1));
    }, 900);
    return () => clearInterval(timer);
  }, [playbackPlaying, playbackRows.length]);

  useEffect(() => {
    if (playbackPlaying && playbackIndex >= playbackRows.length - 1) {
      setPlaybackPlaying(false);
      setPlaybackIndex(0);
    }
  }, [playbackPlaying, playbackIndex, playbackRows.length]);

  const formattedTime = lastRefreshedAt
    ? lastRefreshedAt.toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : null;

  return (
    <div
      className={`relative w-full rounded-lg overflow-hidden border border-border ${
        isFullscreen ? 'h-full min-h-[420px]' : expanded ? 'h-[500px] lg:h-[600px]' : 'h-full min-h-[380px]'
      } ${className}`}
      style={height ? { height: typeof height === 'number' ? `${height}px` : height } : undefined}
    >
      {/* Top Map Header Bar with Controls */}
      <div className="absolute top-3 left-3 right-3 z-[1000] flex flex-wrap items-center justify-between gap-2 pointer-events-none">
        {/* Selected location indicator badge */}
        <div className="pointer-events-auto bg-card/95 backdrop-blur-md border border-border shadow-md rounded-md px-3 py-1.5 flex items-center gap-2 text-xs">
          <MapPin size={14} className="text-primary shrink-0" />
          <span className="font-semibold text-foreground truncate max-w-[200px] sm:max-w-xs">
            {location.area}, {location.city}
          </span>
          <span className="text-[10px] text-muted-foreground hidden sm:inline">
            ({location.latitude.toFixed(4)}°, {location.longitude.toFixed(4)}°)
          </span>
        </div>

        {/* Live Refresh & Status Badge */}
        <div className="pointer-events-auto flex items-center gap-1.5 bg-card/95 backdrop-blur-md border border-border shadow-md rounded-md px-2.5 py-1 text-xs">
          {segmentsLoading ? (
            <div className="flex items-center gap-1.5 text-primary">
              <RefreshCw size={13} className="animate-spin" />
              <span className="text-[11px] font-medium">Updating…</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-muted-foreground">
                <span className={`h-2 w-2 rounded-full ${isStale ? 'bg-amber-500' : 'bg-emerald-500 animate-pulse'}`} />
              <span className="text-[11px]">
                {isStale ? 'Stale observation' : formattedTime ? `Observed ${formattedTime}` : 'Live (60s refresh)'}
              </span>
            </div>
          )}

          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 ml-1 text-muted-foreground hover:text-foreground"
            onClick={refresh}
            disabled={segmentsLoading}
            title="Refresh live traffic map"
            aria-label="Refresh live traffic map"
          >
            <RefreshCw size={12} className={segmentsLoading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>

      <div className="absolute top-[3.6rem] right-3 z-[1000] flex items-center gap-2 pointer-events-auto">
        <label className="flex items-center gap-2 rounded-md border border-border bg-card/95 px-2 py-1.5 text-xs shadow-md">
          <span className="font-medium">{strings.map.layer}</span>
          <select value={metric} onChange={event => setMetric(event.target.value as TrafficMetric)} className="max-w-32 bg-transparent text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" aria-label={strings.map.layer}>
            <option value="congestion">{strings.map.congestion}</option>
            <option value="speed">{strings.map.speed}</option>
            <option value="travelTime">{strings.map.travelTime}</option>
            <option value="confidence">{strings.map.confidence}</option>
          </select>
        </label>
        <Button size="sm" variant="outline" className="h-8 bg-card/95 text-xs shadow-md" onClick={() => playbackOpen ? setPlaybackOpen(false) : void loadPlayback()} aria-expanded={playbackOpen}>
          <History size={14} /> <span className="hidden sm:inline">{strings.map.playback}</span>
        </Button>
      </div>

      {/* Segments Error Notification */}
      {segmentsError && (
        <div className="absolute top-14 left-3 right-3 z-[1000] bg-destructive/90 text-destructive-foreground text-xs p-2.5 rounded-md shadow-md flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <AlertCircle size={15} />
            <span>{segmentsError}</span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            className="h-6 px-2 text-[11px]"
            onClick={refresh}
          >
            Retry
          </Button>
        </div>
      )}

      {/* Empty State Banner if no segments found */}
      {!segmentsLoading && segments.length === 0 && !segmentsError && (
        <div className="absolute bottom-14 left-3 z-[1000] bg-card/90 backdrop-blur border border-border text-xs px-3 py-2 rounded-md shadow flex items-center gap-2 text-muted-foreground">
          <Compass size={14} className="text-amber-500" />
          <span>No active traffic flow segments returned for this point. Click the map to check nearby roads.</span>
        </div>
      )}

      {/* Leaflet Map */}
      <MapContainer
        center={[location.latitude, location.longitude]}
        zoom={14}
        preferCanvas
        zoomControl={false}
        scrollWheelZoom
        className="map-canvas h-full w-full"
      >
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          maxZoom={19}
        />

        <ZoomControl position="bottomright" />
        <MapAutoResize expanded={expanded} isFullscreen={isFullscreen} />
        <MapController
          onZoomChange={setCurrentZoom}
          onMapClick={() => onSelectSegment?.(null)}
        />
        <SelectedSegmentController
          selectedSegmentIndex={selectedSegmentIndex}
          segments={segments}
        />

        {/* A single vector source contains all road segments. */}
        <GeoJSON
          data={segmentGeoJson}
          style={feature => {
            const index = Number(feature?.properties?.segmentIndex);
            const segment = segments[index];
            const selected = selectedSegmentIndex === index;
            return {
              color: selected ? '#1d4ed8' : segment ? metricColor(segment, metric) : '#64748b',
              weight: selected ? weights.inner + 4 : weights.inner,
              opacity: 1,
              lineCap: 'round',
              lineJoin: 'round',
            };
          }}
          eventHandlers={{
            click: event => {
              event.originalEvent?.stopPropagation();
              const clickedEvent = event as typeof event & {
                layer?: { feature?: { properties?: { segmentIndex?: number } } };
                propagatedFrom?: { feature?: { properties?: { segmentIndex?: number } } };
                sourceTarget?: { feature?: { properties?: { segmentIndex?: number } } };
              };
              const layer = clickedEvent.layer ?? clickedEvent.propagatedFrom ?? clickedEvent.sourceTarget;
              const index = layer?.feature?.properties?.segmentIndex;
              if (typeof index === 'number') onSelectSegment?.(index);
            },
          }}
        />

        {activeSegment && activeSegmentMidpoint && <Popup position={activeSegmentMidpoint}>
          <div className="p-1 min-w-[210px] space-y-2 text-xs text-foreground">
            <strong className="block border-b pb-1.5">{activeSegment.name || `Road segment ${(selectedSegmentIndex ?? 0) + 1}`} · {getTrafficCondition(activeSegment.congestion_percent)}</strong>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-muted-foreground">
              <dt>Congestion</dt><dd className="text-foreground">{activeSegment.congestion_percent == null ? 'Unavailable' : `${activeSegment.congestion_percent.toFixed(1)}%`}</dd>
              <dt>Current speed</dt><dd className="text-foreground">{activeSegment.current_speed_kmh == null ? 'Unavailable' : `${activeSegment.current_speed_kmh} km/h`}</dd>
              <dt>Free-flow speed</dt><dd className="text-foreground">{activeSegment.free_flow_speed_kmh == null ? 'Unavailable' : `${activeSegment.free_flow_speed_kmh} km/h`}</dd>
              <dt>Travel time</dt><dd className="text-foreground">{activeSegment.current_travel_time_seconds == null ? 'Unavailable' : `${(activeSegment.current_travel_time_seconds / 60).toFixed(1)} min`}</dd>
              <dt>Confidence</dt><dd className="text-foreground">{activeSegment.confidence == null ? 'Unavailable' : `${(activeSegment.confidence * 100).toFixed(0)}%`}</dd>
            </dl>
            <div className="border-t pt-1.5 text-[10px] text-muted-foreground">
              <span>Observed from TomTom Flow API</span>{' · '}{lastUpdated ? new Date(lastUpdated).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : formattedTime || 'Latest stored observation'}
            </div>
          </div>
        </Popup>}

        {/* Monitored Locations Markers */}
        {monitoredLocations.map(place => (
          <CircleMarker
            key={`monitored-${locationKey(place)}`}
            center={[place.latitude, place.longitude]}
            radius={7}
            pathOptions={{
              color: '#ffffff',
              weight: 2,
              fillColor: '#059669',
              fillOpacity: 0.9,
            }}
          >
            <Popup>
              <div className="text-xs space-y-1 p-0.5">
                <div className="font-semibold text-foreground flex items-center gap-1">
                  <Radio size={12} className="text-emerald-600" />
                  {place.name}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {place.city} · Monitored Location
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full mt-2 h-6 text-[10px]"
                  onClick={() =>
                    selectLocation({
                      name: place.name,
                      city: place.city,
                      area: place.area || place.name,
                      latitude: place.latitude,
                      longitude: place.longitude,
                    })
                  }
                >
                  Select this location
                </Button>
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {playbackRow && <CircleMarker
          key={`playback-${playbackRow.timestamp}`}
          center={[playbackRow.latitude, playbackRow.longitude]}
          radius={11}
          pathOptions={{ color: '#1d4ed8', weight: 3, fillColor: '#facc15', fillOpacity: 0.95, dashArray: '3 3' }}
        >
          <Popup>
            <div className="space-y-1 text-xs">
              <strong>{strings.map.observed}</strong>
              <div>{playbackRow.area}, {playbackRow.city}</div>
              <time dateTime={playbackRow.timestamp}>{new Date(playbackRow.timestamp).toLocaleString()}</time>
              <div>{playbackRow.current_speed_kmh ?? '—'} km/h · {playbackRow.congestion_percent ?? '—'}% congestion</div>
            </div>
          </Popup>
        </CircleMarker>}

        {/* Selected Active Location Marker */}
        <CircleMarker
          center={[location.latitude, location.longitude]}
          radius={10}
          pathOptions={{
            color: '#ffffff',
            weight: 3,
            fillColor: '#2563eb',
            fillOpacity: 1,
          }}
        >
          <Popup>
            <div className="text-xs space-y-1 p-0.5">
              <strong className="text-sm text-foreground flex items-center gap-1">
                <MapPin size={13} className="text-primary" />
                {location.area}
              </strong>
              <div className="text-muted-foreground">{location.city}</div>
              <div className="text-[10px] text-muted-foreground">
                {location.latitude.toFixed(4)}° N, {location.longitude.toFixed(4)}° E
              </div>
            </div>
          </Popup>
        </CircleMarker>
      </MapContainer>

      {playbackOpen && <div className="absolute bottom-[3.6rem] left-3 right-3 z-[1000] rounded-md border border-border bg-card/95 p-2.5 shadow-md backdrop-blur" aria-label="Observed traffic playback">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs font-semibold">{strings.map.observed}</span>
          <Button size="icon" variant="outline" className="h-8 w-8" onClick={() => playbackRows.length && setPlaybackPlaying(value => !value)} disabled={playbackRows.length < 2 || playbackLoading} aria-label={playbackPlaying ? 'Pause playback' : 'Play observations'}>
            {playbackPlaying ? <Pause size={14} /> : <Play size={14} />}
          </Button>
          {playbackLoading ? <span role="status" className="text-xs text-muted-foreground">{strings.state.loading}</span> : playbackRows.length > 0 ? <>
            <input type="range" min={0} max={playbackRows.length - 1} value={playbackIndex} onChange={event => { setPlaybackPlaying(false); setPlaybackIndex(Number(event.target.value)); }} className="min-w-28 flex-1 accent-primary" aria-label="Select observed playback time" />
            <time className="text-xs tabular-nums" dateTime={playbackRow?.timestamp}>{playbackRow ? new Date(playbackRow.timestamp).toLocaleString() : ''}</time>
            <span className="text-xs text-muted-foreground">{playbackIndex + 1} / {playbackRows.length}</span>
          </> : <span role={playbackError.includes('No stored') ? 'status' : 'alert'} className="text-xs text-muted-foreground">{playbackError || strings.map.noHistory}</span>}
          {playbackRows.length === 0 && !playbackLoading && <Button size="sm" variant="ghost" onClick={() => { setPlaybackRows([]); void loadPlayback(); }}>{strings.state.retry}</Button>}
        </div>
      </div>}

      {/* Traffic Map Legend */}
      <div className="absolute bottom-0 left-0 right-0 z-[1000] bg-card/95 backdrop-blur-md border-t border-border px-4 py-2 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-4 flex-wrap">
          <span className="font-bold text-[11px] tracking-wider uppercase text-muted-foreground">
            {metric === 'congestion' ? `${strings.map.congestion}:` : metric === 'travelTime' ? `${strings.map.travelTime}:` : metric === 'speed' ? `${strings.map.speed}:` : `${strings.map.confidence}:`}
          </span>
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#059669]" />
            <span className="text-foreground text-[11px]">{metric === 'congestion' ? 'Low (&lt;30%)' : metric === 'speed' ? 'Near free-flow' : metric === 'travelTime' ? 'Near free-flow time' : 'High (≥80%)'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#eab308]" />
            <span className="text-foreground text-[11px]">{metric === 'congestion' ? 'Moderate (30–59%)' : metric === 'speed' ? 'Reduced speed' : metric === 'travelTime' ? 'Elevated travel time' : 'Medium (50–79%)'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#dc2626]" />
            <span className="text-foreground text-[11px]">{metric === 'congestion' ? 'Heavy (≥60%)' : metric === 'speed' ? 'Low speed' : metric === 'travelTime' ? 'High delay ratio' : 'Low (<50%)'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#64748b]" />
            <span className="text-foreground text-[11px]">Data Unavailable</span>
          </div>
        </div>

        <div className="text-[10px] text-muted-foreground flex items-center gap-2">
          <span>Click road for segment details</span>
          <span>·</span>
          <span>Click map to relocate</span>
        </div>
      </div>
    </div>
  );
}
