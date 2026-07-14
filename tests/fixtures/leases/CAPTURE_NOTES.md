# Lease fixtures — REAL executed leases from SEC EDGAR (public EX-10 exhibits)

Captured live 2026-07-14 via EDGAR full-text search (`efts.sec.gov/LATEST/search-index`),
User-Agent per SEC fair-access policy. These are genuine executed commercial leases filed
as material contracts — NOT invented fixtures. Used to prove the W1 lease-abstraction
engine against real documents (project rule: no mocked proof).

| File | What | Source |
|------|------|--------|
| `retail_lease_dollar_tree.htm` | Full shopping-center lease, Dollar Tree (national retail tenant); base rent, CAM, percentage rent, options, notices | sec.gov/Archives/edgar/data/935703/000093570308000059/ex10_3.htm |
| `retail_lease_community_bancorp.htm` | Full shopping-center lease (bank branch pad), 18k words, heavy CAM + notices | sec.gov/Archives/edgar/data/1089503/000119312505050828/dex1023.htm |
| `retail_lease_acpt.htm` | Full retail lease, American Community Properties Trust; CAM 41 refs, pct rent 15 refs | sec.gov/Archives/edgar/data/1065645/000106564505000027/lease.htm |
| `office_lease_cvent.htm` | Short-form office lease (Cvent, 8180 Greensboro Dr McLean VA) | sec.gov/Archives/edgar/data/1122897/000119312513284555/d520989dex102.htm |
| `office_lease_amendment_13th.htm` | Thirteenth Amendment to Deed of Office Lease (Alarm.com) — amendment-chain specimen | sec.gov/Archives/edgar/data/1459200/000145920023000028/ex101thirteenthamendment.htm |

Selection method note: EDGAR FTS ranks short amendments above full leases on naive queries,
and returns PSAs/press releases that merely *mention* leases. Verified each specimen by
word count + clause-marker density (base rent / CAM / percentage rent / options /
commencement / notice) before keeping. Two early mislabeled grabs (PSAs) were discarded.
