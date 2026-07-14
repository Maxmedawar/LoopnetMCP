# Phase 15 live capture notes

- `guilford_sales.json` was captured 2026-07-13 from Guilford County's official
  `Tax/GCCadastral_FeatureToPointWGS84/FeatureServer/0` query endpoint. The live layer exposes
  package sale price/date, heated area, units, building description, revenue-stamp source, and
  WGS84 point geometry.
- `yavapai_sale.json` was captured 2026-07-13 from Yavapai County's official
  `ASR_Recent_Sales_5_years/FeatureServer/5` (`Sales- All`) endpoint. Its service description
  identifies assessor-maintained RealWare sales; the layer exposes sale price/date, validity
  flags, use type, geometry, and a county time-adjusted price, but no building square footage.
- Douglas County's verified public ArcGIS parcel/account services were inspected live but no
  public sale-price layer was confirmed. It remains deliberately unwired. No Phase 15 fixture is
  marked `# VERIFY`.
