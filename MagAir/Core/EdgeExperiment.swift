import Foundation

enum StudyEdge: String, Codable, CaseIterable, Identifiable {
    case top, bottom, left, right
    var id: String { rawValue }
    var title: String {
        switch self {
        case .top: return "위쪽 변 · iPad 쪽"
        case .bottom: return "아래쪽 변 · 사용자 쪽"
        case .left: return "왼쪽 변"
        case .right: return "오른쪽 변"
        }
    }
    var direction: String { self == .top || self == .bottom ? "왼쪽 → 오른쪽 → 왼쪽" : "위쪽 → 아래쪽 → 위쪽" }
    func point(_ s: Double) -> Point2D {
        switch self {
        case .top: return .init(x: s, y: 0)
        case .bottom: return .init(x: s, y: 1)
        case .left: return .init(x: 0, y: s)
        case .right: return .init(x: 1, y: s)
        }
    }
    func parameter(_ p: Point2D) -> Double { self == .top || self == .bottom ? p.x : p.y }
}

enum EdgeScenario: String, CaseIterable, Identifiable {
    case topTrain, topTest, bottomTrain, bottomTest, horizontalCompare
    case leftTrain, leftTest, rightTrain, rightTest, allCompare, gridMapTrain, gridMapTest
    case gridHorizontal, gridVertical, gridDiagonal
    case grid9Train1A, grid9Train1B, grid9Train1C
    case grid9Train2A, grid9Train2B, grid9Train2C
    case grid9Train3A, grid9Train3B, grid9Train3C
    case pose
    var id: String { rawValue }
    var edge: StudyEdge? {
        switch self {
        case .topTrain, .topTest, .pose: return .top
        case .bottomTrain, .bottomTest: return .bottom
        case .leftTrain, .leftTest: return .left
        case .rightTrain, .rightTest: return .right
        default: return nil
        }
    }
    var isTraining: Bool { [.topTrain, .bottomTrain, .leftTrain, .rightTrain].contains(self) }
    var isGridMap: Bool { self == .gridMapTrain || self == .gridMapTest || denseRound != nil }
    var isGridPath: Bool { [.gridHorizontal, .gridVertical, .gridDiagonal].contains(self) }
    var title: String {
        switch self {
        case .topTrain: return "01  위쪽 변 학습 · 먼저 이것만"
        case .topTest: return "02  위쪽 변 검증"
        case .bottomTrain: return "03  아래쪽 변 학습"
        case .bottomTest: return "04  아래쪽 변 검증"
        case .horizontalCompare: return "05  위·아래 변 구분"
        case .leftTrain: return "06  왼쪽 변 학습"
        case .leftTest: return "07  왼쪽 변 검증"
        case .rightTrain: return "08  오른쪽 변 학습"
        case .rightTest: return "09  오른쪽 변 검증"
        case .allCompare: return "10  네 변 구분"
        case .gridMapTrain: return "11  5×5 격자 학습"
        case .gridMapTest: return "12  5×5 격자 별도 검증"
        case .gridHorizontal: return "13  가로선 5개 자유 왕복"
        case .gridVertical: return "14  세로선 5개 자유 왕복"
        case .gridDiagonal: return "15  대각선 2개 자유 왕복"
        case .grid9Train1A, .grid9Train1B, .grid9Train1C, .grid9Train2A, .grid9Train2B, .grid9Train2C,
             .grid9Train3A, .grid9Train3B, .grid9Train3C: return denseTitle
        case .pose: return "추가  기울기·축 회전 영향"
        }
    }
    var summary: String {
        if let round = denseRound { return "9×9 학습 \(round)/3회차 · 이번 묶음은 3행의 27점 + 배경 6개, 총 33항목입니다. 약 5–7분이며 3회차도 모두 학습용입니다. 각 점은 준비 3초 + 정지 3초입니다." }
        if isGridPath { return "한 선마다 배경 10초 → 자유 속도로 한 번 왕복 → 배경 10초입니다. 돌아온 뒤 직접 완료를 누르세요. 속도로 좌표를 만들지 않으며, 선 이탈·끊김을 확인하는 검증 자료입니다." }
        if isGridMap { return self == .gridMapTrain ? "테두리 포함 25개 점을 한 번씩 측정합니다. 한 줄마다 시작 배경 → 다섯 점 → 종료 배경, 총 35항목·약 6–8분입니다." : "같은 25개 점을 다른 순서로 다시 측정합니다. 줄마다 시작·종료 배경을 재며 총 35항목입니다. 학습에 쓰지 않는 별도 세션입니다." }
        if isTraining { return "배경 → 다섯 점 × 2회 → 자유 왕복 3회 → 배경. 약 3–5분. 완료 후 저장해서 전달하세요." }
        if self == .pose { return "위쪽 변의 양 끝과 가운데에서 펜 끝을 고정합니다. 기울기와 축 회전의 영향을 따로 기록하며 각도는 측정하지 않습니다." }
        if edge != nil { return "배경 → 다섯 점 순서 섞어 1회 → 보통·느림·중간 정지 왕복 → 배경. 학습과 분리된 검증 자료입니다." }
        return "여러 변을 번갈아 측정합니다. 어느 변인지 알려주는 라벨은 검증 정답으로만 사용합니다. 공유 모서리는 변 분류 평가에서 제외합니다."
    }
    func make(block: Int) -> [TrialSpec] {
        if denseRound != nil { return makeDenseGrid(block: block) }
        var result: [TrialSpec] = []
        if isGridPath {
            let guides: [GridGuide] = self == .gridHorizontal ? [.row1, .row2, .row3, .row4, .row5] :
                (self == .gridVertical ? [.col1, .col2, .col3, .col4, .col5] : [.diagonalDown, .diagonalUp])
            for guide in guides {
                for action in ["before", "sweep", "after"] {
                    let moving = action == "sweep"
                    let text = moving ? "\(guide.title). 가로선은 왼쪽, 세로선은 위쪽, 대각선은 위쪽 모서리에서 시작합니다. 준비 3초 후 반대 끝까지 갔다가 돌아오세요. 양 끝에서 잠시 멈추고, 출발점으로 돌아온 뒤 ‘왕복 완료’를 누르세요. 속도는 자유입니다." :
                        "펜슬을 충분히 멀리 치우세요. 이 선의 \(action == "before" ? "시작" : "종료") 배경을 준비 3초 후 10초 측정합니다. iPad·스탠드·케이블을 그대로 두세요."
                    result.append(TrialSpec(id: "b\(block)-\(rawValue)-\(result.count)", kind: moving ? .mapSweep : .mapBaseline,
                                            repetition: 1, pointID: guide.rawValue + "-" + action, point: nil,
                                            purpose: moving ? "grid_path_test" : "grid_path_baseline", instruction: text,
                                            scenarioID: rawValue, edgeAction: action, calibrationGroup: guide.rawValue,
                                            guidePathID: guide.rawValue))
                }
            }
            return result
        }
        let role = isTraining ? "edge_train" : (self == .pose ? "edge_pose" : "edge_test")
        func add(_ kind: ProtocolKind, _ edge: StudyEdge?, _ s: Double?, _ rep: Int, _ action: String, _ text: String) {
            result.append(TrialSpec(id: "b\(block)-\(rawValue)-\(result.count)", kind: kind, repetition: rep,
                                    pointID: s.map { "s\(Int(($0*100).rounded()))" } ?? action,
                                    point: s.flatMap { edge?.point($0) }, edge: edge, purpose: kind.isBaseline ? "edge_baseline" : role,
                                    instruction: text, scenarioID: rawValue, edgeAction: action))
        }
        if isGridMap {
            let rows = self == .gridMapTrain ? [0, 1, 2, 3, 4] : [4, 2, 0, 3, 1]
            let purpose = self == .gridMapTrain ? "grid_map_train" : "grid_map_test"
            for (order, row) in rows.enumerated() {
                let group = "row\(row + 1)"
                func append(_ kind: ProtocolKind, column: Int? = nil, action: String, text: String) {
                    let point = column.map { Point2D(x: Double($0)/4, y: Double(row)/4) }
                    result.append(TrialSpec(id: "b\(block)-\(rawValue)-\(result.count)", kind: kind, repetition: 1,
                                            pointID: column.map { "r\(row + 1)c\($0 + 1)" } ?? "\(group)-\(action)", point: point,
                                            purpose: kind.isBaseline ? "grid_map_baseline" : purpose, instruction: text,
                                            scenarioID: rawValue, edgeAction: action, calibrationGroup: group,
                                            gridRow: row + 1, gridColumn: column.map { $0 + 1 }))
                }
                append(.mapBaseline, action: "before", text: "위에서 \(row + 1)번째 줄의 시작 배경입니다. 펜슬을 충분히 멀리 치우고 시작하세요. iPad·스탠드·케이블은 그대로 두세요.")
                let columns = self == .gridMapTrain ? (row % 2 == 0 ? [0, 1, 2, 3, 4] : [4, 3, 2, 1, 0]) : [2, 0, 4, 1, 3]
                for column in columns {
                    append(.mapHold, column: column, action: "hold", text: "위에서 \(row + 1)행, 왼쪽에서 \(column + 1)열의 표식에 펜 끝을 가볍게 대세요. 수직·로고 왼쪽을 유지합니다. 준비 3초 동안 자세를 잡고, 이어지는 3초 동안 멈추세요.")
                }
                let finish = order == rows.count - 1 ? "마지막 배경이 끝나면 자동 저장·종료됩니다." : "이후 다음 줄을 새 배경으로 측정합니다."
                append(.mapBaseline, action: "after", text: "펜슬을 다시 충분히 멀리 치우세요. 위에서 \(row + 1)번째 줄의 종료 배경입니다. \(finish)")
            }
            return result
        }
        add(.edgeBaseline, nil, nil, 1, "before", "펜슬을 iPad에서 충분히 멀리 치우세요. 배치와 주변 물체를 고정하고 배경을 측정합니다.")
        if self == .pose {
            for s in [0.0, 0.5, 1.0] {
                add(.edgePose, .top, s, 1, "tilt", "펜 끝은 같은 점에 고정. 수직 정지 3초 → 사용자 쪽으로 조금 기울여 4초 → 수직으로 복귀 3초. 로고 방향은 유지하세요.")
                add(.edgePose, .top, s, 1, "roll", "펜 끝·수직 자세는 고정. 로고 왼쪽으로 정지 3초 → 펜 축을 조금 돌려 4초 → 원래 방향으로 복귀 3초.")
            }
        } else {
            let edges: [StudyEdge] = edge.map { [$0] } ?? (self == .horizontalCompare ? [.top, .bottom] : StudyEdge.allCases)
            let rounds = isTraining ? 2 : 1
            for rep in 1...rounds {
                let positions = isTraining ? (rep == 1 ? [0.0, 0.25, 0.5, 0.75, 1.0] : [1.0, 0.75, 0.5, 0.25, 0.0]) : [0.5, 0.0, 0.75, 0.25, 1.0]
                for s in positions { for e in edges {
                    add(.edgeHold, e, s, rep, "hold", "표시된 지점에 펜 끝을 가볍게 대세요. 책상과 수직, 로고 왼쪽. 시작 후 준비 3초, 이어서 정지 3초입니다.")
                } }
            }
            for rep in 1...3 { for e in edges {
                let style = isTraining || rep == 1 ? "편한 속도로" : (rep == 2 ? "앞선 왕복보다 천천히" : "가는 길 가운데에서 잠시 멈췄다가")
                add(.edgeSweep, e, nil, rep, isTraining ? "normal" : ["normal", "slow", "pause"][rep-1],
                    "\(e.direction). 시작점 0%에서 출발해 \(style) 한 번 왕복하세요. 양 끝에서 잠시 정지하고, 출발점에 돌아온 뒤 ‘왕복 완료’를 누르세요. 화면 속도를 따라가지 않습니다.")
            } }
        }
        add(.edgeBaseline, nil, nil, 1, "after", "펜슬을 다시 충분히 멀리 치우세요. 마지막 배경 측정이 끝나면 이 묶음을 자동 저장·종료합니다.")
        return result
    }
}
