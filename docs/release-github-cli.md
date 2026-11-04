# Qualified GitHub CLI for release operations

Generated release jobs install official GitHub CLI **2.102.0**, built with **Go 1.27.1**,
before prepare, candidate publication, stable promotion and final publication.
`.github/gh/release.json` pins both archive and extracted executable SHA-256 for
native Linux/macOS amd64/arm64. The checksums were checked against the official
[release](https://github.com/cli/cli/releases/tag/v2.102.0) and all four binaries
were inspected with `go version -m`. Source commit:
`fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd`. The upstream MIT notice is retained in
`.github/gh/LICENSE`; `gh licenses` lists the binary's dependency notices.

The installer requires Go 1.27.2 to run a small standard-library-only HTTPS
downloader under `GODEBUG=fips140=on`. It rejects HTTP, HTTPS downgrade redirects,
more than ten redirects, oversized responses and errors. No operator credential
is sent to the download endpoint. The installer checks the archive, reads exactly
one regular executable member without extracting paths, checks its hash and
version, and atomically replaces the selected output only after validation.
`--check` needs no Go compiler: the exact binary hash identifies the inspected
Go build and requires the same FIPS runtime setting. Unsupported platforms fail.

`--archive FILE --output PATH` installs an already downloaded archive without
network access or a Go compiler. The same size, archive hash, native executable
hash, FIPS runtime setting, version and atomic replacement checks still apply;
an invalid archive never falls back to downloading. Private runner image builds
use this mode after a bounded, unauthenticated HTTPS download. This does not
change the online installer's Go-based FIPS transport profile.

For local release helper use, select Go 1.27.2 on PATH, then:

```sh
export GODEBUG=fips140=on
python3 scripts/install_release_gh.py --output .release-tools/gh
export PATH="$PWD/.release-tools:$PATH"
export GH_HOST=github.com
python3 scripts/install_release_gh.py --check "$(command -v gh)"
python3 scripts/release.py doctor
```

Keep normal maintainer authentication in place. Do not use arbitrary extensions,
custom hosts, insecure TLS options, aliases or a replacement `gh` in this profile.
CI selects a dedicated CLI configuration directory and the existing explicit
GitHub token; permissions and publication approvals do not change. Build tools
and GitHub Actions have their own pins and are not described as part of this
runtime qualification.

The actual executable is tested against synthetic HTTPS endpoints under TLS 1.2
and 1.3. Ordinary-mode controls prove the fixtures work; FIPS mode accepts the
strong chain and rejects 1024-bit RSA at the leaf, intermediate and root before
HTTP. The test uses only temporary trust and synthetic tokens. It neither changes
the OS trust store nor connects to a real authenticated service.

## Scoped dependency assessment — 2026-10-16

This covers `gh api`, `gh repo view`, `gh workflow run`, `gh run list` and
`gh release upload` in the checked-in release helpers. It does not claim that
all CLI commands or dependencies are free of advisories. Binary scanning reports
13 records: twelve first published on 2026-10-08, and an older legacy OpenPGP
record. Eleven recent records are noncritical and remain open for the next
runtime/dependency update, before the 60-day deadline on 2026-12-07.

[GO-2026-6612](https://pkg.go.dev/vuln/GO-2026-6612) is critical but requires an
HTTP/2 server. These commands use outbound clients and do not start that server:
[client factory](https://github.com/cli/cli/blob/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd/api/http_client.go),
[API request loop](https://github.com/cli/cli/blob/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd/pkg/cmd/api/api.go),
[release upload](https://github.com/cli/cli/blob/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd/pkg/cmd/release/shared/upload.go).
[GO-2026-5932](https://pkg.go.dev/vuln/GO-2026-5932) concerns unmaintained OpenPGP;
the exact source's `go list -deps ./cmd/gh` includes no OpenPGP package. Its
module-only wildcard result does not establish a linked or used vulnerable path.

Reassess after an upstream release, a command change or a new advisory. This
scoped assessment supports no known applicable critical or overdue vulnerability
on the stated date; it is not an indefinite exception or a blanket clean scan.

## Release read recovery and rerun validation

The legacy release publisher carries two scoped shared-toolkit backports:
[bounded GET recovery](https://github.com/victron-venus/venus-os-ci-toolkit/commit/f6b7d4dfbe44158663d6d3da8c3092932d59253a)
and [current-attempt validation](https://github.com/victron-venus/venus-os-ci-toolkit/commit/ae0b6f54b19256c1495c821fb70145eaab6be04e).
Recognized transport failures and HTTP 500/502/503/504 responses can retry a whole
GET with at most three total attempts (the initial request and up to two
retries). Metadata attempts are limited to 30 seconds; buffered
asset and Actions ZIP attempts to 120 seconds, with at most six seconds total
jitter. Failed response bytes are released before waiting or allocating the next
capture. Authentication and authorization, certificate, missing-resource and
rate-limit errors remain terminal. Publication writes
remain single attempts; streamed downloads retain their existing contract.

For reruns, the existing `validate_run` release gate reads the exact attempt's
start time and rejects successful jobs or steps copied from an earlier attempt.
Both candidate publication and RC promotion pass through this gate. First-attempt
compatibility is retained. This is a partial backport: the legacy API, release
policy revision, workflows, versions and source/Simulator release requirements
are unchanged. No version-ledger or final-build migration is included.

The required **Release tooling contracts** job discovers every `test_*.py` in
`.github/release-tests`; **Core and iOS tests** repeats them through `scripts/ci.sh`.
The focused `test_release_read_safety.py` exercises complete-response recovery,
denial handling, failed-capture release, rejected write methods on the attempt
route, actual attempt timestamps and the legacy gate.
`test_release_response_framing.py` covers partial headers and status-shaped
payload text. Keep both files and the existing release-contract suite:
`test_writes_are_not_replayed` in `test_release_control.py` protects
single-attempt write behavior.
Run these contracts without building Swift or starting a Simulator:

```sh
python3 -m unittest discover -s .github/release-tests -p 'test_*.py' -v
```

Keep the focused tests when regenerating release tooling. An older generator
can overwrite these backports, but the retained gate and recovery regressions
must fail until both fixes are reapplied. Do not replace this legacy engine with
a newer whole file without reviewing its other dependencies and release policy.
After a terminal infrastructure failure, inspect existing tags, assets and active
runs before retrying. Where the existing policy allows a retry before publication,
use **Re-run all jobs** at the unchanged source; an earlier attempt's successful
validation does not qualify a later attempt.
