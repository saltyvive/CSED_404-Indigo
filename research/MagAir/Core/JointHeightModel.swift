import Foundation

enum JointTipState: String, Codable {
    case contact, air, uncertain
    var title: String {
        switch self {
        case .contact: return "접촉 추정 · 0 mm"
        case .air: return "공중 추정 · 3 mm"
        case .uncertain: return "접촉·공중 판정 보류"
        }
    }
}

/// Two discrete magnetic hypotheses, not a contact sensor or continuous height regression.
struct JointHeightEstimate {
    static let marginUT = 0.75 // Fixed before replay; heuristic, not a calibrated probability.
    let contact: GridEstimate
    let air: GridEstimate
    var closestState: JointTipState { contact.residual <= air.residual ? .contact : .air }
    var gapUT: Double { abs(contact.residual - air.residual) }
    var heightAmbiguous: Bool { gapUT <= Self.marginUT }
    var estimate: GridEstimate {
        var best = closestState == .contact ? contact : air
        best.accepted = best.accepted && !heightAmbiguous
        // Preserve within-height ambiguity separately in contact/air for the audit log.
        best.ambiguous = best.ambiguous || heightAmbiguous
        return best
    }
    var state: JointTipState { estimate.accepted ? closestState : .uncertain }
    var reason: String {
        if !estimate.showCandidate { return "펜 신호가 약함 · 위치·접촉 표시 보류" }
        if heightAmbiguous { return "두 높이의 신호가 비슷함 · 주황색 후보, 접촉·공중 판정 보류" }
        if !estimate.accepted { return "위치가 불확실함 · 주황색 후보, 접촉·공중 판정 보류" }
        return state.title + (state == .contact ? " · 청록색" : " · 보라색")
    }
}

struct JointHeightProjector {
    static let id = "joint_contact13_air1"
    let contactPair: GridModelPair
    let airPair: GridModelPair
    private let contactA: GridProjector
    private let contactB: KNNProjector
    private let airA: GridProjector
    private let airB: KNNProjector

    init?(library: GridModelLibrary) {
        guard let c = library.pair("13"), let a = library.pair("hover3_1"),
              let cc = c.modelA.printedGridContext, let ac = a.modelA.printedGridContext,
              cc.passes == [1, 3], ac.passes == [1],
              cc.pose.tipHeightMM == 0, cc.pose.tipContact,
              ac.pose.tipHeightMM == 3, !ac.pose.tipContact,
              cc.pose.phiDegrees == ac.pose.phiDegrees, cc.pose.thetaDegrees == ac.pose.thetaDegrees,
              cc.pose.alphaDegrees == ac.pose.alphaDegrees,
              cc.widthMM == ac.widthMM, cc.heightMM == ac.heightMM,
              let ca = GridProjector(model: c.modelA), let cb = KNNProjector(model: c.modelB),
              let aa = GridProjector(model: a.modelA), let ab = KNNProjector(model: a.modelB) else { return nil }
        contactPair = c; airPair = a
        contactA = ca; contactB = cb; airA = aa; airB = ab
    }

    /// Both heights search all XY independently. Only the same 3-axis magnetic input is used.
    func project(_ field: [Double]) -> (a: JointHeightEstimate, b: JointHeightEstimate)? {
        guard let ca = contactA.project(field), let aa = airA.project(field),
              let cb = contactB.project(field), let ab = airB.project(field) else { return nil }
        return (.init(contact: ca, air: aa), .init(contact: cb, air: ab))
    }
}
