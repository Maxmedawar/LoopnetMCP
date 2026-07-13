# Census fixture provenance

- `geocoder.json` is a real response captured 2026-07-13 from the official Census
  geocoder for 1100 Congress Ave, Austin, TX. Unused geography layers were trimmed.
- `acs5_profile.json` follows the official ACS API response schema but is representative:
  anonymous ACS requests redirected to `missing_key.html` with
  `X-DataWebAPI-KeyError: 1` during capture. **# VERIFY against live response** once a
  Census key is available.
- `building_permits.json` is representative. **# VERIFY against live response**.
