import Foundation

struct JointReplayInput: Decodable {
    var truth: JointTipState
    var pass: Int
    var row: Int
    var column: Int
    var field: [Double]
    var xy: [Double]
    var session: String
    var trial: String
}

@main
struct JointHeightTests {
    static func main() throws {
        func candidate(_ residual: Double, x: Double = 0.1, accepted: Bool = true, shown: Bool = true, ambiguous: Bool = false) -> GridEstimate {
            .init(point: .init(x: x, y: 0.5), residual: residual, limit: 3, signal: 20,
                  accepted: accepted, showCandidate: shown, ambiguous: ambiguous, otherLocationResidual: 5)
        }
        let contact = JointHeightEstimate(contact: candidate(0.2), air: candidate(2, x: 0.9))
        precondition(contact.state == .contact && contact.estimate.point.x == 0.1)
        let air = JointHeightEstimate(contact: candidate(2), air: candidate(0.2, x: 0.9))
        precondition(air.state == .air && air.estimate.point.x == 0.9)
        for gap in [0, 0.1, JointHeightEstimate.marginUT] {
            let tied = JointHeightEstimate(contact: candidate(0), air: candidate(gap))
            precondition(tied.state == .uncertain && !tied.estimate.accepted && tied.heightAmbiguous)
            let reversed = JointHeightEstimate(contact: candidate(gap), air: candidate(0))
            precondition(reversed.state == .uncertain && !reversed.estimate.accepted)
        }
        for rejected in [candidate(0.1, accepted: false, shown: false), candidate(0.1, accepted: false, ambiguous: true), candidate(4, accepted: false)] {
            let j = JointHeightEstimate(contact: rejected, air: candidate(8, accepted: false))
            precondition(j.state == .uncertain && !j.estimate.accepted)
        }
        let resources = URL(fileURLWithPath: CommandLine.arguments[1])
        let library = try GridModelLibrary.load { name in try Data(contentsOf: resources.appendingPathComponent(name + ".json")) }
        let projector = JointHeightProjector(library: library)!
        precondition(projector.contactPair.entry.id == "13" && projector.contactPair.entry.passes == [1, 3])
        precondition(projector.airPair.entry.id == "hover3_1" && projector.airPair.entry.passes == [1])
        precondition(projector.project([1, 2]) == nil && projector.project([1, .nan, 3]) == nil)
        let absent = projector.project([0, 0, 0])!
        precondition(!absent.a.estimate.showCandidate && !absent.b.estimate.showCandidate)
        let inputs = try JSONDecoder().decode([JointReplayInput].self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2])))
        precondition(inputs.count == 819)
        precondition(inputs.filter { $0.truth == .contact }.count == 546 && inputs.filter { $0.truth == .air }.count == 273)
        precondition(inputs.allSatisfy { $0.truth == .contact ? [1, 3].contains($0.pass) : $0.pass == 1 })
        var predictions = [[String: Any]]()
        for input in inputs {
            let pair = projector.project(input.field)!
            for (family, prediction) in [("A", pair.a), ("B", pair.b)] {
                let e = prediction.estimate
                predictions.append(["family": family, "truth": input.truth.rawValue, "pass": input.pass,
                    "row": input.row, "column": input.column, "session": input.session, "trial": input.trial,
                    "predicted": prediction.state.rawValue, "closestState": prediction.closestState.rawValue,
                    "contactResidualUT": prediction.contact.residual, "airResidualUT": prediction.air.residual,
                    "gapUT": prediction.gapUT, "heightAmbiguous": prediction.heightAmbiguous,
                    "xy": [e.point.x, e.point.y], "targetXY": input.xy, "accepted": e.accepted,
                    "shown": e.showCandidate,
                    "positionErrorMM": hypot(50*(e.point.x-input.xy[0]), 30*(e.point.y-input.xy[1]))])
            }
        }
        var summary = [String: Any]()
        for family in ["A", "B"] {
            let selected = predictions.filter { $0["family"] as? String == family }
            var classes = [String: Any]()
            for label in ["contact", "air"] {
                let samples = selected.filter { $0["truth"] as? String == label }
                let correct = samples.filter { $0["predicted"] as? String == label }.count
                let accepted = samples.filter { $0["accepted"] as? Bool == true }.count
                let success = samples.filter { $0["predicted"] as? String == label && ($0["positionErrorMM"] as! Double) <= 2.5 }.count
                classes[label] = ["count": samples.count, "accepted": accepted, "correct": correct,
                    "wrong": accepted-correct, "uncertain": samples.count-accepted,
                    "correctFractionAll": Double(correct)/Double(samples.count),
                    "correctAmongAccepted": accepted == 0 ? NSNull() : Double(correct)/Double(accepted) as Any,
                    "correctHeightAndXYWithin2p5MM": success]
            }
            summary[family] = classes
        }
        let report: [String: Any] = ["role": "training_replay_not_independent_validation", "heightMarginUT": JointHeightEstimate.marginUT,
            "inputMode": "trimmed stationary hold median minus preceding row baseline; no future baseline at query",
            "models": [projector.contactPair, projector.airPair].map { ["id": $0.entry.id, "sha256A": $0.entry.sha256A, "sha256B": $0.entry.sha256B] },
            "summary": summary, "predictions": predictions]
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            .write(to: URL(fileURLWithPath: CommandLine.arguments[3]), options: .atomic)
        print("Joint height: margins/ties/rejections/invalid input checked; 0mm passes 1+3 and 3mm pass 1 only; \(predictions.count) Swift replay predictions saved.")
        print(String(data: try JSONSerialization.data(withJSONObject: summary, options: [.sortedKeys]), encoding: .utf8)!)
    }
}
