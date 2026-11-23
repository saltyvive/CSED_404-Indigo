import Foundation

/// Operator-set fixture labels, never Pencil IMU or measured contact/height.
struct PrintedGridPose: Codable, Equatable {
    var phiDegrees = 0.0
    var thetaDegrees = 90.0
    // Missing legacy alpha stays unknown; only a scoped annotation may fill it.
    var alphaDegrees: Double? = 0
    var alphaLabelSource: String? = "operator_set_fixture_unmeasured"
    var alphaDefinition: String? = Self.alphaConvention
    var tipHeightMM = 0.0
    var tipContact = true
    var referenceNote = "φ=0: 기존 데모의 홀더 방향. θ=90°에서 로고 왼쪽. 펜의 독립적인 축 회전은 고정."
    var tiltDirectionAtPhiZero = "" // Required for tilted runs; vertical has no projected axis direction.
    var source = "operator_set_fixture_unmeasured"
    var phiDefinition = "Whole holder yaw about desk vertical; positive clockwise viewed from above; demo fixture orientation=0; 360 equivalent to 0. Not Pencil axial roll."
    var thetaDefinition = "Pencil axis elevation above desk plane: horizontal=0, vertical=90."
    static let alphaConvention = "fixture_phi_theta_alpha_v1: theta is elevation at alpha=0; alpha rotates the initial vertical pencil plane about its desk-projection hinge. Positive tips toward fixture-local right, which rotates with phi. Range [-90,90]. At theta=90 use the fixture reference line, never derive it from the zero-length projection. Phi remains whole-holder desk-vertical yaw, not Pencil axial roll."
    var needsHingeReference: Bool { thetaDegrees < 90 || (alphaDegrees ?? 0) != 0 }
    var readyForCollection: Bool {
        isValid && alphaDegrees != nil && alphaDefinition == Self.alphaConvention &&
        !(alphaLabelSource ?? "").isEmpty
    }
    var isValid: Bool {
        phiDegrees.isFinite && (0...360).contains(phiDegrees) &&
        thetaDegrees.isFinite && (0...90).contains(thetaDegrees) &&
        (alphaDegrees.map { $0.isFinite && (-90...90).contains($0) } ?? true) &&
        tipHeightMM.isFinite && tipHeightMM >= 0 &&
        (tipContact ? tipHeightMM == 0 : tipHeightMM > 0) &&
        !referenceNote.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        (!needsHingeReference || !tiltDirectionAtPhiZero.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }
    var canonical: Self {
        var result = self; if result.phiDegrees == 360 { result.phiDegrees = 0 }; return result
    }
    var summary: String {
        String(format: "φ %.1f° · θ %.1f° · α %@ · 높이 %.1f mm · %@", phiDegrees, thetaDegrees,
               alphaDegrees.map { String(format: "%.1f°", $0) } ?? "미기록", tipHeightMM, tipContact ? "접촉" : "공중")
    }
    func csvLabels(phase: String) -> [String] {
        phase == "hold" ? [number(phiDegrees), number(thetaDegrees), alphaDegrees.map(number) ?? "",
                           tipContact ? "contact" : "air", source, alphaLabelSource ?? ""] : Array(repeating: "", count: 6)
    }
}

/// Unsigned screen-plane inclination to gravity-defined horizontal, independent of UI orientation.
func ipadScreenInclination(gravity: [Double]) -> Double? {
    guard gravity.count == 3, gravity.allSatisfy(\.isFinite) else { return nil }
    let norm = sqrt(gravity.reduce(0) { $0 + $1*$1 })
    guard norm > 0.1 else { return nil }
    return acos(min(1, abs(gravity[2])/norm)) * 180 / .pi
}

struct IPadInclinationSnapshot: Codable {
    var degrees: Double
    var gravity: [Double]
    var sensorUptime: Double
    var source = "CoreMotion.gravity; acos(abs(gz)/norm(g)); screen plane vs gravity horizontal, 0=flat,90=upright"
}

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

