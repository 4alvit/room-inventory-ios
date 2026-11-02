import Foundation

/// One post-activation observation allowance, including snapshot traversal.
struct RecoveryOCRSelectionWindow {
    enum Failure: Error, Equatable, CustomStringConvertible {
        case expired
        case nodeLimit
        case duplicateSwitch

        var description: String {
            switch self {
            case .expired: "OCR selection deadline expired"
            case .nodeLimit: "OCR selection snapshot exceeded 10000 nodes"
            case .duplicateSwitch: "OCR selection snapshot has duplicate target switches"
            }
        }
    }

    struct Observation {
        let matches: Int
        let value: String?

        var selected: Bool { matches == 1 && value == "1" }
    }

    private let clock: () -> TimeInterval
    private let end: TimeInterval

    init(clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.clock = clock
        end = clock() + 10
    }

    func remaining() throws -> TimeInterval {
        let value = end - clock()
        guard value > 0 else { throw Failure.expired }
        return value
    }

    /// The supplied accessors read only the immutable snapshot, never live UI.
    func observe<Node>(identifier: String, snapshot: () throws -> Node,
                       children: (Node) -> [Node], isSwitch: (Node) -> Bool,
                       identifierOf: (Node) -> String, value: (Node) -> String?) throws -> Observation {
        _ = try remaining()
        let root = try snapshot()
        _ = try remaining()
        var pending = [root]
        var visited = 0
        var matches = 0
        var selectedValue: String?
        while let node = pending.popLast() {
            _ = try remaining()
            visited += 1
            guard visited <= 10_000 else { throw Failure.nodeLimit }
            if isSwitch(node) && identifierOf(node) == identifier {
                matches += 1
                guard matches == 1 else { throw Failure.duplicateSwitch }
                selectedValue = value(node)
            }
            let descendants = children(node)
            guard descendants.count <= 10_000 - visited - pending.count else { throw Failure.nodeLimit }
            pending.append(contentsOf: descendants.reversed())
            _ = try remaining()
        }
        _ = try remaining()
        return Observation(matches: matches, value: selectedValue)
    }
}
