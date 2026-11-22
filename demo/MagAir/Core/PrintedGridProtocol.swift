import Foundation

/// One row per file/checkpoint. All 39 batches belong to one training campaign.
struct PrintedGridBatch: Codable, Hashable, Identifiable {
    let pass: Int
    let row: Int
    static let protocolID = "sweetspot_21x13_v1"
    static let rowOrders = [Array(1...13), Array((1...13).reversed()),
                            [7, 1, 13, 4, 10, 2, 12, 5, 9, 3, 11, 6, 8]]
    static let all: [Self] = rowOrders.enumerated().flatMap { index, rows in
        rows.map { Self(pass: index + 1, row: $0) }
    }
    var id: String { "\(Self.protocolID)_p\(pass)_r\(row)" }
    var index: Int { Self.all.firstIndex(of: self)! }
    var title: String { String(format: "%02d/39 · %d회차 · %d행", index + 1, pass, row) }
    var columns: [Int] {
        // Reverse each row's approach on pass 2. Pass 3 changes row order;
        // keep adjacent columns easy to identify on the unnumbered paper.
        (row + pass) % 2 == 0 ? Array(1...21) : Array((1...21).reversed())
    }
    var direction: String { columns.first == 1 ? "왼쪽 → 오른쪽" : "오른쪽 → 왼쪽" }
    var next: Self? { index + 1 < Self.all.count ? Self.all[index + 1] : nil }

    func make(block: Int) -> [TrialSpec] {
        var specs: [TrialSpec] = []
        let group = "pass\(pass)-row\(row)"
        func append(column: Int?, action: String, instruction: String) {
            specs.append(TrialSpec(id: "b\(block)-\(id)-\(specs.count)",
                                   kind: column == nil ? .mapBaseline : .mapHold, repetition: pass,
                                   pointID: column.map { "r\(row)c\($0)" } ?? "\(group)-\(action)",
                                   point: column.map { Point2D(x: Double($0-1)/20, y: Double(row-1)/12) },
                                   purpose: column == nil ? "printed_grid_baseline" : "printed_grid_train",
                                   instruction: instruction, scenarioID: id, edgeAction: action,
                                   calibrationGroup: group, gridRow: row, gridColumn: column,
                                   gridColumns: 21, gridRows: 13,
                                   nominalPointMM: column.map { Point2D(x: Double($0-1)*2.5, y: Double(row-1)*2.5) }))
        }
        append(column: nil, action: "before", instruction: "\(row)행 시작 배경입니다. 펜슬과 이동하는 홀더를 항상 같은 먼 위치에 두세요. iPad·종이·스탠드·케이블은 그대로 두고 준비 3초 후 10초간 측정합니다.")
        for column in columns {
            append(column: column, action: "hold", instruction: "위에서 \(row)행, 왼쪽에서 \(column)열의 검은 점에 펜 끝을 가볍게 대세요. 종이와 수직 90°·로고 왼쪽을 유지합니다. 위치를 확인하고 시작한 뒤 준비 3초 + 정지 3초 동안 손과 홀더를 멈추세요.")
        }
        append(column: nil, action: "after", instruction: "\(row)행 종료 배경입니다. 펜슬과 이동하는 홀더를 시작 배경 때와 같은 먼 위치에 두세요. 10초 배경까지 끝나야 이 행이 완료됩니다. 자동 저장 후 쉬어도 됩니다.")
        return specs
    }

    /// Completion is reconstructed from files, not a count of button presses.
    func accepts(_ session: SessionManifest, campaignID: String) -> Bool {
        guard session.status == "completed", let meta = session.printedGrid,
              meta.campaignID == campaignID, meta.batch == self, meta.hasExpectedGeometry,
              session.setup.widthMM == "50", session.setup.heightMM == "30",
              abs(session.setup.aspect - 5.0/3.0) < 1e-9 else { return false }
        let completed = session.trials.filter { $0.status == "completed" }
        let expected = make(block: 0)
        guard completed.count == expected.count, Set(completed.map { $0.spec.id }).count == expected.count else { return false }
        for (actual, target) in zip(completed, expected) {
            let s = actual.spec
            guard s.scenarioID == id, s.pointID == target.pointID, s.kind == target.kind,
                  s.repetition == pass, s.calibrationGroup == target.calibrationGroup,
                  s.edgeAction == target.edgeAction, s.purpose == target.purpose,
                  s.gridRows == 13, s.gridColumns == 21, s.gridSize == nil,
                  s.gridRow == row, s.gridColumn == target.gridColumn,
                  s.point == target.point, s.nominalPointMM == target.nominalPointMM,
                  actual.startUptime.isFinite, actual.settleSeconds == 3,
                  let end = actual.endUptime, end.isFinite,
                  abs(end - actual.plannedEnd) < 0.001 else { return false }
        }
        return zip(completed, completed.dropFirst()).allSatisfy { $0.endUptime! <= $1.startUptime }
    }
}

struct PrintedGridMetadata: Codable {
    var protocolID = PrintedGridBatch.protocolID
    var campaignID: String
    var batch: PrintedGridBatch
    var columns = 21
    var rows = 13
    var widthMM = 50.0
    var heightMM = 30.0
    var pitchMM = 2.5
    var paperWidthMM = 297.0
    var paperHeightMM = 210.0
    var paperLowerLeftOffsetMM = Point2D(x: 115, y: 55)
    var nominalTiltDegrees = 90.0
    var nominalTipHeightMM = 0.0
    var nominalRoll = "Apple logo faces operator's left"
    var labelSource = "operator_confirmed_printed_target_unmeasured_pose"
    var coordinateDefinition = "Normalized top-left=(0,0); right=+x, toward user=+y. nominalPointMM=(50*x,30*y) from sweet spot top-left. Paper lower-left mm=(115+50*x,85-30*y). These are printed targets, not sensed tip coordinates."
    var hasExpectedGeometry: Bool {
        protocolID == PrintedGridBatch.protocolID && columns == 21 && rows == 13 &&
        widthMM == 50 && heightMM == 30 && pitchMM == 2.5 &&
        paperWidthMM == 297 && paperHeightMM == 210 && paperLowerLeftOffsetMM == .init(x: 115, y: 55)
    }
}

struct PrintedGridCampaign: Codable {
    var id = "SweetSpot-" + UUID().uuidString
    var createdAt = ISO8601DateFormatter().string(from: Date())
    var hasStarted = false
    var setup: Setup = {
        var setup = Setup()
        setup.aspect = 5.0/3.0
        setup.widthMM = "50"; setup.heightMM = "30"
        setup.heightNote = "종이 표면 접촉 · 목표 높이 0 mm (실측 아님)"
        setup.environment = "플라스틱 빨대 홀더 · 종이/스탠드 고정 · 충전/케이스 상태를 기록하세요"
        return setup
    }()
}
