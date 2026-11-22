import Foundation

struct Point2D: Codable, Equatable {
    var x: Double
    var y: Double
}

struct Setup: Codable {
    var pencil = "Apple Pencil 2세대 · A2051"
    var plane = "책상 평면 · 펜 끝 접촉"
    var aspect = 1.5 // width / height; user confirmed the horizontal side is longer
    var widthMM = ""
    var heightMM = ""
    var heightNote = "펜 끝을 같은 평면에 유지"
    var standAngle = "약 60–80°"
    var environment = "스탠드 고정 · iPad 아래쪽 책상과 같은 평면 · 충전/케이스 상태 추가 기록"
    var requestedHz = 50.0
    var confirmed = false
}

enum ProtocolKind: String, Codable, CaseIterable, Identifiable {
    case baselineBefore, corners, gridTrain, gridTest, clockwise, counterclockwise
    case diagonalDown, diagonalUp, horizontal, vertical, lift, roll, free, baselineAfter
    case cornersHeight, clockwiseAir, counterclockwiseAir
    case edgeBaseline, edgeHold, edgeSweep, edgePose
    case mapBaseline, mapHold, mapSweep
    var id: String { rawValue }
    static let basic: [ProtocolKind] = [.baselineBefore, .corners, .clockwise, .counterclockwise, .diagonalDown, .diagonalUp, .baselineAfter]
    static let advanced: [ProtocolKind] = [.gridTrain, .gridTest, .horizontal, .vertical, .lift, .roll, .free]
    static let heightStudies: [ProtocolKind] = [.cornersHeight, .clockwiseAir, .counterclockwiseAir]
    var title: String {
        switch self {
        case .mapBaseline: return "격자 측정 · 줄별 배경"
        case .mapHold: return "격자 측정 · 좌표 정지"
        case .mapSweep: return "격자 측정 · 선 따라 자유 왕복"
        case .edgeBaseline: return "변 측정 · 배경"
        case .edgeHold: return "변 측정 · 기준점 정지"
        case .edgeSweep: return "변 측정 · 자유 속도 왕복"
        case .edgePose: return "변 측정 · 자세 영향"
        case .baselineBefore: return "01  시작 배경 자기장"
        case .corners: return "02  네 모서리에서 멈추기"
        case .gridTrain: return "정밀 · 5 × 5 좌표 학습"
        case .gridTest: return "정밀 · 4 × 4 새 좌표 검증"
        case .clockwise: return "03  접촉 테두리 · 시계 방향"
        case .counterclockwise: return "04  접촉 테두리 · 반시계 방향"
        case .cornersHeight: return "높이 · 모서리 접촉 ↔ 공중"
        case .clockwiseAir: return "공중 테두리 · 시계 방향"
        case .counterclockwiseAir: return "공중 테두리 · 반시계 방향"
        case .diagonalDown: return "05  대각선 ↘ ↖"
        case .diagonalUp: return "06  대각선 ↗ ↙"
        case .horizontal: return "추가 · 가로 왕복"
        case .vertical: return "추가 · 세로 왕복"
        case .lift: return "추가 · 중앙 들기 / 내리기"
        case .roll: return "추가 · 중앙 축 회전"
        case .free: return "추가 · 자유 궤적"
        case .baselineAfter: return "07  종료 배경 자기장"
        }
    }
    var summary: String {
        switch self {
        case .mapBaseline: return "이번 줄의 앞뒤에서 펜슬을 멀리 치우고 배경 10초"
        case .mapHold: return "표시된 점에서 준비 3초 후 정지 3초"
        case .mapSweep: return "표시된 선을 자유 속도로 한 번 왕복 · 돌아온 뒤 직접 완료"
        case .edgeBaseline: return "펜슬을 멀리 치우고 10초 동안 배경 측정"
        case .edgeHold: return "표시된 기준점에서 준비 3초 후 정지 3초"
        case .edgeSweep: return "편한 속도로 한 번 왕복하고 직접 완료 · 시간으로 좌표를 만들지 않습니다"
        case .edgePose: return "펜 끝을 고정하고 자세만 조금 바꾼 뒤 복귀"
        case .baselineBefore, .baselineAfter: return "펜슬을 충분히 멀리 치우고 10초 정지"
        case .corners: return "네 모서리를 세 번 · 총 12번만 멈추세요. 자와 격자는 필요 없습니다."
        case .cornersHeight: return "모서리마다 접촉 3초 → 2초에 들기 → 약 1cm 정지 3초 → 2초에 내리기 → 접촉 3초"
        case .clockwiseAir, .counterclockwiseAir: return "펜 끝을 책상에서 약 1cm 띄우고 같은 테두리 따라가기 · 12초 × 5회"
        case .gridTrain: return "25개 위치 × 3회 · 점마다 준비 3초 + 정지 3초"
        case .gridTest: return "학습점 사이 16개 위치 × 2회 · 별도 검증용"
        case .clockwise, .counterclockwise: return "왼쪽 위에서 시작 · 12초에 한 바퀴 × 5회"
        case .diagonalDown: return "왼쪽 위 → 오른쪽 아래 → 왼쪽 위 · 5회"
        case .diagonalUp: return "왼쪽 아래 → 오른쪽 위 → 왼쪽 아래 · 5회"
        case .horizontal: return "중앙 높이에서 왼쪽 ↔ 오른쪽 · 5회"
        case .vertical: return "중앙에서 위 ↔ 아래 · 5회"
        case .lift: return "중앙에서 접촉 3초 / 약간 들기 3초 × 5회"
        case .roll: return "중앙 위치·높이를 고정하고 축을 천천히 돌렸다 복귀 · 5회"
        case .free: return "30초 동안 도형이나 글씨 · 정답 좌표 없음"
        }
    }
    var isGrid: Bool { self == .gridTrain || self == .gridTest }
    var isStatic: Bool { isGrid || self == .corners || self == .edgeHold || self == .mapHold }
    var isCornerStudy: Bool { self == .corners || self == .cornersHeight }
    var isAirPath: Bool { self == .clockwiseAir || self == .counterclockwiseAir }
    var isHeightStudy: Bool { self == .cornersHeight || isAirPath }
    var isBaseline: Bool { self == .baselineBefore || self == .baselineAfter || self == .edgeBaseline || self == .mapBaseline }
    var dataset: String {
        if self == .corners { return "corner_pilot" }
        if self == .cornersHeight { return "height_paired" }
        if isAirPath { return "trajectory_air" }
        if self == .gridTrain { return "train" }
        if self == .gridTest { return "spatial_test" }
        if isBaseline { return "baseline" }
        return "trajectory"
    }
    var duration: Double {
        if self == .edgeSweep || self == .mapSweep { return 180 }
        if self == .edgePose { return 10 }
        if self == .cornersHeight { return 13 }
        if isStatic { return 3 }
        if isBaseline { return 10 }
        if self == .free || self == .lift { return 30 }
        return 60
    }
    var path: [Point2D] {
        let tl = Point2D(x: 0, y: 0), tr = Point2D(x: 1, y: 0)
        let bl = Point2D(x: 0, y: 1), br = Point2D(x: 1, y: 1)
        switch self {
        case .clockwise, .clockwiseAir: return [tl, tr, br, bl, tl]
        case .counterclockwise, .counterclockwiseAir: return [tl, bl, br, tr, tl]
        case .diagonalDown: return [tl, br, tl]
        case .diagonalUp: return [bl, tr, bl]
        case .horizontal: return [.init(x: 0, y: 0.5), .init(x: 1, y: 0.5), .init(x: 0, y: 0.5)]
        case .vertical: return [.init(x: 0.5, y: 0), .init(x: 0.5, y: 1), .init(x: 0.5, y: 0)]
        default: return []
        }
    }
    func target(at elapsed: Double) -> Point2D? {
        let points = path
        guard points.count > 1 else { return nil }
        let progress = max(0, elapsed).truncatingRemainder(dividingBy: 12) / 12
        let scaled = progress * Double(points.count - 1)
        let i = min(points.count - 2, Int(scaled)), f = scaled - Double(i)
        return .init(x: points[i].x + f * (points[i + 1].x - points[i].x),
                     y: points[i].y + f * (points[i + 1].y - points[i].y))
    }
}

