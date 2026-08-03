# HUD fixture provenance

All fixtures are fresh real responses captured 2026-07-13 from HUD USER with the
configured JWT in the documented Bearer header. `fmr.json` and `income_limits.json`
use the verified Austin entity `METRO12420M12420` for FY 2024. The USPS county/CBSA
fixtures use ZIP 78701 and the live 2026 Q1 crosswalk. The newly created token returned
401 briefly while account access propagated, then all four endpoints returned 200.
All HUD fixtures are live-confirmed.
