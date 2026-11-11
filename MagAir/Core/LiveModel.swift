import Foundation

struct LiveModel: Codable {
    var version: Int
    var sourceSession: String
    var aspect: Double
    var method: String
    var baselineReferenceUT: [Double]
    var modes: [LiveMode]
    var limitation: String

    var isValid: Bool {
        version == 1 && aspect.isFinite && aspect > 0 && baselineReferenceUT.count == 3 &&
        baselineReferenceUT.allSatisfy(\.isFinite) && !modes.isEmpty && modes.allSatisfy(\.isValid)
    }
}

struct LiveProjection {
    var point: Point2D
    var residual: Double
    var accepted: Bool
    var reason: String
}

struct LiveMode: Codable {
    var id: String
    var title: String
    var anchors: [[Double]] // top-left, top-right, bottom-right, bottom-left
    var residualLimitUT: Double
    var minimumSignalUT: Double
    var trainingTrialIDs: [String]

    var isValid: Bool {
        anchors.count == 4 && anchors.allSatisfy { $0.count == 3 && $0.allSatisfy(\.isFinite) } &&
        residualLimitUT.isFinite && residualLimitUT > 0 && minimumSignalUT.isFinite && minimumSignalUT >= 0
    }

    func field(x: Double, y: Double) -> [Double] {
        let weights = [(1-x)*(1-y), x*(1-y), x*y, (1-x)*y]
        return (0..<3).map { axis in (0..<4).reduce(0.0) { $0 + weights[$1]*anchors[$1][axis] } }
    }

    func project(_ field: [Double]) -> LiveProjection? {
        guard isValid, field.count == 3, field.allSatisfy(\.isFinite) else { return nil }
        var bx = 0.0, by = 0.0, best = Double.infinity
        func consider(_ x: Double, _ y: Double) {
            let prediction = self.field(x: x, y: y)
            let d = zip(prediction, field).reduce(0.0) { $0 + pow($1.0 - $1.1, 2) }
            if d < best { best = d; bx = x; by = y }
        }
        // Search beyond the rectangle so an out-of-range field does not just stick to its edge.
        for iy in 0..<27 { for ix in 0..<27 { consider(-0.15 + Double(ix)*0.05, -0.15 + Double(iy)*0.05) } }
        let cx = bx, cy = by
        for iy in -5...5 { for ix in -5...5 { consider(cx + Double(ix)*0.005, cy + Double(iy)*0.005) } }
        let residual = sqrt(best)
        let strength = sqrt(field.reduce(0) { $0 + $1*$1 })
        let reason: String
        if strength < minimumSignalUT { reason = "신호가 약함 · 위치 표시 보류" }
        else if residual > residualLimitUT { reason = "학습한 신호와 차이가 큼 · 위치 표시 보류" }
        else if bx < -0.10 || bx > 1.10 || by < -0.10 || by > 1.10 { reason = "영역 밖 추정 · 위치 표시 보류" }
        else { reason = "네 모서리 사이 보간 · 내부 위치 미검증" }
        return LiveProjection(point: Point2D(x: bx, y: by), residual: residual,
                              accepted: strength >= minimumSignalUT && residual <= residualLimitUT &&
                                bx >= -0.10 && bx <= 1.10 && by >= -0.10 && by <= 1.10,
                              reason: reason)
    }
}

func medianValue(_ values: [Double]) -> Double {
    let sorted = values.sorted()
    guard !sorted.isEmpty else { return .nan }
    let i = sorted.count / 2
    return sorted.count % 2 == 0 ? (sorted[i-1] + sorted[i])/2 : sorted[i]
}