    func make(block: Int, pose: PrintedGridPose = .init(), fast: Bool = false) -> [TrialSpec] {
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
                                   nominalPointMM: column.map { Point2D(x: Double($0-1)*2.5, y: Double(row-1)*2.5) },
                                   fixturePose: column == nil ? nil : pose.canonical,
                                   acquisitionSeconds: fast && column != nil ? 2 : nil,
                                   preparationSeconds: fast && column != nil ? 2 : nil))
        }
        append(column: nil, action: "before", instruction: "\(row)행 시작 배경입니다. 펜슬과 이동하는 홀더를 항상 같은 먼 위치에 두세요. iPad·종이·스탠드·케이블은 그대로 두고 준비 3초 후 10초간 측정합니다.")
        for column in columns {
            let position = pose.tipContact ? "검은 점에 펜 끝을 가볍게 대세요." : "검은 점의 수직 위에 펜촉을 맞추세요."
            let timing = fast ? "이동·준비 2초 후 정지 2초입니다. 준비 중 다음 점에 놓고, 측정 시작음부터 정지하세요. 늦었다면 일시정지를 눌러 다시 잽니다." : "위치를 확인하고 시작한 뒤 준비 3초 + 정지 3초 동안 손과 홀더를 멈추세요."
            append(column: column, action: "hold", instruction: "위에서 \(row)행, 왼쪽에서 \(column)열. \(position) \(pose.canonical.summary)를 유지합니다. \(timing)")
        }
        append(column: nil, action: "after", instruction: "\(row)행 종료 배경입니다. 펜슬과 이동하는 홀더를 시작 배경 때와 같은 먼 위치에 두세요. 10초 배경까지 끝나야 이 행이 완료됩니다. 자동 저장 후 쉬어도 됩니다.")
        return specs
    }

    /// Completion is reconstructed from files, not a count of button presses.
    func accepts(_ session: SessionManifest, campaignID: String) -> Bool {
        guard session.status == "completed", let meta = session.printedGrid,
              meta.campaignID == campaignID, meta.batch == self, meta.hasExpectedGeometry, meta.pose.isValid,
              session.setup.widthMM == "50", session.setup.heightMM == "30",
              abs(session.setup.aspect - 5.0/3.0) < 1e-9 else { return false }
        let completed = session.trials.filter { $0.status == "completed" }
        guard meta.timingRevision == nil || meta.timingRevision == "printed_2s_prepare_2s_hold_v2" else { return false }
        let expected = make(block: 0, pose: meta.pose, fast: meta.timingRevision != nil)
        guard completed.count == expected.count, Set(completed.map { $0.spec.id }).count == expected.count else { return false }
        for (actual, target) in zip(completed, expected) {
            let s = actual.spec
            guard s.scenarioID == id, s.pointID == target.pointID, s.kind == target.kind,
                  s.repetition == pass, s.calibrationGroup == target.calibrationGroup,
                  s.edgeAction == target.edgeAction, s.purpose == target.purpose,
                  s.gridRows == 13, s.gridColumns == 21, s.gridSize == nil,
                  s.gridRow == row, s.gridColumn == target.gridColumn,
                  s.point == target.point, s.nominalPointMM == target.nominalPointMM, s.fixturePose == target.fixturePose,
                  s.acquisitionSeconds == target.acquisitionSeconds, s.preparationSeconds == target.preparationSeconds,
                  actual.startUptime.isFinite, actual.settleSeconds == (target.preparationSeconds ?? 3),
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
    var pose = PrintedGridPose()
    var timingRevision: String? = nil
    var autoAdvanceEnabledAtStart: Bool? = nil
    var evaluationModelSHA256: String? = nil
    var evaluationTrainingPasses: [Int]? = nil
    var labelSource = "operator_confirmed_printed_target_unmeasured_pose"
    var coordinateDefinition = "Normalized top-left=(0,0); right=+x, toward user=+y. nominalPointMM=(50*x,30*y) from sweet spot top-left. Paper lower-left mm=(115+50*x,85-30*y). These are printed targets, not sensed tip coordinates."
    var hasExpectedGeometry: Bool {
        protocolID == PrintedGridBatch.protocolID && columns == 21 && rows == 13 &&
        widthMM == 50 && heightMM == 30 && pitchMM == 2.5 &&
        paperWidthMM == 297 && paperHeightMM == 210 && paperLowerLeftOffsetMM == .init(x: 115, y: 55)
    }
}

/// Only consecutive holds may auto-start. Backgrounds and row changes require a person.
struct PrintedAutoSequence {
    var enabled = true
    private(set) var running = false
    mutating func begin(isHold: Bool) { running = enabled && isHold }
    mutating func pause() { running = false }
    mutating func advance(nextIsHold: Bool, sensorFresh: Bool, deviceMoving: Bool) -> Bool {
        guard running && enabled && nextIsHold && sensorFresh && !deviceMoving else { pause(); return false }
        return true
    }
}

struct PrintedGridCampaign: Codable {
    var id = "SweetSpot-" + UUID().uuidString
    var createdAt = ISO8601DateFormatter().string(from: Date())
    var hasStarted = false
    var pose = PrintedGridPose()
    var setup: Setup = {
        var setup = Setup()
        setup.aspect = 5.0/3.0
        setup.widthMM = "50"; setup.heightMM = "30"
        setup.heightNote = "종이 표면 접촉 · 목표 높이 0 mm (실측 아님)"
        setup.environment = "플라스틱 빨대 홀더 · 종이/스탠드 고정 · 충전/케이스 상태를 기록하세요"
        return setup
    }()
}
