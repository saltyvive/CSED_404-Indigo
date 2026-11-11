import Foundation

struct GridReplayFrame: Decodable {
    var filteredDeltaUT: [Double]
    var xy: [Double]
    var residualUT: Double
    var otherLocationResidualUT: Double
    var shown: Bool
    var ambiguous: Bool
    var accepted: Bool
}

@main
struct GridLiveModelTests {
    static func main() throws {
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        var model = try JSONDecoder().decode(GridLiveModel.self, from: data)
        let projector = GridProjector(model: model)!
        precondition(projector.project([Double.nan,0,0]) == nil)
        precondition(projector.project([1,2]) == nil)
        precondition(!projector.project([0,0,0])!.showCandidate)
        precondition(!projector.project([1000,1000,1000])!.accepted)
        let replay = try JSONDecoder().decode([GridReplayFrame].self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2])))
        let start = Date()
        for f in replay {
            let result = projector.project(f.filteredDeltaUT)!
            precondition(abs(result.point.x-f.xy[0]) < 1e-9 && abs(result.point.y-f.xy[1]) < 1e-9)
            precondition(abs(result.residual-f.residualUT) < 1e-8)
            precondition(abs(result.otherLocationResidual-f.otherLocationResidualUT) < 1e-8)
            precondition(result.showCandidate == f.shown && result.ambiguous == f.ambiguous && result.accepted == f.accepted)
        }
        print("Grid Swift/Python parity: \(replay.count) replay frames; \(Date().timeIntervalSince(start)) seconds")
        model.fieldsUT = model.yKnots.map { _ in model.xKnots.map { x in [30*x,0,10] } }
        let ambiguous = GridProjector(model: model)!.project([15,0,10])!
        precondition(ambiguous.ambiguous && !ambiguous.accepted)
        model.searchSteps = 0
        precondition(GridProjector(model: model) == nil)
        model.searchSteps = 100; model.fieldsUT[0][0] = [1,2]
        precondition(GridProjector(model: model) == nil)
        print("Grid model validation and ambiguity tests passed")
    }
}
