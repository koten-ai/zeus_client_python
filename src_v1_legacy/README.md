# V1 free-function tree archive (0.3.1)

Historical reference only — **not installed** by the `kotenai-zeus-client` 2.0+ package.

Public migration aid for free-function APIs is `zeus_client.compat.v1` (deprecated, ≤1 minor).

Session create, turn, and trace in this archive include `bucket` and `scope` only when both sides are non-empty (ZCP-120). The installed package applies the same rule, and it rejects `auth_mode=pat` and `auth_mode=m2m` with `FEATURE_DISABLED` until ZE-360 and ZE-361.
