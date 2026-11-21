import { lazy, Suspense } from 'react';
import { ClientOnly } from '@tanstack/react-router';
import { Loader2 } from 'lucide-react';
import type { TrafficReading, TrafficSegment } from '@/types/traffic';

const Canvas = lazy(() => import('./HotspotMapCanvas'));

export interface HotspotMapProps {
  segments?: TrafficSegment[] | undefined;
  selectedSegmentId?: string | null | undefined;
  onSelectSegment?: ((segmentId: string) => void) | undefined;
  readings?: TrafficReading[] | undefined;
  center?: [number, number] | undefined;
  height?: number | string;
  isExpanded?: boolean | undefined;
  onToggleExpand?: (() => void) | undefined;
}

export function HotspotMap({
  segments,
  selectedSegmentId,
  onSelectSegment,
  readings,
  center,
  height = 420,
  isExpanded = false,
  onToggleExpand,
}: HotspotMapProps) {
  const fallback = (
    <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="animate-spin" size={16} />
      <span>Loading hotspot map…</span>
    </div>
  );

  return (
    <div
      className={`relative w-full overflow-hidden rounded-xl border border-border bg-card shadow-sm transition-all ${
        isExpanded ? 'h-full flex-1 min-h-[480px]' : ''
      }`}
      style={!isExpanded ? { height } : undefined}
    >
      <ClientOnly fallback={fallback}>
        <Suspense fallback={fallback}>
          <Canvas
            segments={segments}
            selectedSegmentId={selectedSegmentId}
            onSelectSegment={onSelectSegment}
            readings={readings}
            center={center}
            isExpanded={isExpanded}
            onToggleExpand={onToggleExpand}
          />
        </Suspense>
      </ClientOnly>
    </div>
  );
}