struct TrialSpec: Codable, Identifiable {
    var id: String
    var kind: ProtocolKind
    var repetition: Int
    var pointID: String
    var point: Point2D?
    var nominalLiftMM: Double? = nil // Instruction only; never a measured height.
    var edge: StudyEdge? = nil
    var purpose: String? = nil
    var instruction: String? = nil
    var scenarioID: String? = nil
    var edgeAction: String? = nil
    var calibrationGroup: String? = nil
    var gridRow: Int? = nil
    var gridColumn: Int? = nil
    var guidePathID: String? = nil
    var gridSize: Int? = nil // Missing in historical 5x5 sessions; explicit for dense grids.
    var duration: Double { kind.duration }
    var dataset: String { purpose ?? kind.dataset }
    var isManual: Bool { kind == .edgeSweep || kind == .mapSweep }
    var locationName: String {
        if let guidePathID, let guide = GridGuide(rawValue: guidePathID) { return guide.title }
        if let row = gridRow, let column = gridColumn {
            return "위에서 \(row)행 · 왼쪽에서 \(column)열"
        }
        if let edge, let point {
            return "\(edge.title) · \(Int((edge.parameter(point) * 100).rounded()))% 지점"
        }
        switch pointID {
        case "top_left": return "왼쪽 위 모서리 · iPad 쪽"
        case "top_right": return "오른쪽 위 모서리 · iPad 쪽"
        case "bottom_right": return "오른쪽 아래 모서리 · 사용자 쪽"
        case "bottom_left": return "왼쪽 아래 모서리 · 사용자 쪽"
        default: return pointID
        }
    }

