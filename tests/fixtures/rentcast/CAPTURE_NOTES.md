# RentCast fixture capture notes

`# VERIFY against live response`: Max has not configured `CRE_RENTCAST_API_KEY`, so
the representative AVM fixture follows RentCast's official published schema for
`GET /v1/avm/rent/long-term`. The endpoint path, `X-Api-Key` authentication, and
fields (`rent`, `comparables[].price`) were confirmed in the official API docs.
