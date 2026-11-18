# Documentation

Room Inventory, a SwiftUI app for recording what is in each room, documented from
the data contract through App Store materials.

## Product

- [Architecture and data contract](implementation-contract.md) — the SwiftUI app, its local package and the data model.
- [Localization](localization.md) — English as development fallback and Russian.
- [App Store submission copy](app-store-submission.md) — the 2026-10-25 draft against a named preview baseline.
- [App Store screenshot candidates](app-store/screenshots/README.md) — seven Simulator captures across languages and devices.

## Release

- [Application release checklist](release-checklist.md) — what to record against an exact SHA and tag.
- [Device build and App Store handoff](device-release.md) — why the public preview build cannot be shipped.
- [Qualified GitHub CLI for release operations](release-github-cli.md) — the pinned CLI and Go versions.
- [CI and release operations](release-workflow.md) — `.release-policy.json` and the required status.
- [Exercise a published unsigned RC on hosted Simulators](rc-hosted-acceptance.md) — testing the downloaded release rather than a rebuild.

## Regressions

- [Recovery journey regression](recovery-journey.md) — the opt-in UI data-loss regression.
- [Hosted recovery scenario](recovery-hosted.md) — the hosted adapter for that journey.

## Published text

- [Privacy — development preview](privacy.md) — the English privacy text.
- [Конфиденциальность — предварительная версия](privacy.ru.md) — the Russian privacy text.
- [Support and recovery](support.md) — the English support text.
- [Поддержка и восстановление](support.ru.md) — the Russian support text.
