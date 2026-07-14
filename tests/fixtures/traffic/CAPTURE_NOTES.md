# Traffic fixture capture notes

Captured live on 2026-07-13 from the public ArcGIS query endpoints configured in
`STATE_AADT_ENDPOINTS`. Each response included WGS84 geometry or explicit latitude/
longitude fields and the exact AADT, year, and route fields used by the adapter.

- NC: NCDOT 2024 AADT Stations, `services.arcgis.com/NuWFvHYDMVmmxMeM`
- AZ: ADOT 2024 Average Annual Daily Traffic, `services6.arcgis.com/clPWQMwZfdWn4MQZ`
- CO: CDOT Highways Traffic Counts, `dtdapps.codot.gov`
- TX: TxDOT AADT Annuals Public View, `services.arcgis.com/KTcxiTD9dsQw4r7Z`
- FL: FDOT RCI Annual Average Daily Traffic, `gis.fdot.gov`
- CA: Caltrans 2023 Traffic AADT, `caltrans-gis.dot.ca.gov`
- NV: NDOT FY2025 TRINA AADT routes, `services9.arcgis.com/eNX73FDxjlKFtCtH`
- GA: GDOT AADT station mirror published by DeKalb County GIS,
  `services2.arcgis.com/IxVN2oUE9EYLSnPE`

All eight endpoints and schemas were confirmed live; none is `# VERIFY`.
