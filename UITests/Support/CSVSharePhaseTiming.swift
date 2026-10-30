// Pure timing policy shared by the UI flow and its scalar regression tests.
struct CSVSharePhaseTiming {
    let start: Double
    var deadline: Double { start + 15 }

    func remaining(at now: Double) -> Double { deadline - now }

    func permitsAction(at now: Double) -> Bool {
        now >= start && now < deadline
    }

    func acceptsReturn(waitStartedAt: Double, waiterCompleted: Bool, finishedAt: Double) -> Bool {
        waiterCompleted && permitsAction(at: waitStartedAt)
            && finishedAt >= waitStartedAt && finishedAt <= deadline
    }
}
