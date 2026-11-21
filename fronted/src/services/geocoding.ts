import type { Location } from '@/types/traffic';
let lastRequest = 0;
export async function searchPlaces(query: string, cityScope?: string): Promise<Location[]> {
  const wait = Math.max(0, 1100 - (Date.now() - lastRequest));
  await new Promise(resolve => setTimeout(resolve, wait));
  lastRequest = Date.now();
  const scopedQuery = cityScope?.trim() && !query.toLocaleLowerCase().includes(cityScope.toLocaleLowerCase())
    ? `${query}, ${cityScope.trim()}`
    : query;
  const params = new URLSearchParams({ q: scopedQuery, format: 'json', addressdetails: '1', limit: '5', countrycodes: 'in' });
  const response = await fetch(`https://nominatim.openstreetmap.org/search?${params}`, { headers: { 'Accept-Language': 'en' }, signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error('Location search is temporarily unavailable. Select a point on the map instead.');
  const data = await response.json() as { lat: string; lon: string; display_name: string; address: Record<string, string> }[];
  const places = data.map(item => ({ latitude: Number(item.lat), longitude: Number(item.lon), city: item.address['city'] || item.address['town'] || item.address['village'] || item.address['county'] || 'Selected location', area: item.address['suburb'] || item.address['road'] || item.address['neighbourhood'] || item.display_name.split(',')[0] || 'Selected road', name: item.display_name }));
  if (!cityScope?.trim()) return places;
  const normalizeCity = (value: string) => ({ bengaluru: 'bangalore', mangaluru: 'mangalore' }[value.trim().toLocaleLowerCase()] || value.trim().toLocaleLowerCase());
  return places.filter(place => normalizeCity(place.city) === normalizeCity(cityScope));
}
