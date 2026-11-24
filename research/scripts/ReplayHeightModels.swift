import Foundation
import CryptoKit

struct HeightQuery: Decodable {
    var truth: String
    var passID: Int
    var row: Int
    var column: Int
    var session: String
    var trial: String
    var xy: [Double]
    var field: [Double]
    var mode: String
}

/// Replays actual app estimators; target/height/mode are evaluator-only fields.
@main struct ReplayHeightModels {
    static func main() throws {
        let args = CommandLine.arguments
        precondition(args.count == 6, "resources airCombination C-resource queries output")
        let root = URL(fileURLWithPath: args[1]), airID = args[2]
        func read(_ name: String) throws -> Data { try Data(contentsOf: root.appendingPathComponent(name + ".json")) }
        func hash(_ d: Data) -> String { SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined() }
        let ca = try read("model_A_13"), cb = try read("model_B_13")
        let aa = try read("model_A_"+airID), ab = try read("model_B_"+airID), cn = try read(args[3])
        let decoder = JSONDecoder()
        let contactA = GridProjector(model: try decoder.decode(GridLiveModel.self, from: ca))!
        let contactB = KNNProjector(model: try decoder.decode(KNNLiveModel.self, from: cb))!
        let airA = GridProjector(model: try decoder.decode(GridLiveModel.self, from: aa))!
        let airB = KNNProjector(model: try decoder.decode(KNNLiveModel.self, from: ab))!
        let neural = JointNeuralProjector(model: try decoder.decode(JointNeuralModel.self, from: cn))!
        let queryData = try Data(contentsOf: URL(fileURLWithPath: args[4]))
        let queries = try decoder.decode([HeightQuery].self, from: queryData)
        var rows = [[String: Any]]()
        for q in queries {
            precondition(q.field.count == 3 && q.xy.count == 2 && ["contact","air"].contains(q.truth))
            let a = JointHeightEstimate(contact: contactA.project(q.field)!, air: airA.project(q.field)!)
            let b = JointHeightEstimate(contact: contactB.project(q.field)!, air: airB.project(q.field)!)
            let c = neural.project(q.field)!
            func position(_ e: GridEstimate) -> [String: Any] {
                ["xy": [e.point.x,e.point.y], "residualUT": e.residual, "otherLocationResidualUT": e.otherLocationResidual,
                 "signalUT": e.signal, "shown": e.showCandidate, "accepted": e.accepted, "ambiguous": e.ambiguous,
                 "errorMM": hypot(50*(e.point.x-q.xy[0]),30*(e.point.y-q.xy[1]))]
            }
            func joint(_ p: JointHeightEstimate) -> [String: Any] {
                var r = position(p.estimate)
                r["predicted"] = p.state.rawValue; r["closestState"] = p.closestState.rawValue
                r["heightAmbiguous"] = p.heightAmbiguous; r["gapUT"] = p.gapUT
                r["contactResidualUT"] = p.contact.residual; r["airResidualUT"] = p.air.residual
                r["spatialAmbiguous"] = (p.closestState == .contact ? p.contact : p.air).ambiguous
                r["residualRejected"] = p.estimate.residual > p.estimate.limit
                return r
            }
            var cr = position(c.gridEstimate)
            cr["predicted"] = c.state.rawValue; cr["closestState"] = c.closestState.rawValue
            cr["contactScore"] = c.contactScore; cr["inSupport"] = c.inSupport; cr["inBounds"] = c.inBounds
            rows.append(["truth":q.truth,"passID":q.passID,"row":q.row,"column":q.column,"session":q.session,
                "trial":q.trial,"targetXY":q.xy,"field":q.field,"mode":q.mode,
                "A":joint(a),"B":joint(b),"C":cr,"singleA":position(a.air),"singleB":position(b.air)])
        }
        let output: [String: Any] = ["queriesSHA256":hash(queryData),"models":
            ["A_contact13":hash(ca),"B_contact13":hash(cb),"A_air":hash(aa),"B_air":hash(ab),"C":hash(cn)],
            "predictions":rows]
        let target = URL(fileURLWithPath: args[5])
        precondition(!FileManager.default.fileExists(atPath: target.path), "Use a fresh output file")
        try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys,.prettyPrinted]).write(to: target)
        print("Replayed \(queries.count) inputs using actual Swift single-height A/B and joint A/B/C.")
    }
}
