import Foundation
import CryptoKit

struct NeuralParityCase: Decodable {
    var field: [Double]
    var xy: [Double]
    var contactScore: Double
    var supportDistanceUT: Double
    var signalUT: Double
    var shown: Bool
    var inSupport: Bool
    var inBounds: Bool
    var ambiguous: Bool
    var accepted: Bool
    var closestState: JointTipState
    var predicted: JointTipState
}

@main
struct JointNeuralModelTests {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        func read(_ name: String) throws -> Data { try Data(contentsOf: root.appendingPathComponent(name + ".json")) }
        let library = try GridModelLibrary.load(read: read)
        let air = CommandLine.arguments.count > 3 ? CommandLine.arguments[3] : "hover3_1"
        let combination = air.replacingOccurrences(of: "hover3_", with: "")
        let catalogName = combination == "1" ? "joint_mlp_catalog" : "joint_mlp_air\(combination)_catalog"
        let resourceName = "joint_mlp_contact13_air\(combination)"
        let bundle = try JointNeuralBundle.load(library: library, airCombination: air, read: read)
        let cases = try JSONDecoder().decode([NeuralParityCase].self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2])))
        precondition(cases.count == (air == "hover3_12" ? 4370 : 3278))
        for c in cases {
            let p = bundle.projector.project(c.field)!
            precondition(abs(p.point.x-c.xy[0]) < 1e-8 && abs(p.point.y-c.xy[1]) < 1e-8)
            precondition(abs(p.contactScore-c.contactScore) < 1e-8)
            precondition(abs(p.supportDistanceUT-c.supportDistanceUT) < 1e-8 && abs(p.signal-c.signalUT) < 1e-8)
            precondition(p.showCandidate == c.shown && p.accepted == c.accepted && p.ambiguous == c.ambiguous)
            precondition(p.inSupport == c.inSupport && p.inBounds == c.inBounds)
            precondition(p.state == c.predicted && p.closestState == c.closestState)
        }
        precondition(bundle.projector.project([1,2]) == nil && bundle.projector.project([.nan,1,2]) == nil)
        precondition(!bundle.projector.project([0,0,0])!.showCandidate)
        precondition(!bundle.projector.project([1000,-1000,1000])!.accepted)
        do {
            _ = try JointNeuralBundle.load(library: library, airCombination: air) { name in
                var data = try read(name); if name == resourceName { data.append(32) }; return data
            }
            preconditionFailure("Corrupt weights hash accepted")
        } catch { }
        // Even a rehashed model must not silently include a different pass or invalid shape.
        let original = try JSONSerialization.jsonObject(with: bundle.data) as! [String: Any]
        for mutation in ["pass", "shape", "source"] {
            var model = original
            if mutation == "pass" {
                var conditions = model["conditions"] as! [[String: Any]]
                conditions[0]["passes"] = [1,2]; model["conditions"] = conditions
            } else if mutation == "shape" {
                var layers = model["layers"] as! [[String: Any]]
                layers[0]["weights"] = [[0,0,0]]; model["layers"] = layers
            } else {
                var ids = model["trainingTrialIDs"] as! [String]
                ids[0] = "unrelated-pass2-trial"; model["trainingTrialIDs"] = ids
            }
            let raw = try JSONSerialization.data(withJSONObject: model)
            var catalog = try JSONSerialization.jsonObject(with: read(catalogName)) as! [String: Any]
            catalog["sha256"] = SHA256.hash(data: raw).map { String(format: "%02x",$0) }.joined()
            let catalogData = try JSONSerialization.data(withJSONObject: catalog)
            do {
                _ = try JointNeuralBundle.load(library: library, airCombination: air) { name in
                    if name == catalogName { return catalogData }
                    return name == resourceName ? raw : try read(name)
                }
                preconditionFailure("Invalid \(mutation) accepted")
            } catch { }
        }
        print("C shared MLP \(air): \(cases.count) Python/Swift predictions matched (XY, score, gates, state); corrupt weights, wrong contact passes, source mismatch and malformed layers rejected.")
    }
}
