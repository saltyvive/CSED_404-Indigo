import Foundation

struct GridLiveModel: Codable {
    var version: Int
    var method: String
    var aspect: Double
    var xKnots: [Double]
    var yKnots: [Double]
    var fieldsUT: [[[Double]]]
    var searchSteps: Int
    var residualLimitUT: Double
    var ambiguityDistance: Double
    var ambiguityMarginUT: Double
    var sourceSession: String
    var trainingTrialIDs: [String]
    var excludedRows: [Int]
    var movementIncludedRows: [Int]? = nil
    var inclusionNote: String? = nil
    var scope: String

    var isValid: Bool {
        func validKnots(_ k: [Double]) -> Bool {
            k.count >= 3 && k.first == 0 && k.last == 1 && k.allSatisfy(\.isFinite) &&
            zip(k, k.dropFirst()).allSatisfy { $0 < $1 }
        }
        return version == 1 && method == "bilinear_forward_surface_grid_inverse" && aspect.isFinite && aspect > 0 &&
            validKnots(xKnots) && validKnots(yKnots) && fieldsUT.count == yKnots.count &&
            fieldsUT.allSatisfy { row in row.count == xKnots.count && row.allSatisfy { $0.count == 3 && $0.allSatisfy(\.isFinite) } } &&
            (20...200).contains(searchSteps) && residualLimitUT.isFinite && residualLimitUT > 0 &&
            ambiguityDistance.isFinite && ambiguityDistance > 0 && ambiguityDistance < 1 &&
            ambiguityMarginUT.isFinite && ambiguityMarginUT >= 0
    }

    func field(x: Double, y: Double) -> [Double] {
        let i = (0..<(xKnots.count-1)).first { x <= xKnots[$0+1] } ?? xKnots.count-2
        let j = (0..<(yKnots.count-1)).first { y <= yKnots[$0+1] } ?? yKnots.count-2
        let u = max(0, min(1, (x-xKnots[i])/(xKnots[i+1]-xKnots[i])))
        let v = max(0, min(1, (y-yKnots[j])/(yKnots[j+1]-yKnots[j])))
        return (0..<3).map { k in
            let upper = (1-u)*fieldsUT[j][i][k] + u*fieldsUT[j][i+1][k]
            let lower = (1-u)*fieldsUT[j+1][i][k] + u*fieldsUT[j+1][i+1][k]
            return (1-v)*upper + v*lower
        }
    }
}

struct GridEstimate {
    var point: Point2D
    var residual: Double
    var limit: Double
    var signal: Double
    var accepted: Bool
    var showCandidate: Bool
    var ambiguous: Bool
    var otherLocationResidual: Double
    var reason: String {
        if !showCandidate { return "펜 신호가 약함 · 위치 표시 보류" }
        if ambiguous { return "서로 떨어진 위치의 신호가 비슷함 · 주황색 참고 후보" }
        if !accepted { return "모델과 차이가 큼 · 주황색 참고 후보" }
        return "청록색 추정 위치 · 실제 정확도는 별도 검증이 필요합니다"
    }
}

/// Search the entire surface. No guide path, trial target, previous position,
/// elapsed movement time or assumed pen speed is an input to this estimator.
struct GridProjector {
    private struct Candidate { var point: Point2D; var bx: Double; var by: Double; var bz: Double }
    private var candidates: [Candidate] = []
    let minimumSignalUT: Double
    private let model: GridLiveModel

    init?(model: GridLiveModel) {
        guard model.isValid else { return nil }
        self.model = model
        for j in 0...model.searchSteps {
            for i in 0...model.searchSteps {
                let p = Point2D(x: Double(i)/Double(model.searchSteps), y: Double(j)/Double(model.searchSteps))
                let b = model.field(x: p.x, y: p.y)
                candidates.append(.init(point: p, bx: b[0], by: b[1], bz: b[2]))
            }
        }
        minimumSignalUT = max(3, 0.2*(candidates.map { sqrt($0.bx*$0.bx + $0.by*$0.by + $0.bz*$0.bz) }.min() ?? 0))
    }

    func project(_ b: [Double]) -> GridEstimate? {
        guard b.count == 3, b.allSatisfy(\.isFinite) else { return nil }
        var distances = [Double](); distances.reserveCapacity(candidates.count)
        var best = 0, bestSquared = Double.infinity
        for (i, c) in candidates.enumerated() {
            let dx = c.bx-b[0], dy = c.by-b[1], dz = c.bz-b[2]
            let squared = dx*dx + dy*dy + dz*dz
            distances.append(squared)
            if squared < bestSquared { best = i; bestSquared = squared }
        }
        let p = candidates[best].point, residual = sqrt(bestSquared)
        var otherSquared = Double.infinity
        for (i, c) in candidates.enumerated() where hypot(c.point.x-p.x, c.point.y-p.y) >= model.ambiguityDistance {
            otherSquared = min(otherSquared, distances[i])
        }
        let other = sqrt(otherSquared), signal = sqrt(b.reduce(0) { $0+$1*$1 })
        let ambiguous = other <= residual+model.ambiguityMarginUT
        return GridEstimate(point: p, residual: residual, limit: model.residualLimitUT, signal: signal,
                            accepted: signal >= minimumSignalUT && residual <= model.residualLimitUT && !ambiguous,
                            showCandidate: signal >= minimumSignalUT, ambiguous: ambiguous, otherLocationResidual: other)
    }
}

/// Instructions only. A known line does not supply a timestamped position.
enum GridGuide: String, CaseIterable, Identifiable, Codable {
    case free, row1, row2, row3, row4, row5, col1, col2, col3, col4, col5, diagonalDown, diagonalUp
    case denseRow1, denseRow2, denseRow3, denseRow4, denseRow5, denseRow6, denseRow7, denseRow8, denseRow9
    case denseCol1, denseCol2, denseCol3, denseCol4, denseCol5, denseCol6, denseCol7, denseCol8, denseCol9
    var id: String { rawValue }
    var row: Int? { rawValue.hasPrefix("row") || rawValue.hasPrefix("denseRow") ? Int(rawValue.suffix(1)) : nil }
    var column: Int? { rawValue.hasPrefix("col") || rawValue.hasPrefix("denseCol") ? Int(rawValue.suffix(1)) : nil }
    static func options(gridSize: Int) -> [GridGuide] {
        allCases.filter { $0 == .free || $0 == .diagonalDown || $0 == .diagonalUp ||
            (gridSize == 9 ? $0.rawValue.hasPrefix("dense") : !$0.rawValue.hasPrefix("dense")) }
    }
    var title: String {
        if let row { return "가로 \(row)행 · 좌우 왕복" }
        if let column { return "세로 \(column)열 · 위아래 왕복" }
        switch self {
        case .diagonalDown: return "대각선 ↘ · 왼쪽 위 ↔ 오른쪽 아래"
        case .diagonalUp: return "대각선 ↙ · 오른쪽 위 ↔ 왼쪽 아래"
        default: return "자유 이동 · 안내선 없음"
        }
    }
    var endpoints: [Point2D] {
        let divisor = rawValue.hasPrefix("dense") ? 8.0 : 4.0
        if let row { let y = Double(row-1)/divisor; return [.init(x: 0,y: y), .init(x: 1,y: y)] }
        if let column { let x = Double(column-1)/divisor; return [.init(x: x,y: 0), .init(x: x,y: 1)] }
        switch self {
        case .diagonalDown: return [.init(x: 0,y: 0), .init(x: 1,y: 1)]
        case .diagonalUp: return [.init(x: 1,y: 0), .init(x: 0,y: 1)]
        default: return []
        }
    }
}
