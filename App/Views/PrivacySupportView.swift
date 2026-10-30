import SwiftUI
import InventoryCore

/// Bundled text has no inventory, entitlement or network dependency.
/// External destinations are opened only by the system Link action.
struct PrivacySupportView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                section("intro", title: UIL10n.text("privacy.intro.title"), body: UIL10n.text("privacy.intro.body"))
                section("storage", title: UIL10n.text("privacy.storage.title"), body: UIL10n.text("privacy.storage.body"))
                section("capture", title: UIL10n.text("privacy.capture.title"), body: UIL10n.text("privacy.capture.body"))
                section("sharing", title: UIL10n.text("privacy.sharing.title"), body: UIL10n.text("privacy.sharing.body"))
                section("deletion", title: UIL10n.text("privacy.deletion.title"), body: UIL10n.text("privacy.deletion.body"))
                section("apple", title: UIL10n.text("privacy.apple.title"), body: UIL10n.text("privacy.apple.body"))
                section("limits", title: UIL10n.text("privacy.limits.title"), body: UIL10n.text("privacy.limits.body"))
                section("recovery", title: UIL10n.text("privacy.recovery.title"), body: UIL10n.text("privacy.recovery.body"))
                section("support", title: UIL10n.text("privacy.support.title"), body: UIL10n.text("privacy.support.body"))
                Section {
                    externalLink(UIL10n.text("privacy.link.policy"), url: PrivacySupportLinks.document(.privacy), id: "policy")
                    externalLink(UIL10n.text("privacy.link.support"), url: PrivacySupportLinks.document(.support), id: "support")
                    externalLink(UIL10n.text("privacy.link.issues"), url: PrivacySupportLinks.issues, id: "issues")
                    externalLink(UIL10n.text("privacy.link.apple"), url: PrivacySupportLinks.apple, id: "apple")
                    externalLink(UIL10n.text("privacy.link.github"), url: PrivacySupportLinks.github, id: "github")
                } header: {
                    Text(UIL10n.text("privacy.links.title"))
                } footer: {
                    Text(UIL10n.text("privacy.links.footer"))
                }
            }
            .accessibilityIdentifier("privacy.content")
            .navigationTitle(UIL10n.text("privacy.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(UIL10n.text("Done")) { dismiss() }
                        .accessibilityIdentifier("privacy.done")
                }
            }
        }
    }

    private func section(_ id: String, title: String, body: String) -> some View {
        Section {
            Text(body)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
                .accessibilityIdentifier("privacy.\(id).body")
        } header: {
            Text(title).accessibilityAddTraits(.isHeader)
        }
    }

    private func externalLink(_ title: String, url: URL, id: String) -> some View {
        Link(destination: url) {
            Label(title, systemImage: "arrow.up.right.square")
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityHint(UIL10n.text("privacy.link.hint"))
        .accessibilityIdentifier("privacy.link.\(id)")
    }
}

enum PrivacySupportLinks {
    enum Document: String, CaseIterable { case privacy, support }

    // Published preview documents remain reachable before the feature PR merges.
    static let revision = "0d0f7eb75d8c9a9c42e3a8dc1b8d3f350b12776e"
    static let issues = URL(string: "https://github.com/4alvit/room-inventory-ios/issues")!
    static let apple = URL(string: "https://www.apple.com/legal/privacy/data/en/app-store/")!
    static let github = URL(string: "https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement")!

    static func document(_ document: Document, language: String? = nil) -> URL {
        let selected = InventoryLocalization.preferredLanguage(bundle: .main, language: language)
        let suffix = selected == "ru" ? ".ru" : ""
        return URL(string: "https://github.com/4alvit/room-inventory-ios/blob/\(revision)/docs/\(document.rawValue)\(suffix).md")!
    }
}
