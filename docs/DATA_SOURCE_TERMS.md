# Data-source terms and operating limits

Reviewed 2026-11-21. Re-check provider terms before release; terms, plans, quotas, and public service policies can change.

## TomTom Search, Traffic, and Routing APIs

- The backend uses TomTom Search for city-limited place suggestions when `TOMTOM_API_KEY` is configured. Traffic/routing API calls are likewise backend-only. No API key is exposed to the browser.
- TomTom API access is subject to the product-specific terms accepted by the key owner and the applicable account plan. The project does not know the owner's account plan or whether long-term storage, redistribution, or use with third-party data is permitted. Confirm those terms in the current MyTomTom account before enabling scheduled collection or publishing stored provider values.
- Automatic collection and retraining remain disabled by default. Quota checks run before TomTom requests. Do not commit keys or place them in frontend environment variables.
- The general [TomTom Terms of Use](https://www.tomtom.com/en-us/legal/terms-of-use/) and [TomTom API product documentation](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/product-information/introduction) are references, not a substitute for the product/account agreement.

## OpenStreetMap

- Base map tiles are requested by the browser from the Standard raster tile service. Keep the visible `© OpenStreetMap contributors` attribution and do not prefetch tiles. The service has limited capacity and best-effort availability; it is not a production tile-hosting SLA. Follow the current [Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/).
- The backend and frontend no longer fall back to public Nominatim for type-ahead suggestions. Its current [Usage Policy](https://operations.osmfoundation.org/policies/nominatim/) forbids autocomplete and sets tight usage limits. If geocoding without TomTom is needed, choose a provider whose terms allow this UI pattern or operate an appropriately provisioned service.
- OpenStreetMap database content is provided under the Open Database License (ODbL); tile service access and data licensing are distinct. See [OpenStreetMap copyright and license](https://www.openstreetmap.org/copyright).

## Local traffic data and synthetic demo values

- Imported observations must retain provenance and pass the project validators. Check the source dataset's own license and terms before import or redistribution; the project cannot grant rights to externally sourced data.
- `SyntheticSource` is demo-only. Synthetic records must remain labelled and separated from measured real-world evaluation.
