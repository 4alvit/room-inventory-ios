import XCTest
import UIKit

@MainActor
final class TestWindowHost {
    private enum LifecycleError: Error {
        case rootDidNotAppear
        case contentDidNotAppear
    }

    @MainActor
    private final class Container: UIViewController {
        let content: UIViewController?
        private(set) var hasAppeared = false

        init(content: UIViewController? = nil) {
            self.content = content
            super.init(nibName: nil, bundle: nil)
        }

        required init?(coder: NSCoder) {
            fatalError("init(coder:) is not supported by this test fixture")
        }

        override func viewDidLoad() {
            super.viewDidLoad()
            guard let content else { return }
            addChild(content)
            content.view.translatesAutoresizingMaskIntoConstraints = false
            view.addSubview(content.view)
            NSLayoutConstraint.activate([
                content.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
                content.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
                content.view.topAnchor.constraint(equalTo: view.topAnchor),
                content.view.bottomAnchor.constraint(equalTo: view.bottomAnchor)
            ])
            content.didMove(toParent: self)
        }

        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            hasAppeared = true
        }

        override func viewDidDisappear(_ animated: Bool) {
            super.viewDidDisappear(animated)
            hasAppeared = false
        }
    }

    let window: UIWindow
    private let previousKeyWindow: UIWindow?
    private let root = Container()
    private let presentation: Container
    private let beforeDismiss: @MainActor () -> Void

    init(_ controller: UIViewController,
         beforeDismiss: @escaping @MainActor () -> Void = {}) throws {
        self.beforeDismiss = beforeDismiss
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }.first)
        previousKeyWindow = scene.windows.first(where: \.isKeyWindow)
        window = UIWindow(windowScene: scene)
        window.frame = scene.coordinateSpace.bounds
        presentation = Container(content: controller)
        presentation.modalPresentationStyle = .fullScreen
        window.rootViewController = root
    }

    private func waitUntil(_ condition: () -> Bool) async -> Bool {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(5))
        while !condition() {
            guard clock.now < deadline else { return false }
            do { try await Task.sleep(for: .milliseconds(20)) }
            catch { return false }
        }
        return true
    }

    func show(makeKey: Bool = true) async throws {
        if makeKey { window.makeKeyAndVisible() }
        else { window.isHidden = false }
        window.layoutIfNeeded()
        guard await waitUntil({ root.hasAppeared && root.view.window === window }) else {
            throw LifecycleError.rootDidNotAppear
        }
        var completed = false
        root.present(presentation, animated: false) { completed = true }
        guard await waitUntil({ completed && presentation.hasAppeared
            && presentation.view.window === window }) else {
            throw LifecycleError.contentDidNotAppear
        }
    }

    func close() async {
        beforeDismiss()
        if presentation.presentingViewController != nil {
            var completed = false
            presentation.dismiss(animated: false) { completed = true }
            let disappeared = await waitUntil({ completed && !presentation.hasAppeared
                && presentation.presentingViewController == nil && root.hasAppeared })
            XCTAssertTrue(disappeared, "Test presentation did not complete its real dismissal")
        }
        window.isHidden = true
        window.rootViewController = nil
        previousKeyWindow?.makeKey()
    }

    static func withHost(_ controller: UIViewController, makeKey: Bool = true,
                         beforeDismiss: @escaping @MainActor () -> Void = {},
                         body: (TestWindowHost) async throws -> Void) async throws {
        let host = try TestWindowHost(controller, beforeDismiss: beforeDismiss)
        do {
            try await host.show(makeKey: makeKey)
            try await body(host)
        } catch {
            await host.close()
            throw error
        }
        await host.close()
    }
}