    static func make(_ kind: ProtocolKind, block: Int) -> [TrialSpec] {
        if kind.isCornerStudy {
            let points: [(String, Point2D)] = [
                ("top_left", .init(x: 0, y: 0)), ("top_right", .init(x: 1, y: 0)),
                ("bottom_right", .init(x: 1, y: 1)), ("bottom_left", .init(x: 0, y: 1))
            ]
            // Same, easy-to-follow order: clockwise, four corners, three rounds.
            var trials: [TrialSpec] = []
            for rep in 1...3 {
                for (name, point) in points {
                    trials.append(.init(id: "b\(block)-\(kind.rawValue)-\(rep)-\(name)", kind: kind,
                                        repetition: rep, pointID: name, point: point,
                                        nominalLiftMM: kind == .cornersHeight ? 10 : nil))
                }
            }
            return trials
        }
        guard kind.isGrid else {
            return [.init(id: "b\(block)-\(kind.rawValue)", kind: kind, repetition: 1, pointID: "", point: nil,
                          nominalLiftMM: kind.isAirPath ? 10 : nil)]
        }
        let n = kind == .gridTrain ? 5 : 4
        let rounds = kind == .gridTrain ? 3 : 2
        var result: [TrialSpec] = []
        for rep in 1...rounds {
            // A deterministic shuffle separates neighboring positions and balances order effects.
            var order = Array(0..<(n * n))
            var seed = UInt64(90210 + rep * 37 + block * 101)
            for i in stride(from: order.count - 1, through: 1, by: -1) {
                seed = seed &* 6364136223846793005 &+ 1442695040888963407
                order.swapAt(i, Int((seed >> 32) % UInt64(i + 1)))
            }
            for index in order {
                let col = index % n, row = index / n
                let offset = kind == .gridTest ? 0.5 : 0.0
                let pointID = "r\(row + 1)c\(col + 1)"
                let point = Point2D(x: (Double(col) + offset) / 4, y: (Double(row) + offset) / 4)
                let spec = TrialSpec(id: "b\(block)-\(kind.rawValue)-\(rep)-\(pointID)", kind: kind,
                                     repetition: rep, pointID: pointID, point: point)
                result.append(spec)
            }
        }
        return result
    }
}

