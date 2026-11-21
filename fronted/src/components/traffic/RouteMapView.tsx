import { lazy, Suspense } from 'react';
import { ClientOnly } from '@tanstack/react-router';
import { Loader2 } from 'lucide-react';
import type { RouteMapProps } from './RouteMap';

const ClientRouteMap = lazy(() =>
  import('./RouteMap').then(module => ({ default: module.RouteMap }))
);

export function RouteMapView(props: RouteMapProps) {
  const fallback = (
    <div
      className="flex h-[480px] min-h-[380px] items-center justify-center gap-2 rounded-xl border border-border bg-muted/20 text-sm text-muted-foreground sm:h-[500px] lg:h-[520px]"
      aria-label="Loading route map"
    >
      <Loader2 className="animate-spin text-primary" size={20} />
      <span>Loading route map…</span>
    </div>
  );

  return (
    <ClientOnly fallback={fallback}>
      <Suspense fallback={fallback}>
        <ClientRouteMap {...props} />
      </Suspense>
    </ClientOnly>
  );
}
