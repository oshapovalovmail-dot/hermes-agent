# Yandex search providers

Explicit profile-local `WebSearchProvider` plugins; not bundled or auto-enabled.
See `../../README.md` for settings and local installation. `yandex` POSTs only the
query to the public SearchAPI URL. `yandex-context` is registered only with an
explicit configured HTTPS endpoint using the expected workflow envelope.
No default private workflow URL, credentials, cookies or browser is included.

Normal system trust/proxies, TLS hostname verification, no redirects, no retries,
no backend fallback. Generated summaries are labeled separately from source
snippets; citation IDs survive ordering. Source snippets are bounded at 4000
characters with truncation metadata. Malformed responses, rejections, HTTP errors
and cancellation are failures, not fabricated empty successes. Tests in
`tests/integrations/test_yandex_provider.py` mock HTTP; they are not evidence of
live endpoint availability. The network/provider has not been called by this port.