struct TrialRecord: Codable {
    var spec: TrialSpec
    var startUptime: Double
    var settleSeconds = 3.0
    var endUptime: Double?
    var status = "recording"
    var reason = ""
    var activeStart: Double { startUptime + settleSeconds }
    var plannedEnd: Double { activeStart + spec.duration }
    func annotation(at timestamp: Double) -> (phase: String, point: Point2D?, source: String) {
        guard timestamp >= startUptime, timestamp < (endUptime ?? plannedEnd) else {
            return ("outside", nil, "none")
        }
        if timestamp < activeStart { return ("settle", spec.point ?? spec.kind.path.first, "guide_only") }
        let t = timestamp - activeStart
        if spec.kind == .edgeSweep { return ("move", nil, "known_edge_only") }
        if spec.kind == .mapSweep { return ("move", nil, "known_path_only") }
        if spec.kind == .edgePose {
            return (t < 3 ? "pose_reference" : (t < 7 ? "pose_change" : "pose_return"), spec.point, "manual_pose_probe")
        }
        if spec.kind == .cornersHeight {
            let phase: String
            if t < 3 { phase = "surface_hold" }
            else if t < 5 { phase = "lift_transition" }
            else if t < 8 { phase = "air_hold" }
            else if t < 10 { phase = "lower_transition" }
            else { phase = "surface_return" }
            return (phase, spec.point, "manual_height_instruction")
        }
        if spec.kind.isStatic { return ("hold", spec.point, "manual_static_target") }
        if spec.kind.isBaseline { return ("baseline", nil, "none") }
        if spec.kind == .lift {
            return (Int(t / 3) % 2 == 0 ? "contact_instruction" : "lift_instruction", .init(x: 0.5, y: 0.5), "guide_only")
        }
        if spec.kind == .roll { return ("roll_instruction", .init(x: 0.5, y: 0.5), "guide_only") }
        return ("move", spec.kind.target(at: t), spec.kind == .free ? "none" : "guide_only")
    }

    func instructedHeightMM(at timestamp: Double) -> Double? {
        let phase = annotation(at: timestamp).phase
        if spec.kind == .mapHold && phase == "hold" { return 0 }
        if spec.kind == .mapSweep && phase == "move" { return 0 }
        if spec.edge != nil && phase != "settle" && phase != "outside" { return 0 }
        if phase == "surface_hold" || phase == "surface_return" { return 0 }
        if phase == "air_hold" { return spec.nominalLiftMM }
        if phase == "move" && spec.kind.isAirPath { return spec.nominalLiftMM }
        if phase == "move" && (spec.kind == .clockwise || spec.kind == .counterclockwise) { return 0 }
        return nil // No height labels for transitions, settling, missing observations or other protocols.
    }
}

struct SessionManifest: Codable {
    var schemaVersion = 1
    var appVersion = "1.12.0"
    var id: String
    var startedAt: String
    var anchorUptime: Double
    var anchorUnix: Double
    var device: String
    var osVersion: String
    var setup: Setup
    var availableSensors: [String: Bool]
    var status = "recording"
    var endedAt: String?
    var trials: [TrialRecord] = []
    var sensorCounts: [String: Int] = [:]
    var warnings: [String] = []
    var coordinateDefinition = "User looking at desk rectangle: top-left=(0,0), right=+x, toward user/down=+y. Normalized coordinates, not screen pixels or mm."
    var pencilIMU = "Unavailable: no off-screen Apple Pencil raw IMU API. All IMU streams are from iPad."
    var motionReference = "xArbitraryZVertical (not magnetic north); raw magnetometer remains unmodified."
}

func number(_ value: Double) -> String {
    String(format: "%.9f", locale: Locale(identifier: "en_US_POSIX"), value)
}

func csvRow(_ fields: [String]) -> String {
    fields.map { field in
        if field.contains(",") || field.contains("\"") || field.contains("\n") || field.contains("\r") {
            return "\"" + field.replacingOccurrences(of: "\"", with: "\"\"") + "\""
        }
        return field
    }.joined(separator: ",") + "\n"
}
