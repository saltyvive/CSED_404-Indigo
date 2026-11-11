import Foundation

extension EdgeScenario {
    static let denseTraining: [EdgeScenario] = [
        .grid9Train1A, .grid9Train1B, .grid9Train1C,
        .grid9Train2A, .grid9Train2B, .grid9Train2C,
        .grid9Train3A, .grid9Train3B, .grid9Train3C
    ]
    var denseIndex: Int? { Self.denseTraining.firstIndex(of: self) }
    var denseRound: Int? { denseIndex.map { $0 / 3 + 1 } }
    var gridSize: Int { denseRound == nil ? 5 : 9 }
    var nextDense: EdgeScenario? {
        guard let index = denseIndex, index + 1 < Self.denseTraining.count else { return nil }
        return Self.denseTraining[index + 1]
    }
    var denseRows: [Int] {
        guard let index = denseIndex, let round = denseRound else { return [] }
        let rows = round == 1 ? Array(1...9) : (round == 2 ? Array((1...9).reversed()) : [5, 1, 9, 3, 7, 2, 8, 4, 6])
        let first = (index % 3) * 3
        return Array(rows[first..<first+3])
    }
    var denseTitle: String {
        guard let index = denseIndex, let round = denseRound else { return "" }
        return "\(15 + round)\(["A", "B", "C"][index % 3])  9×9 학습 \(round)회차 · \(denseRows.map(String.init).joined(separator: ","))행"
    }
    func makeDenseGrid(block: Int) -> [TrialSpec] {
        guard let round = denseRound else { return [] }
        var result: [TrialSpec] = []
        for row in denseRows {
            let group = "pass\(round)-row\(row)"
            func append(_ column: Int?, action: String, text: String) {
                result.append(TrialSpec(id: "b\(block)-\(rawValue)-\(result.count)",
                                        kind: column == nil ? .mapBaseline : .mapHold, repetition: round,
                                        pointID: column.map { "r\(row)c\($0)" } ?? "\(group)-\(action)",
                                        point: column.map { .init(x: Double($0-1)/8, y: Double(row-1)/8) },
                                        purpose: column == nil ? "grid9_baseline" : "grid9_train",
                                        instruction: text, scenarioID: rawValue, edgeAction: action,
                                        calibrationGroup: group, gridRow: row, gridColumn: column, gridSize: 9))
            }
            append(nil, action: "before", text: "학습 \(round)회차 · \(row)행 시작 배경. 펜슬을 충분히 멀리 치우고 준비 3초 + 배경 10초를 측정하세요. iPad·스탠드·케이블은 고정합니다.")
            let columns = round == 3 ? [5, 1, 9, 3, 7, 2, 8, 4, 6] :
                ((row + round) % 2 == 0 ? Array(1...9) : Array((1...9).reversed()))
            for column in columns {
                append(column, action: "hold", text: "학습 \(round)/3회차 · 위에서 \(row)행, 왼쪽에서 \(column)열. 새 위치에 펜 끝을 가볍게 놓고 버튼을 누르세요. 준비 3초 뒤 3초간 정지합니다. 책상과 수직·로고 왼쪽을 유지하세요.")
            }
            append(nil, action: "after", text: "\(row)행 종료 배경. 펜슬을 충분히 멀리 치우고 준비 3초 + 배경 10초를 측정하세요. 오래 쉬려면 이 배경을 마친 뒤 쉬세요. 묶음의 마지막 배경 후 자동 저장됩니다.")
        }
        return result
    }
}
