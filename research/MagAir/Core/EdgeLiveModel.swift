import Foundation

struct EdgeLiveModel: Codable {
    var version: Int
    var method: String
    var aspect: Double
    var curves: [EdgeFieldCurve]
    var scope: String

    var isValid: Bool {
        version == 1 && aspect.isFinite && aspect > 0 && !curves.isEmpty &&
        Set(curves.map(\.edge)).count == curves.count && curves.allSatisfy(\.isValid)
    }
}

struct EdgeFieldCurve: Codable {
    var edge: StudyEdge
    var knots: [Double]
    var fieldsUT: [[Double]]
    var slopesUT: [[Double]]
    var residualLimitUT: Double
    var sourceSession: String
    var trainingTrialIDs: [String]

    var isValid: Bool {
        knots.count >= 2 && knots.first == 0 && knots.last == 1 && knots.allSatisfy(\.isFinite) &&
        zip(knots, knots.dropFirst()).allSatisfy { $0 < $1 } &&
        fieldsUT.count == knots.count && slopesUT.count == knots.count &&
        (fieldsUT + slopesUT).allSatisfy { $0.count == 3 && $0.allSatisfy(\.isFinite) } &&
        residualLimitUT.isFinite && residualLimitUT > 0
    }

    /// Same piecewise Hermite interpolation as scripts/build_edge_model.py.
    func field(at s: Double) -> [Double] {
        let i = min(knots.count - 2, max(0, (knots.indices.dropFirst().first { s <= knots[$0] } ?? (knots.count - 1)) - 1))
        let h = knots[i+1] - knots[i]
        let t = max(0, min(1, (s - knots[i])/h))
        let t2 = t*t, t3 = t*t*t
        let h00 = 2*t3 - 3*t2 + 1
        let h10 = (t3 - 2*t2 + t)*h
        let h01 = -2*t3 + 3*t2
        let h11 = (t3 - t2)*h
        return (0..<3).map { axis in
            let left = h00*fieldsUT[i][axis] + h10*slopesUT[i][axis]
            let right = h01*fieldsUT[i+1][axis] + h11*slopesUT[i+1][axis]
            return left + right
        }
    }
}

struct EdgeEstimate {
    var edge: StudyEdge
    var parameter: Double
    var residual: Double
    var limit: Double
    var signal: Double
    var accepted: Bool
    var showCandidate: Bool
    var ambiguous: Bool
    var otherEdge: StudyEdge?
    var otherEdgeResidual: Double?
    var point: Point2D { edge.point(parameter) }
    var reason: String {
        if !showCandidate { return "펜 신호가 약함 · 위치 표시 보류" }
        if ambiguous { return "여러 위치의 신호가 비슷함 · 참고 후보만 표시" }
        if !accepted { return "모델과 차이가 큼 · 주황색은 참고 후보" }
        return "학습한 신호 범위 안 · 실제 위치 정확도는 검증 중"
    }
}

/// Precompute the 401 candidates per edge. The measured field selects the edge;
/// neither a collection target nor elapsed sweep time enters the prediction.
struct EdgeProjector {
    private struct Candidate {
        var edge: StudyEdge
        var s: Double
        var field: [Double]
        var limit: Double
    }
    private var candidates: [Candidate] = []
    let minimumSignalUT: Double

    init?(model: EdgeLiveModel) {
        guard model.isValid else { return nil }
        for curve in model.curves {
            for i in 0...400 {
                let s = Double(i)/400
                candidates.append(Candidate(edge: curve.edge, s: s, field: curve.field(at: s), limit: curve.residualLimitUT))
            }
        }
        minimumSignalUT = max(3, 0.2 * (candidates.map { sqrt($0.field.reduce(0) { $0 + $1*$1 }) }.min() ?? 0))
    }

    func project(_ field: [Double]) -> EdgeEstimate? {
        guard field.count == 3, field.allSatisfy(\.isFinite) else { return nil }
        let distances = candidates.map { c in sqrt(zip(c.field, field).reduce(0) { $0 + pow($1.0 - $1.1, 2) }) }
        guard let index = distances.indices.min(by: { distances[$0] < distances[$1] }) else { return nil }
        let best = candidates[index], distance = distances[index]
        let point = best.edge.point(best.s)
        // A competing location at least 20% of a side away with virtually the
        // same residual should not be shown as a single trustworthy position.
        let ambiguous = candidates.indices.contains { i in
            let other = candidates[i].edge.point(candidates[i].s)
            return hypot(other.x - point.x, other.y - point.y) >= 0.2 && distances[i] <= distance + 0.75
        }
        let signal = sqrt(field.reduce(0) { $0 + $1*$1 })
        let otherIndex = candidates.indices.filter { candidates[$0].edge != best.edge }
            .min { distances[$0] < distances[$1] }
        return EdgeEstimate(edge: best.edge, parameter: best.s, residual: distance, limit: best.limit, signal: signal,
                            accepted: signal >= minimumSignalUT && distance <= best.limit && !ambiguous,
                            showCandidate: signal >= minimumSignalUT, ambiguous: ambiguous,
                            otherEdge: otherIndex.map { candidates[$0].edge },
                            otherEdgeResidual: otherIndex.map { distances[$0] })
    }
}
