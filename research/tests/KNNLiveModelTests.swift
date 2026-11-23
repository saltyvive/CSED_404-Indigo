import Foundation

struct KNNReplayFrame: Decodable {
    var filteredDeltaUT: [Double]
    var xy: [Double]
    var residualUT: Double
    var otherLocationResidualUT: Double
    var shown: Bool
    var ambiguous: Bool
    var accepted: Bool
}

@main
struct KNNLiveModelTests {
    static func main() throws {
        let model = try JSONDecoder().decode(KNNLiveModel.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        let projector = KNNProjector(model: model)!
        let cases = try JSONDecoder().decode([KNNReplayFrame].self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2])))
        let start = Date()
        for c in cases {
            let actual = projector.project(c.filteredDeltaUT)!
            precondition(abs(actual.point.x-c.xy[0]) < 1e-8 && abs(actual.point.y-c.xy[1]) < 1e-8)
            precondition(abs(actual.residual-c.residualUT) < 1e-8 && abs(actual.otherLocationResidual-c.otherLocationResidualUT) < 1e-8)
            precondition(actual.accepted == c.accepted && actual.showCandidate == c.shown && actual.ambiguous == c.ambiguous)
        }
        precondition(projector.project([.nan,0,0]) == nil)
        precondition(projector.project([1,2]) == nil)
        var bad = model; bad.locations.removeLast(); precondition(KNNProjector(model: bad) == nil)
        bad = model; bad.locations[0].fieldsUT[0] = [.infinity,0,0]; precondition(KNNProjector(model: bad) == nil)
        bad = model; bad.k = 0; precondition(KNNProjector(model: bad) == nil)
        bad = model; bad.locations[0].placementIDs = ["wrong"]; precondition(KNNProjector(model: bad) == nil)
        var conflict = model
        conflict.locations[272].fieldsUT = conflict.locations[0].fieldsUT
        let result = KNNProjector(model: conflict)!.project(conflict.locations[0].fieldsUT[0])!
        precondition(result.ambiguous && !result.accepted)
        precondition(hypot(result.point.x,result.point.y) < 0.2) // Never average the distant corner into the middle.
        print("KNN Swift/Python parity: \(cases.count) frames, validation/ambiguity passed; \(Date().timeIntervalSince(start)) seconds")
    }
}
