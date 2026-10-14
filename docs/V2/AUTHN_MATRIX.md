# Client authn matrix (ZCP-125)

Client checks for basic, PAT, and M2M. Scoped basic is the existing mint
(`POST /v1/{bucket}/{scope}/auth/session`). The Zeus suite script stays on
[ZE-365](https://kotenai.atlassian.net/browse/ZE-365). This file is the client
result sheet that can sit beside that ticket.

A missing row fails `tests/unit/adapters/test_authn_matrix.py`.

| Case | Basic | PAT | M2M |
| --- | --- | --- | --- |
| Missing credential on a verb | `missing_credential_basic` | `missing_credential_pat` | `missing_credential_m2m` |
| Wrong secret or expired JWT | `wrong_secret_basic` | `wrong_secret_pat` | `wrong_secret_m2m` |
| Good mint, then one V2 verb | `good_verb_basic` | `good_verb_pat` | `good_verb_m2m` |
| Cross-scope session | `cross_scope_basic` | `cross_scope_pat` | `cross_scope_m2m` |
| Revoke or hard TTL | n/a | `revoke_pat` | n/a (exp is `wrong_secret_m2m`) |
| Lockout | `lockout_basic` | n/a | n/a |
| Issuer unset | n/a | n/a | `issuer_unset_m2m` |
| Wrong aud or iss | n/a | n/a | `wrong_aud_m2m`, `wrong_iss_m2m` |

`dev_no_auth` stays off. No cell URL contains `dev_no_auth`.

Missing credentials and an unset M2M issuer are refused before a verb is sent.
The live ZE-365 check for those cells is HTTP 401 from Zeus. Lockout surfaces
HTTP 429 from the basic mint. The other 401 cells surface the mint status.
Cross-scope refuses to reuse the other scope's session id.
