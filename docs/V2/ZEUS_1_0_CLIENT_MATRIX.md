# Zeus 1.0.0 client matrix row (ZCP-124)

Python row for [ZE-77](https://kotenai.atlassian.net/browse/ZE-77). This does not
award design-repo MATRIX `supported`. Claim level stays **candidate**.

| Field | Value |
| --- | --- |
| Zeus | 1.0.0 |
| Package | `kotenai-zeus-client` |
| Available tag | `v2.5.1` |
| Auth on that tag | `basic`, `bearer`, `session`. Production profile rejects `auth_mode=none`. |
| Auth not released on that tag | `pat` ([ZCP-123](https://kotenai.atlassian.net/browse/ZCP-123)), `m2m` ([ZCP-122](https://kotenai.atlassian.net/browse/ZCP-122)) |

`v2.5.1` is the available client package (`git tag v2.5.1`, `pyproject.toml`
version `2.5.1`). `v2.4.1` is the previous tag and has `basic`, `bearer`, and
`session` only. This tag contains the PAT and M2M mint code and keeps both
modes disabled until ZE-360 and ZE-361 (`ENABLED_UNRELEASED_AUTH_MODES` is
empty). The tag that enables PAT and M2M is the next package tag cut after
those Zeus tickets ship and the allow-list is opened. This release does not
open that allow-list.

## ZCP-1 leftover

[ZCP-1](https://kotenai.atlassian.net/browse/ZCP-1) is still **In Review**. No
open child blocks Done (`parent = ZCP-1 AND statusCategory != Done` is empty).
The leftover is review of the epic, not a missing runtime story. This task does
not rewrite the V2 runtime.
