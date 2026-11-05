import XCTest
import UIKit
@testable import RoomInventory

@MainActor
final class NameEntryTextFieldTests: XCTestCase {
    private final class TrackingTextField: UITextField {
        private(set) var focusRequests = 0
        var permitsFocus = true

        override func becomeFirstResponder() -> Bool {
            focusRequests += 1
            guard permitsFocus else { return false }
            return super.becomeFirstResponder()
        }
    }

    @MainActor
    private final class WindowHost {
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

        init(_ controller: UIViewController) throws {
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
            (presentation.content as? NameEntryTextField.Controller)?.dismantle()
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
    }

    private func withWindowHost(_ controller: UIViewController, makeKey: Bool = true,
                                body: (WindowHost) async throws -> Void) async throws {
        let host = try WindowHost(controller)
        do {
            try await host.show(makeKey: makeKey)
            try await body(host)
        } catch {
            await host.close()
            throw error
        }
        await host.close()
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

    private func configure(_ controller: NameEntryTextField.Controller,
                           text: String = "Home", enabled: Bool = true,
                           onChange: @escaping (String) -> Void = { _ in },
                           onSubmit: @escaping () -> Void = {}) {
        controller.configure(text: text, placeholder: "Home name", enabled: enabled,
                             onChange: onChange, onSubmit: onSubmit)
    }

    func testPresentationOwnsRealResponderAndUpdatesPreserveFieldAndSelection() async throws {
        let field = TrackingTextField()
        let controller = NameEntryTextField.Controller(textField: field)
        configure(controller, text: "Main home")
        try await withWindowHost(controller) { host in
            guard await waitUntil({ field.isFirstResponder }) else {
                XCTFail("Presented name field never became the actual first responder")
                return
            }
            let start = try XCTUnwrap(field.position(from: field.beginningOfDocument, offset: 1))
            let end = try XCTUnwrap(field.position(from: field.beginningOfDocument, offset: 4))
            field.selectedTextRange = try XCTUnwrap(field.textRange(from: start, to: end))

            for _ in 0..<3 { configure(controller, text: "Main home") }

            XCTAssertTrue(controller.textField === field)
            XCTAssertTrue(field.isFirstResponder)
            XCTAssertEqual(field.focusRequests, 1)
            XCTAssertEqual(field.text, "Main home")
            let selection = try XCTUnwrap(field.selectedTextRange)
            XCTAssertEqual(field.offset(from: field.beginningOfDocument, to: selection.start), 1)
            XCTAssertEqual(field.offset(from: field.beginningOfDocument, to: selection.end), 4)
            XCTAssertEqual(field.accessibilityIdentifier, "entry.name")
            XCTAssertEqual(field.placeholder, "Home name")
            XCTAssertEqual(field.returnKeyType, .done)
            XCTAssertTrue(field.adjustsFontForContentSizeCategory)

            XCTAssertTrue(field.resignFirstResponder())
            configure(controller, text: "Main home")
            NotificationCenter.default.post(name: UIWindow.didBecomeKeyNotification, object: host.window)
            XCTAssertFalse(field.isFirstResponder, "A normal update must not undo intentional focus dismissal")
            XCTAssertEqual(field.focusRequests, 1)
        }
    }

    func testNonKeyPresentationDefersItsSingleRequestUntilItsOwnWindowBecomesKey() async throws {
        try await withWindowHost(UIViewController()) { blocker in
            let field = TrackingTextField()
            let controller = NameEntryTextField.Controller(textField: field)
            configure(controller)
            try await withWindowHost(controller, makeKey: false) { host in
                guard await waitUntil({ controller.view.window === host.window }) else {
                    XCTFail("Name field was not attached to its non-key window")
                    return
                }
                XCTAssertFalse(host.window.isKeyWindow)
                XCTAssertTrue(blocker.window.isKeyWindow)
                XCTAssertEqual(field.focusRequests, 0)
                NotificationCenter.default.post(name: UIWindow.didBecomeKeyNotification, object: blocker.window)
                XCTAssertEqual(field.focusRequests, 0, "Another window cannot admit the name field")

                host.window.makeKey()
                guard await waitUntil({ field.isFirstResponder }) else {
                    XCTFail("The pending name field did not acquire focus when its own window became key")
                    return
                }
                XCTAssertEqual(field.focusRequests, 1)
            }
        }
    }

    func testRejectedResponderRequestIsNotRetriedByConfigurationOrKeyNotifications() async throws {
        let field = TrackingTextField()
        field.permitsFocus = false
        let controller = NameEntryTextField.Controller(textField: field)
        configure(controller)
        try await withWindowHost(controller) { host in
            guard await waitUntil({ field.focusRequests == 1 }) else {
                XCTFail("Expected one admitted responder request")
                return
            }
            field.permitsFocus = true
            configure(controller, text: "Updated home")
            NotificationCenter.default.post(name: UIWindow.didBecomeKeyNotification, object: host.window)
            XCTAssertEqual(field.focusRequests, 1)
            XCTAssertFalse(field.isFirstResponder)
        }
    }

    func testConfigurationDoesNotOverwriteAnActiveMarkedTextComposition() async throws {
        let field = TrackingTextField()
        let controller = NameEntryTextField.Controller(textField: field)
        var submissions = 0
        configure(controller, text: "", onSubmit: { submissions += 1 })
        try await withWindowHost(controller) { _ in
            guard await waitUntil({ field.isFirstResponder }) else {
                XCTFail("Name field did not acquire focus for composition")
                return
            }
            field.setMarkedText("に", selectedRange: NSRange(location: 1, length: 0))
            XCTAssertNotNil(field.markedTextRange, "The fixture must establish a real marked composition")
            let composingText = field.text
            configure(controller, text: "stale binding", onSubmit: { submissions += 1 })
            XCTAssertEqual(field.text, composingText)
            XCTAssertNotNil(field.markedTextRange)
            XCTAssertTrue(field.isFirstResponder)
            XCTAssertEqual(field.focusRequests, 1)
            _ = field.delegate?.textFieldShouldReturn?(field)
            XCTAssertEqual(submissions, 0, "Return must not submit an unfinished composition")
            field.unmarkText()
            configure(controller, text: "Committed name")
            XCTAssertEqual(field.text, "Committed name")
        }
    }

    func testEditingUsesLatestBindingAndReturnIsSuppressedWhileSaving() throws {
        let controller = NameEntryTextField.Controller()
        defer { controller.dismantle() }
        var oldChanges: [String] = []
        var currentChanges: [String] = []
        var submissions = 0
        configure(controller, onChange: { oldChanges.append($0) })
        configure(controller, onChange: { currentChanges.append($0) },
                  onSubmit: { submissions += 1 })
        let field = controller.textField
        field.text = "Renamed home"
        field.sendActions(for: .editingChanged)
        XCTAssertTrue(oldChanges.isEmpty)
        XCTAssertEqual(currentChanges, ["Renamed home"])
        let delegate = try XCTUnwrap(field.delegate)
        _ = delegate.textFieldShouldReturn?(UITextField())
        XCTAssertEqual(submissions, 0, "Only the owned field can submit")
        _ = delegate.textFieldShouldReturn?(field)
        _ = delegate.textFieldShouldReturn?(field)
        XCTAssertEqual(submissions, 2, "A later enabled Return may retry a rejected submission")

        configure(controller, text: "Renamed home", enabled: false,
                  onChange: { currentChanges.append($0) }, onSubmit: { submissions += 1 })
        XCTAssertFalse(field.isEnabled)
        _ = delegate.textFieldShouldReturn?(field)
        field.sendActions(for: .editingChanged)
        XCTAssertEqual(submissions, 2)
        XCTAssertEqual(currentChanges, ["Renamed home"])
        configure(controller, text: "Renamed home", enabled: true,
                  onChange: { currentChanges.append($0) }, onSubmit: { submissions += 1 })
        XCTAssertTrue(field.isEnabled)
        field.text = "Another name"
        field.sendActions(for: .editingChanged)
        _ = delegate.textFieldShouldReturn?(field)
        XCTAssertEqual(currentChanges, ["Renamed home", "Another name"])
        XCTAssertEqual(submissions, 3)
    }

    func testDismantlingPendingFieldPreventsLaterWindowFocusAndCallbacks() async throws {
        try await withWindowHost(UIViewController()) { blocker in
            let field = TrackingTextField()
            let controller = NameEntryTextField.Controller(textField: field)
            var callbacks = 0
            configure(controller, onChange: { _ in callbacks += 1 }, onSubmit: { callbacks += 1 })
            try await withWindowHost(controller, makeKey: false) { host in
                guard await waitUntil({ controller.view.window === host.window }) else {
                    XCTFail("Pending field was not attached to its non-key window")
                    return
                }
                // show() awaited the real presentation completion, so UIKit has
                // delivered appearance before this pending admission is dismantled.
                XCTAssertFalse(host.window.isKeyWindow)
                XCTAssertTrue(blocker.window.isKeyWindow)
                XCTAssertEqual(field.focusRequests, 0)
                controller.dismantle()
                host.window.makeKey()
                NotificationCenter.default.post(name: UIWindow.didBecomeKeyNotification, object: host.window)
                field.text = "After teardown"
                field.sendActions(for: .editingChanged)
                _ = field.delegate?.textFieldShouldReturn?(field)
                XCTAssertEqual(field.focusRequests, 0)
                XCTAssertFalse(field.isFirstResponder)
                XCTAssertEqual(callbacks, 0)
            }
        }
    }

    func testDismantlingActiveFieldReleasesResponderWithoutReacquiringIt() async throws {
        let field = TrackingTextField()
        let controller = NameEntryTextField.Controller(textField: field)
        configure(controller)
        try await withWindowHost(controller) { host in
            guard await waitUntil({ field.isFirstResponder }) else {
                XCTFail("Name field did not acquire focus before teardown")
                controller.dismantle()
                return
            }
            controller.dismantle()
            XCTAssertFalse(field.isFirstResponder)
            configure(controller)
            NotificationCenter.default.post(name: UIWindow.didBecomeKeyNotification, object: host.window)
            XCTAssertFalse(field.isFirstResponder)
            XCTAssertEqual(field.focusRequests, 1)
        }
    }
}
