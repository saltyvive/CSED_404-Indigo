import Foundation

@main
struct LiveModelTests {
    static func main() throws {
        let mode = LiveMode(id: "surface", title: "test", anchors: [[10,10,0],[40,10,0],[40,30,0],[10,30,0]],
                            residualLimitUT: 2, minimumSignalUT: 3, trainingTrialIDs: [])
        let p = mode.project(mode.field(x: 0.365, y: 0.785))!
        precondition(p.accepted && abs(p.point.x - 0.365) < 0.006 && abs(p.point.y - 0.785) < 0.006)
        precondition(!mode.project([0,0,0])!.accepted)
        precondition(!mode.project([20,20,100])!.accepted)
        precondition(!mode.project(mode.field(x: 1.16, y: 0.5))!.accepted)
        precondition(mode.project([Double.nan,0,0]) == nil)
        precondition(mode.project([0]) == nil)
        var invalid = mode
        invalid.anchors = [[1,2,3]]
        precondition(!invalid.isValid && invalid.project([1,2,3]) == nil)
        precondition(medianValue([5,1,3,2]) == 2.5)
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let model = try JSONDecoder().decode(LiveModel.self, from: data)
        precondition(model.isValid && Set(model.modes.map(\.id)) == ["surface", "air"])
        for m in model.modes {
            for (i, xy) in [(0, Point2D(x: 0,y: 0)), (1, Point2D(x: 1,y: 0)), (2, Point2D(x: 1,y: 1)), (3, Point2D(x: 0,y: 1))] {
                let result = m.project(m.anchors[i])!
                precondition(result.accepted && result.residual < 0.000001)
                precondition(abs(result.point.x-xy.x) < 0.001 && abs(result.point.y-xy.y) < 0.001)
            }
        }
        print("Live model tests passed: interpolation, rejection, invalid inputs, bundled real model")
    }
}
