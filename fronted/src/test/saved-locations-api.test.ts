import { beforeEach, describe, expect, it } from 'vitest';
import {
  createSavedLocation,
  deleteSavedLocation,
  getSavedLocations,
  updateSavedLocation,
} from '@/services/api';

describe('personal saved locations', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('creates and reads locations without calling the backend', async () => {
    const location = await createSavedLocation({
      name: 'Home', label: 'Home', address: 'Central Pune', city: 'Pune',
      area: 'Central Pune', latitude: 18.52, longitude: 73.85,
    });

    expect(location.id).toBeTruthy();
    expect((await getSavedLocations())[0]?.name).toBe('Home');
  });

  it('updates and removes locations from browser storage', async () => {
    const location = await createSavedLocation({
      name: 'Home', label: 'Home', address: 'Central Pune', city: 'Pune',
      area: 'Central Pune', latitude: 18.52, longitude: 73.85,
    });

    const updated = await updateSavedLocation(location.id, { name: 'Apartment' });
    expect(updated.name).toBe('Apartment');
    await deleteSavedLocation(location.id);
    expect(await getSavedLocations()).toEqual([]);
  });
});
