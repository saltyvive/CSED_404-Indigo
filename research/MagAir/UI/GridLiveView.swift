import SwiftUI
import Combine
import CryptoKit

enum GridMappingMethod: String, CaseIterable, Identifiable {
    case bilinear = "A · 기존 보간"
    case neighbors = "B · k-NN 회귀"
    case neural = "C · 공동 학습"
    var id: String { rawValue }
    var explanation: String {
        switch self {
        case .bilinear: return "A: 높이별 보간 지도에서 더 잘 맞는 위치·높이를 선택"
        case .neighbors: return "B: 높이별 k-NN 모델에서 더 가까운 패턴의 위치·높이를 선택"
        case .neural: return "C: 두 높이를 함께 학습한 하나의 신경망이 위치와 접촉 점수를 동시에 예측"
        }
    }
}

final class GridLiveTester: ObservableObject {
    @Published var model: GridLiveModel?
    @Published var knnModel: KNNLiveModel?
    @Published var selectedMethod: GridMappingMethod = .bilinear
    @Published private(set) var selectedCombination = "123"
    private(set) var library: GridModelLibrary?
    var isJoint: Bool { selectedCombination == JointHeightProjector.id }
    var selectedEntry: GridModelEntry? { library?.pair(selectedCombination)?.entry }
    var selectedCondition: GridModelCondition? { library?.condition(for: selectedCombination) }
    var conditionID: String { isJoint ? JointHeightProjector.id : selectedCondition?.id ?? "air3" }
    private static let selectionKey = "gridLive.selectedCombination.v2"
    private(set) var gridModelSHA256: String?
    @Published var baseline: [Double]?
    @Published var calibrating = false
    @Published var remaining = 5.0
    @Published var status = "펜을 멀리 두고 배경을 맞추세요"
    @Published private var gridEstimate: GridEstimate?
    @Published private var knnEstimate: GridEstimate?
    @Published private var jointA: JointHeightEstimate?
    @Published private var jointB: JointHeightEstimate?
    @Published private(set) var neuralEstimate: JointNeuralEstimate?
    private(set) var neuralBundle: JointNeuralBundle?
    private(set) var neuralLoadError: String?
    var jointEstimate: JointHeightEstimate? {
        selectedMethod == .neural ? nil : selectedMethod == .bilinear ? jointA : jointB
    }
    var displayColor: Color {
        let state = selectedMethod == .neural ? neuralEstimate?.state : jointEstimate?.state
        return isJoint && state == .air ? .purple : .teal
    }
    var displayStatus: String {
        if selectedMethod == .neural { return neuralEstimate?.reason ?? status }
        return isJoint ? jointEstimate?.reason ?? status : estimate?.reason ?? status
    }
    var estimate: GridEstimate? {
        switch selectedMethod {
        case .bilinear: return gridEstimate
        case .neighbors: return knnEstimate
        case .neural: return neuralEstimate?.gridEstimate
        }
    }
    var comparison: [(String, GridEstimate?, JointTipState?)] {
        [("A", gridEstimate, jointA?.state), ("B", knnEstimate, jointB?.state),
         ("C", neuralEstimate?.gridEstimate, neuralEstimate?.state)]
    }
    @Published var exportURL: URL?
    @Published var logStatus = "배경을 맞추면 테스트 기록이 자동 저장됩니다"
    @Published var baselineAge = 0.0
    @Published var guide: GridGuide = .free
    @Published private var gridTrail: [GridTrailPoint] = []
    @Published private var knnTrail: [GridTrailPoint] = []
    @Published private var neuralTrail: [GridTrailPoint] = []
    var trail: [GridTrailPoint] { selectedMethod == .neural ? neuralTrail : selectedMethod == .bilinear ? gridTrail : knnTrail }
    private var lastAcceptedTime: Double?
    private var lastKNNAcceptedTime: Double?
    private var lastNeuralAcceptedTime: Double?
    private(set) var knnModelSHA256: String?
    private var gridModelData: Data?
    private var knnModelData: Data?
    var calibrationSettle: Double { model?.printedGridContext == nil ? 2 : 3 }
    var calibrationCapture: Double { model?.printedGridContext == nil ? 3 : 10 }
    var calibrationTotal: Double { calibrationSettle + calibrationCapture }

    func clearTrail() {
        gridTrail = []; knnTrail = []; neuralTrail = []
        lastAcceptedTime = nil; lastKNNAcceptedTime = nil; lastNeuralAcceptedTime = nil
    }

    var active = false
    private var projector: GridProjector?
    private var knnProjector: KNNProjector?
    private var jointProjector: JointHeightProjector?
    private var calibrationStart = 0.0
    private var calibrationSamples: [(Double, [Double])] = []
    private var baselineTime = 0.0
    private var baselineNoise = 0.0
    private var baselineSamples: [(Double, [Double])] = []
    private var recent: [(Double, [Double])] = []
    private var lastDisplay = 0.0
    private var lastSensorTime = 0.0
    private var logURL: URL?
    private var handle: FileHandle?
    private let io = DispatchQueue(label: "MagAir.gridLive.log")
    private var lastSync = 0.0

    init() {
        do {
            library = try GridModelLibrary.load { resource in
                guard let url = Bundle.main.url(forResource: resource, withExtension: "json") else {
                    throw GridModelLibrary.LoadError.invalid("모델 파일 누락: \(resource)")
                }
                return try Data(contentsOf: url)
            }
            do {
                neuralBundle = try JointNeuralBundle.load(library: library!) { resource in
                    guard let url = Bundle.main.url(forResource: resource, withExtension: "json") else {
                        throw GridModelLibrary.LoadError.invalid("C 모델 파일 누락")
                    }
                    return try Data(contentsOf: url)
                }
            } catch { neuralLoadError = error.localizedDescription }
            let saved = UserDefaults.standard.string(forKey: Self.selectionKey)
            let args = ProcessInfo.processInfo.arguments
            let initial: String? = args.contains("--live-joint-height") || args.contains("--live-joint-mlp") ? JointHeightProjector.id : args.contains("--live-hover3") ? "hover3_1" : saved
            selectCombination(initial.flatMap { $0 == JointHeightProjector.id || library!.pair($0) != nil ? $0 : nil } ?? JointHeightProjector.id)
            if args.contains("--live-joint-mlp"), neuralBundle != nil { selectedMethod = .neural }
        } catch { status = "모델 읽기 실패: \(error.localizedDescription)" }
    }

    func selectCombination(_ id: String) {
        guard !calibrating, id != selectedCombination || model == nil, let library,
              let pair = library.pair(id == JointHeightProjector.id ? "13" : id),
              let a = GridProjector(model: pair.modelA), let b = KNNProjector(model: pair.modelB) else { return }
        let joint = id == JointHeightProjector.id ? JointHeightProjector(library: library) : nil
        guard id != JointHeightProjector.id || joint != nil else { status = "통합 모델 읽기 실패"; return }
        let sameCondition = library.canReuseBaseline(from: selectedCombination, to: id)
        if !sameCondition { invalidate("학습 높이 조건 변경 · 펜과 홀더를 멀리 두고 배경을 다시 맞추세요") }
        else { closeLog(reason: "training_combination_changed_to_" + id) }
        clearTrail(); gridEstimate = nil; knnEstimate = nil; jointA = nil; jointB = nil; neuralEstimate = nil; exportURL = nil
        selectedCombination = id
        if !isJoint && selectedMethod == .neural { selectedMethod = .bilinear }
        UserDefaults.standard.set(id, forKey: Self.selectionKey)
        model = pair.modelA; knnModel = pair.modelB; projector = a; knnProjector = b
        jointProjector = joint
        gridModelData = pair.dataA; knnModelData = pair.dataB
        gridModelSHA256 = pair.entry.sha256A; knnModelSHA256 = pair.entry.sha256B
        // The same baseline and causal sensor window remain valid for every same-condition pair.
        if let baseline, active {
            startLog(baseline: baseline, noise: baselineNoise)
            status = "\(selectedCondition?.title ?? "") · \(pair.entry.title)회차 모델 · 같은 배경으로 비교 중"
        } else { status = "펜을 멀리 두고 배경을 맞추세요" }
    }

    func selectCondition(_ id: String) {
        if id == JointHeightProjector.id { selectCombination(id); return }
        guard let condition = library?.conditions.first(where: { $0.id == id }) else { return }
        selectCombination(condition.defaultCombination)
    }

    func calibrate() {
        guard active, model != nil else { return }
        closeLog(reason: "background_recalibration")
        clearTrail()
        baseline = nil; gridEstimate = nil; knnEstimate = nil; jointA = nil; jointB = nil; neuralEstimate = nil; recent = []; calibrationSamples = []; exportURL = nil
        calibrationStart = ProcessInfo.processInfo.systemUptime
        calibrating = true; remaining = calibrationTotal; baselineAge = 0
        status = "준비 \(Int(calibrationSettle))초 · 펜슬과 이동 홀더를 충분히 멀리 치우세요"
    }

    func invalidate(_ message: String) {
        clearTrail()
        baseline = nil; gridEstimate = nil; knnEstimate = nil; jointA = nil; jointB = nil; neuralEstimate = nil; calibrating = false; recent = []
        closeLog(reason: message); status = message
    }

    func deviceMoved() {
        guard active, baseline != nil || calibrating else { return }
        if calibrating && ProcessInfo.processInfo.systemUptime - calibrationStart < calibrationSettle { return }
        invalidate("iPad 움직임 감지 · 고정한 뒤 배경을 다시 맞추세요")
    }

    func checkStale(now: Double) {
        guard active, baseline != nil || calibrating else { return }
        if now - lastSensorTime > 1 { invalidate("센서 수신 중단 · 배경을 다시 맞추세요") }
    }

    func receive(timestamp: Double, field: [Double]) {
        guard active, field.count == 3, field.allSatisfy(\.isFinite) else { return }
        lastSensorTime = timestamp
        if calibrating {
            let elapsed = timestamp - calibrationStart
            remaining = max(0, calibrationTotal - elapsed)
            status = elapsed < calibrationSettle ? "준비 중 · 펜슬과 홀더를 충분히 멀리" : "배경 측정 중 · 배치를 유지하세요"
            if elapsed >= calibrationSettle && elapsed < calibrationTotal { calibrationSamples.append((timestamp, field)) }
            if elapsed >= calibrationTotal {
                calibrating = false
                guard calibrationSamples.count >= Int(calibrationCapture*30),
                      let first = calibrationSamples.first, let last = calibrationSamples.last,
                      last.0 - first.0 >= calibrationCapture-0.5,
                      zip(calibrationSamples, calibrationSamples.dropFirst()).allSatisfy({ $1.0 - $0.0 <= 0.15 }) else {
                    status = "배경 샘플 부족 또는 수신 공백 · 다시 시도하세요"; return
                }
                let b = (0..<3).map { axis in medianValue(calibrationSamples.map { $0.1[axis] }) }
                let noise = sqrt(calibrationSamples.reduce(0.0) { sum, sample in
                    sum + zip(sample.1, b).reduce(0.0) { $0 + pow($1.0 - $1.1, 2) }
                } / Double(calibrationSamples.count))
                guard noise < 3 else { status = "배경이 불안정합니다 · 펜을 치우고 다시 시도하세요"; return }
                baseline = b; baselineTime = timestamp; baselineNoise = noise; baselineSamples = calibrationSamples
                startLog(baseline: b, noise: noise)
                status = "배경 준비 완료 · 격자 내부와 선을 따라 움직여 보세요"
                calibrationSamples = []
            }
            return
        }
        guard let baseline, let projector else { return }
        recent.append((timestamp, field)); recent.removeAll { timestamp - $0.0 > 0.12 }
        guard timestamp - lastDisplay >= 0.09, recent.count >= 3 else { return }
        lastDisplay = timestamp; baselineAge = max(0, timestamp - baselineTime)
        let filtered = (0..<3).map { axis in medianValue(recent.map { $0.1[axis] }) - baseline[axis] }
        let result: GridEstimate
        let neighborResult: GridEstimate?
        if let jointProjector {
            guard let joint = jointProjector.project(filtered) else {
                gridEstimate = nil; knnEstimate = nil; jointA = nil; jointB = nil; neuralEstimate = nil; return
            }
            jointA = joint.a; jointB = joint.b
            neuralEstimate = neuralBundle?.projector.project(filtered)
            result = joint.a.estimate; neighborResult = joint.b.estimate
        } else {
            guard let single = projector.project(filtered) else { gridEstimate = nil; knnEstimate = nil; return }
            result = single; neighborResult = knnProjector?.project(filtered)
        }
        gridEstimate = result; knnEstimate = neighborResult
        var columns = [number(timestamp), number(Date().timeIntervalSince1970)]
        columns += field.map(number)
        columns += baseline.map(number)
        columns += filtered.map(number)
        columns += [number(result.point.x), number(result.point.y), number(result.residual)]
        columns += [number(result.limit), number(result.signal), result.accepted ? "1" : "0", result.showCandidate ? "1" : "0"]
        columns += [result.ambiguous ? "1" : "0", number(baselineAge), number(result.otherLocationResidual), guide.rawValue]
        if let b = neighborResult {
            columns += [number(b.point.x),number(b.point.y),number(b.residual),number(b.limit),number(b.signal),
                        b.accepted ? "1" : "0",b.showCandidate ? "1" : "0",b.ambiguous ? "1" : "0",number(b.otherLocationResidual)]
        } else { columns += Array(repeating: "", count: 9) }
        columns += [selectedMethod.rawValue, selectedCombination, conditionID,
                    isJoint ? "" : model?.printedGridContext.map { number($0.pose.tipHeightMM) } ?? "",
                    isJoint ? "" : model?.printedGridContext.map { $0.pose.tipContact ? "contact" : "air" } ?? "",
                    isJoint ? "" : model?.printedGridContext?.campaignID ?? ""]
        columns += jointLogColumns(jointA) + jointLogColumns(jointB) + neuralLogColumns()
        if result.accepted {
            let state = jointA?.state
            let begins = (lastAcceptedTime.map { timestamp-$0 > 0.3 } ?? true) || gridTrail.last?.state != state
            gridTrail.append(GridTrailPoint(time: timestamp, point: result.point, beginsSegment: begins, state: state))
            lastAcceptedTime = timestamp
        } else { lastAcceptedTime = nil }
        gridTrail.removeAll { timestamp-$0.time > 8 }
        if let b = neighborResult, b.accepted {
            let state = jointB?.state
            let begins = (lastKNNAcceptedTime.map { timestamp-$0 > 0.3 } ?? true) || knnTrail.last?.state != state
            knnTrail.append(GridTrailPoint(time: timestamp, point: b.point, beginsSegment: begins, state: state))
            lastKNNAcceptedTime = timestamp
        } else { lastKNNAcceptedTime = nil }
        knnTrail.removeAll { timestamp-$0.time > 8 }
        if let c = neuralEstimate, c.accepted {
            let begins = (lastNeuralAcceptedTime.map { timestamp-$0 > 0.3 } ?? true) || neuralTrail.last?.state != c.state
            neuralTrail.append(.init(time: timestamp, point: c.point, beginsSegment: begins, state: c.state))
            lastNeuralAcceptedTime = timestamp
        } else { lastNeuralAcceptedTime = nil }
        neuralTrail.removeAll { timestamp-$0.time > 8 }
        if let handle {
            let data = Data(csvRow(columns).utf8)
            let sync = timestamp - lastSync >= 2
            if sync { lastSync = timestamp }
            io.async { [weak self] in
                do { try handle.write(contentsOf: data); if sync { try handle.synchronize() } }
                catch { DispatchQueue.main.async { self?.logStatus = "기록 저장 실패: \(error.localizedDescription)" } }
            }
        }
    }

    private static let jointColumnNames = ["estimated_state", "closest_height_candidate", "height_gap_uT", "height_ambiguous",
        "contact_x", "contact_y", "contact_residual_uT", "contact_position_accepted", "contact_position_ambiguous",
        "air_x", "air_y", "air_residual_uT", "air_position_accepted", "air_position_ambiguous"]
    private static let neuralColumnNames = ["c_estimated_x", "c_estimated_y", "c_contact_score", "c_estimated_state", "c_closest_state",
        "c_support_distance_uT", "c_support_limit_uT", "c_signal_uT", "c_accepted", "c_candidate_shown", "c_in_bounds", "c_in_support", "c_contact_ambiguous"]
    private func neuralLogColumns() -> [String] {
        guard let c = neuralEstimate else { return Array(repeating: "", count: Self.neuralColumnNames.count) }
        return [number(c.point.x), number(c.point.y), number(c.contactScore), c.state.rawValue, c.closestState.rawValue,
                number(c.supportDistanceUT), number(c.supportLimitUT), number(c.signal), c.accepted ? "1" : "0",
                c.showCandidate ? "1" : "0", c.inBounds ? "1" : "0", c.inSupport ? "1" : "0", c.ambiguous ? "1" : "0"]
    }
    private func jointLogColumns(_ joint: JointHeightEstimate?) -> [String] {
        guard let j = joint else { return Array(repeating: "", count: Self.jointColumnNames.count) }
        return [j.state.rawValue, j.closestState.rawValue, number(j.gapUT), j.heightAmbiguous ? "1" : "0",
                number(j.contact.point.x), number(j.contact.point.y), number(j.contact.residual), j.contact.accepted ? "1" : "0", j.contact.ambiguous ? "1" : "0",
                number(j.air.point.x), number(j.air.point.y), number(j.air.residual), j.air.accepted ? "1" : "0", j.air.ambiguous ? "1" : "0"]
    }

    private func startLog(baseline: [Double], noise: Double) {
        do {
            let folder = SessionStore.root.deletingLastPathComponent().appendingPathComponent("MagAirGridLiveTests")
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
            let url = folder.appendingPathComponent("GridLive-\(stamp)-\(UUID().uuidString.prefix(6)).csv")
            var header = ["timestamp_s", "callback_unix_s", "bx_uT", "by_uT", "bz_uT", "baseline_x_uT", "baseline_y_uT", "baseline_z_uT",
                          "filtered_delta_x_uT", "filtered_delta_y_uT", "filtered_delta_z_uT", "estimated_x", "estimated_y",
                          "residual_uT", "residual_limit_uT", "signal_uT", "accepted", "candidate_shown", "ambiguous", "baseline_age_s",
                          "distant_location_residual_uT", "display_guide_only",
                          "knn_estimated_x", "knn_estimated_y", "knn_residual_uT", "knn_residual_limit_uT", "knn_signal_uT",
                          "knn_accepted", "knn_candidate_shown", "knn_ambiguous", "knn_distant_location_residual_uT", "viewed_model", "training_combination",
                          "model_training_condition", "model_tip_height_mm", "model_tip_state", "model_campaign_id"]
            header += Self.jointColumnNames.map { "joint_a_" + $0 } + Self.jointColumnNames.map { "joint_b_" + $0 }
            header += Self.neuralColumnNames
            try Data(csvRow(header).utf8).write(to: url, options: .atomic)
            if let gridModelData {
                try gridModelData.write(to: url.deletingPathExtension().appendingPathExtension("model.json"), options: .atomic)
            }
            if let knnModelData {
                try knnModelData.write(to: url.deletingPathExtension().appendingPathExtension("knn-model.json"), options: .atomic)
            }
            var metadata: [String: Any] = ["baselineUT": baseline, "baselineNoiseUT": noise, "baselineTimestamp": baselineTime,
                                         "trainingCombination": selectedCombination,
                                         "modelTrainingCondition": conditionID,
                                         "contactDetectionAvailable": isJoint,
                                         "contactDetectionMethod": isJoint ? "experimental_two_height_residual_comparison_v1" : "none",
                                         "measuredContactAvailable": false,
                                         "trainingPasses": isJoint ? [] : model?.printedGridContext?.passes ?? [],
                                         "calibrationSamples": baselineSamples.map { [$0.0] + $0.1 },
                                         "filter": "causal component median, 0.12 seconds; no coordinate smoothing or prediction",
                                         "modelASHA256": gridModelData.map { SHA256.hash(data: $0).map { String(format: "%02x", $0) }.joined() } ?? "",
                                         "modelBSHA256": knnModelSHA256 ?? "",
                                         "scope": "A and B run on identical filtered magnetic input and the same live baseline. Unprefixed estimate columns are A; knn_ columns are B. viewed_model only selects display. model_* height/state/condition are selected model training labels, not detected live pose/contact. Guide is never timestamped ground truth. No Pencil IMU or measured contact."]
            if let jointProjector {
                let air = jointProjector.airPair
                try air.dataA.write(to: url.deletingPathExtension().appendingPathExtension("air-model.json"), options: .atomic)
                try air.dataB.write(to: url.deletingPathExtension().appendingPathExtension("air-knn-model.json"), options: .atomic)
                metadata["heightMarginUT"] = JointHeightEstimate.marginUT
                metadata["heightHypotheses"] = try [jointProjector.contactPair, air].map { pair -> [String: Any] in
                    ["combination": pair.entry.id, "modelASHA256": pair.entry.sha256A, "modelBSHA256": pair.entry.sha256B,
                     "context": try JSONSerialization.jsonObject(with: JSONEncoder().encode(pair.modelA.printedGridContext!))]
                }
                metadata["scope"] = "Experimental joint XY and 0/3mm inference. Contact uses passes 1+3 only; air uses pass 1. Both height models search all XY on the same magnetic input. Smaller raw residual wins; gap <= 0.75uT or winner position rejection abstains. Not calibrated probabilities or measured contact; other heights unvalidated. A/B run together; unprefixed XY is A and knn_ XY is B. Joint columns preserve both height candidates. Model height/state/campaign single-label columns are empty. No Pencil IMU, fixture labels or guide used as live inputs. B has 8 contact vs 4 air patterns per XY, which may bias nearest residuals. No independent air repeat validation."
                if let neuralBundle {
                    try neuralBundle.data.write(to: url.deletingPathExtension().appendingPathExtension("c-model.json"), options: .atomic)
                    metadata["modelCSHA256"] = neuralBundle.sha256
                    metadata["modelCPlanSHA256"] = neuralBundle.projector.model.planSHA256
                    metadata["modelCScope"] = "Single shared MLP jointly trained on contact passes 1+3 and air pass 1; equal total loss weight per height. Predicts XY and uncalibrated sigmoid contact score from the same filtered field as A/B. c_ columns are C; support distance only gates display, never selects XY or height. Scores 0.35 < p < 0.65 abstain. Other display gates: minimum signal, training support distance, XY bounds. C has no independent air repeat validation; five-fold spatial row holdout is separate from final model training replay."
                }
            } else if let context = model?.printedGridContext {
                metadata["modelTrainingContext"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode(context))
            }
            try JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys])
                .write(to: url.deletingPathExtension().appendingPathExtension("metadata.json"), options: .atomic)
            handle = try FileHandle(forWritingTo: url); try handle?.seekToEnd()
            logURL = url; lastSync = baselineTime
            logStatus = "자동 저장 중 · 맥북에서 직접 가져올 수 있습니다"
        } catch { logStatus = "테스트 기록 생성 실패: \(error.localizedDescription)" }
    }

    private func closeLog(reason: String) {
        if let handle {
            let endURL = logURL?.deletingPathExtension().appendingPathExtension("end.json")
            let endedUptime = ProcessInfo.processInfo.systemUptime
            io.async { [weak self] in
                do {
                    try handle.synchronize(); try handle.close()
                    if let endURL {
                        let end: [String: Any] = ["reason": reason, "endedUptime": endedUptime]
                        try JSONSerialization.data(withJSONObject: end, options: [.prettyPrinted, .sortedKeys])
                            .write(to: endURL, options: .atomic)
                    }
                }
                catch { DispatchQueue.main.async { self?.logStatus = "기록 마감 실패: \(error.localizedDescription)" } }
            }
            self.handle = nil
            logStatus = "테스트 기록 저장 완료 · 맥북에서 가져올 수 있습니다"
        }
    }

    func shareSnapshot() {
        guard let url = logURL else { return }
        let currentHandle = handle
        io.async { [weak self] in
            do {
                try currentHandle?.synchronize()
                let copy = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + "-" + url.lastPathComponent)
                try FileManager.default.copyItem(at: url, to: copy)
                DispatchQueue.main.async { self?.exportURL = copy }
            } catch { DispatchQueue.main.async { self?.logStatus = "공유 파일 생성 실패: \(error.localizedDescription)" } }
        }
    }
}

struct GridTrailPoint {
    var time: Double
    var point: Point2D
    var beginsSegment: Bool
    var state: JointTipState? = nil
}

struct GridLiveView: View {
    @ObservedObject var collector: Collector
    @ObservedObject var tester: GridLiveTester
    var collectPrinted: () -> Void
    var gridColumns: Int { tester.model?.xKnots.count ?? 5 }
    var gridRows: Int { tester.model?.yKnots.count ?? 5 }
    var printed: PrintedGridModelContext? { tester.model?.printedGridContext }

    private func metricLine(_ evaluation: GridCombinationEvaluation) -> String {
        let m = tester.selectedMethod == .bilinear ? evaluation.primaryA : evaluation.primaryB
        return String(format: "%d회차: 중앙 %.2f mm · 95%% %.2f mm · 2.5 mm 성공 %.1f%% · 정상 표시 %.1f%%",
                      evaluation.testPass, m.medianRadialErrorMM, m.p95RadialErrorMM,
                      100*m.successWithin2p5MM, 100*m.acceptedDisplayRate)
    }

    @ViewBuilder private var evaluationCard: some View {
        if tester.isJoint {
            VStack(alignment: .leading, spacing: 8) {
                Text("접촉·공중 구분 시험").font(.headline)
                Text("● 청록색: 접촉 추정 · 0 mm").foregroundStyle(.teal)
                Text("● 보라색: 공중 추정 · 3 mm").foregroundStyle(.purple)
                Text("◯ 주황색: 위치 또는 접촉·공중 구분이 불확실함").foregroundStyle(.orange)
                Text("0 mm의 1+3회차와 3 mm의 1회차를 함께 비교합니다. 같은 점에서 높이만 바꾸어 색이 바뀌는지 확인하세요. 독립적인 공중 반복 검증은 아직 없습니다.")
                    .font(.subheadline)
            }.padding(16).background(.teal.opacity(0.06), in: RoundedRectangle(cornerRadius: 14))
        } else if let entry = tester.selectedEntry {
            VStack(alignment: .leading, spacing: 8) {
                Text("학습에 쓰지 않은 회차의 정지점 평가").font(.headline)
                let held = entry.evaluations.filter { $0.role == "held_out_pass" }
                if held.isEmpty {
                    Text("선택한 모델은 별도 시험 회차가 없어 독립 정확도를 아직 모릅니다. 아래 학습 자료 재생 수치는 참고용입니다.")
                        .foregroundStyle(.orange)
                } else {
                    ForEach(held, id: \.testPass) { e in Text(metricLine(e)).font(.subheadline.monospacedDigit()) }
                }
                Text("각 시험은 273점. 성공률은 정상 표시되면서 2.5 mm 이내인 점의 비율입니다. 자유 이동·필기 정확도와는 다릅니다.")
                    .font(.footnote).foregroundStyle(.secondary)
                DisclosureGroup("학습에 사용한 자료 재생 · 독립 평가 아님") {
                    ForEach(entry.evaluations.filter { $0.role == "training_replay" }, id: \.testPass) { e in
                        Text(metricLine(e)).font(.footnote.monospacedDigit())
                    }
                }.font(.footnote)
            }.padding(16).background(.teal.opacity(0.06), in: RoundedRectangle(cornerRadius: 14))
        }
    }

    @ViewBuilder private var comparisonCard: some View {
        if tester.isJoint {
            VStack(alignment: .leading, spacing: 10) {
                Text("같은 순간의 A / B / C 비교").font(.headline)
                Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 8) {
                    GridRow { Text("모델"); Text("접촉 판정"); Text("x · y (mm)") }.font(.caption)
                    ForEach(0..<tester.comparison.count, id: \.self) { index in
                        let item = tester.comparison[index]
                        GridRow {
                            Text(item.0).bold()
                            Text(item.2?.title ?? "배경·센서 대기")
                                .foregroundStyle(item.2 == .air ? Color.purple : item.2 == .contact ? Color.teal : Color.orange)
                            if let e = item.1, e.showCandidate {
                                Text("\(e.point.x*50, specifier: "%.1f") · \(e.point.y*30, specifier: "%.1f")").monospacedDigit()
                            } else { Text("—") }
                        }
                    }
                }
                Text("위 선택은 지도·궤적 표시만 바꿉니다. 세 결과는 같은 입력으로 함께 계산·저장됩니다.").font(.footnote).foregroundStyle(.secondary)
            }.padding(16).background(.background, in: RoundedRectangle(cornerRadius: 14))
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(printed == nil ? "격자 내부 실시간 테스트" : "스윗 스팟 · 273점 실시간 테스트").font(.largeTitle.bold())
                    Text("테스트 모드").font(.headline)
                    Picker("테스트 모드", selection: Binding(get: { tester.conditionID }, set: { tester.selectCondition($0) })) {
                        Text("통합 · 0 / 3 mm").tag(JointHeightProjector.id)
                        ForEach(tester.library?.conditions ?? []) { condition in
                            Text(condition.title).tag(condition.id)
                        }
                    }.pickerStyle(.segmented)
                        .disabled(tester.calibrating || collector.sessionOpen || collector.isClosing)
                    Text(tester.isJoint ? "현재 높이를 선택하지 않고 자력계로 위치와 접촉·공중 후보를 함께 추정합니다. 0 mm와 3 mm 사이를 오가며 시험하세요." : "선택한 높이를 장치에서 직접 맞춰 주세요. 이 단일 높이 모드에서는 접촉 여부를 판정하지 않습니다.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    if let entries = tester.selectedCondition?.entries, entries.count > 1 {
                        Text("학습에 사용한 회차").font(.headline)
                        Picker("학습 회차 조합", selection: Binding(get: { tester.selectedCombination }, set: { tester.selectCombination($0) })) {
                            ForEach(entries) { entry in Text(entry.title).tag(entry.id) }
                        }.pickerStyle(.segmented)
                            .disabled(tester.calibrating || collector.sessionOpen || collector.isClosing)
                    } else if tester.isJoint {
                        Text("0 mm: 1+3회차  ·  3 mm: 1회차").font(.headline)
                    } else {
                        Text("3 mm 공중 · 1회차 273점 모델").font(.headline).foregroundStyle(.teal)
                    }
                    Picker("위치 추정 모델", selection: $tester.selectedMethod) {
                        Text(GridMappingMethod.bilinear.rawValue).tag(GridMappingMethod.bilinear)
                        Text(GridMappingMethod.neighbors.rawValue).tag(GridMappingMethod.neighbors).disabled(tester.knnModel == nil)
                        if tester.isJoint {
                            Text(GridMappingMethod.neural.rawValue).tag(GridMappingMethod.neural).disabled(tester.neuralBundle == nil)
                        }
                    }.pickerStyle(.segmented)
                    Text(tester.isJoint ? tester.selectedMethod.explanation : tester.selectedMethod == .bilinear ? "A: 각 위치의 반복값을 대표값으로 합친 보간 지도" : "B: 같은 위치의 여러 자력계 패턴을 유지하는 k-NN 회귀")
                        .font(.headline)
                    if tester.isJoint, let error = tester.neuralLoadError {
                        Text("C 모델을 읽지 못했습니다: \(error). 기존 A/B는 사용할 수 있습니다.").foregroundStyle(.orange)
                    }
                    Text(tester.isJoint ? "배경을 한 번 맞춘 뒤 높이만 바꾸세요. A/B/C는 같은 입력으로 함께 계산됩니다. 테스트 모드를 바꾸면 배경을 다시 맞춥니다." : "같은 높이 조건에서는 배경을 한 번 맞춰 A/B와 회차 조합을 비교합니다. 높이 조건을 바꾸면 배경을 다시 맞춥니다. A/B는 같은 입력으로 함께 계산됩니다.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    if tester.isJoint {
                        Text("21열 × 13행 · 50 × 30 mm · 접촉 546회 + 공중 273회 배치").font(.subheadline)
                    } else if let printed {
                        Text("21열 × 13행 · 50 × 30 mm · 사용 회차 \(printed.passes.map(String.init).joined(separator: ", "))")
                            .font(.headline).foregroundStyle(.teal)
                        Text("273개 위치 × \(printed.passes.count)회 = \(273 * printed.passes.count)번의 배치로 학습했습니다.")
                            .foregroundStyle(.secondary)
                    } else {
                        Text("\(gridColumns)×\(gridRows) 정지점 지도입니다. 점 사이 위치는 보간으로 추정합니다.").foregroundStyle(.secondary)
                    }
                    if printed == nil, let model = tester.model, let included = model.movementIncludedRows, !included.isEmpty {
                        Text("학습점 \(model.trainingTrialIDs.count)개 · \(included.map(String.init).joined(separator: ", "))행의 움직임 경고를 보존한 시험 모델입니다.")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                    if let model = tester.model, !model.excludedRows.isEmpty {
                        Text("학습에 사용한 점 \(model.trainingTrialIDs.count)개 · \(model.excludedRows.map(String.init).joined(separator: ", "))행은 iPad 움직임 경고로 제외했습니다. 이 줄은 주변 줄에서 보간하므로 오차가 더 클 수 있습니다.")
                            .font(.subheadline).foregroundStyle(.orange)
                    }
                    evaluationCard
                    VStack(alignment: .leading, spacing: 10) {
                        Text(tester.isJoint ? "① 펜을 멀리  ② 배경 맞추기  ③ 같은 점에서 0 ↔ 3 mm" : printed?.pose.tipContact == false ? "① 펜을 멀리  ② 배경 맞추기  ③ 높이 3 mm로 이동" : "① 펜을 멀리  ② 배경 맞추기  ③ 책상에 대고 이동").font(.headline)
                        Text("iPad·종이·스탠드·케이블을 수집 때와 같은 배치로 유지하세요.")
                        Text(tester.isJoint ? "φ=0° · θ=90° · α=0° 유지 · 높이만 0 / 3 mm로 조절" : printed?.pose.summary ?? "펜은 책상에 수직, 로고는 왼쪽입니다.").font(.headline)
                        if let printed, let min = printed.ipadInclinationRange.first, let max = printed.ipadInclinationRange.last {
                            Text("수집 때 iPad 경사 \(min, specifier: "%.1f")–\(max, specifier: "%.1f")° · 현재 \(collector.ipadInclinationDegrees.map { String(format: "%.1f°", $0) } ?? "수신 대기")")
                                .font(.footnote.monospacedDigit())
                        }
                        Button(tester.calibrating ? "배경 측정 중… \(Int(ceil(tester.remaining)))초" : "펜·홀더를 멀리 두었음 · 배경 맞추기") { tester.calibrate() }
                            .buttonStyle(.borderedProminent).controlSize(.large)
                            .disabled(!collector.sensorFresh || collector.sessionOpen || collector.isClosing || tester.calibrating || tester.model == nil)
                        if collector.sessionOpen { Text("수집을 저장·종료한 뒤 테스트하세요.").foregroundStyle(.orange) }
                        if !collector.sensorFresh { Text("자력계 수신 대기 중입니다.").foregroundStyle(.orange) }
                        Text("준비 \(Int(tester.calibrationSettle))초 + 배경 \(Int(tester.calibrationCapture))초").font(.footnote)
                        if tester.baseline != nil {
                            Text("배경 측정 후 \(tester.baselineAge, specifier: "%.0f")초 · 약 1분마다 다시 맞춰 주세요. 1분이 지나도 중단되지 않습니다.")
                                .font(.footnote).foregroundStyle(tester.baselineAge > 60 ? .orange : .secondary)
                        }
                    }.padding(18).background(.background, in: RoundedRectangle(cornerRadius: 18))
                    HStack {
                        Picker("따라 그릴 안내선", selection: $tester.guide) {
                            ForEach(GridGuide.options(columns: gridColumns, rows: gridRows)) { Text($0.title).tag($0) }
                        }.pickerStyle(.menu)
                        Spacer()
                        Button("궤적 지우기") { tester.clearTrail() }.buttonStyle(.bordered)
                    }
                    Text(tester.guide == .free ? "가운데에 놓고 자유롭게 움직여 보세요. 안내선은 현재 \(gridColumns)열 × \(gridRows)행 도면 기준입니다." : "회색 굵은 선을 편한 속도로 한 번 왕복하세요. 끝점에서 잠깐 멈춰도 됩니다.")
                        .font(.subheadline)
                    GridLiveCanvas(estimate: tester.estimate, trail: tester.trail, guide: tester.guide,
                                   aspect: tester.model?.aspect ?? 1.5, gridColumns: gridColumns, gridRows: gridRows,
                                   pointColor: tester.displayColor).frame(height: 380)
                    Text(tester.displayStatus).font(.headline)
                    if tester.selectedMethod == .neural, let c = tester.neuralEstimate {
                        Text(c.state.title).font(.title2.bold()).foregroundStyle(c.accepted ? tester.displayColor : .orange)
                        Text("C 접촉 점수 \(c.contactScore, specifier: "%.3f") · 0은 공중 쪽, 1은 접촉 쪽 · 정확도 확률이 아닙니다.")
                            .font(.subheadline.monospacedDigit())
                        Text("학습 신호까지 거리 \(c.supportDistanceUT, specifier: "%.2f") / 기준 \(c.supportLimitUT, specifier: "%.2f") µT · 점수 0.35~0.65 사이면 판정 보류")
                            .font(.footnote.monospacedDigit())
                    }
                    if tester.isJoint, let joint = tester.jointEstimate {
                        Text(joint.state.title).font(.title2.bold()).foregroundStyle(joint.estimate.accepted ? tester.displayColor : .orange)
                        Text("모델과의 차이 · 접촉 \(joint.contact.residual, specifier: "%.2f") µT / 공중 \(joint.air.residual, specifier: "%.2f") µT · 두 후보 차이 \(joint.gapUT, specifier: "%.2f") µT")
                            .font(.footnote.monospacedDigit())
                    }
                    if let e = tester.estimate, e.showCandidate {
                        Text("왼쪽에서 \(e.point.x*100, specifier: "%.0f")% · 위에서 \(e.point.y*100, specifier: "%.0f")%")
                            .font(.title2.monospacedDigit()).foregroundStyle(e.accepted ? tester.displayColor : .orange)
                        if let printed {
                            Text("도면 기준 추정 x \(e.point.x*printed.widthMM, specifier: "%.1f") mm · y \(e.point.y*printed.heightMM, specifier: "%.1f") mm")
                                .font(.subheadline.monospacedDigit())
                        }
                        if tester.selectedMethod != .neural {
                            Text("자기장 차이 \(e.residual, specifier: "%.1f") / 기준 \(e.limit, specifier: "%.1f") µT · 떨어진 다른 후보의 차이 \(e.otherLocationResidual, specifier: "%.1f") µT")
                                .font(.footnote.monospacedDigit())
                        }
                    }
                    comparisonCard
                    Text(tester.isJoint ? "● 청록: 접촉 추정 · ● 보라: 3 mm 공중 추정 · ◯ 주황: 판정 보류\n궤적은 최근 8초이며 접촉 상태가 바뀌거나 판정을 보류하면 선을 끊습니다. 회색 안내선은 추정에 사용하지 않습니다." : "● 청록색: 표시 기준을 통과한 추정점 · ◯ 주황색: 불확실한 후보\n궤적은 최근 8초의 청록색 점만 연결합니다. 회색 안내선은 추정에 사용하지 않습니다. 선 위에 붙어 보이는지 직접 확인해 주세요.")
                        .font(.footnote).foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 10) {
                        if printed != nil {
                            Text(tester.isJoint ? "같은 점과 경로에서 A/B/C 비교" : "같은 점과 경로에서 A/B 비교").font(.headline)
                            if tester.isJoint {
                                Text("중앙과 네 모서리에서 펜촉의 수평 위치를 유지하며 0 → 3 → 0 mm로 바꿔 보세요. 색이 맞는지와 높이를 바꿀 때 위치가 튀는지를 A/B/C 각각 비교하세요. 움직이는 중간 높이는 아직 학습하지 않았습니다.")
                            } else if printed?.pose.tipContact == false {
                                Text("φ=0°·θ=90°·α=0°를 유지하고 펜촉을 표식의 수직 위 3 mm에 놓으세요. 같은 점과 선에서 A/B를 전환하며 흔들림·점프·주황색 후보를 비교하세요. 3 mm의 첫 모델이며 반복 수집 검증은 아직 없습니다.")
                            } else {
                                Text("같은 자세와 경로에서 7개 회차 조합의 A/B를 비교하세요. 고정점의 흔들림, 선을 따라갈 때의 점프, 주황색 후보를 비교하세요.")
                            }
                            Text("자유 이동에는 정답 좌표가 없어 자동 정확도 점수로 사용하지 않습니다.").font(.footnote)
                            Button("273점 수집으로 이동") { collectPrinted() }
                                .buttonStyle(.bordered).disabled(collector.sessionOpen || collector.isClosing || tester.calibrating)
                            if let included = tester.model?.movementIncludedRows, !included.isEmpty {
                                Text("수집 중 이동·준비 구간의 기기 움직임이 기록된 \(included.map(String.init).joined(separator: ", "))행을 검토 후 시험에 포함했습니다. 정지 측정 중 움직임은 없었지만 실제 배치 변화가 없었다고 보장할 수는 없습니다.")
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                    }.padding(18).background(.teal.opacity(0.06), in: RoundedRectangle(cornerRadius: 18))
                    Text(tester.logStatus).font(.footnote)
                    HStack {
                        Button("기록 공유본 만들기 (선택)") { tester.shareSnapshot() }.buttonStyle(.bordered)
                        if let url = tester.exportURL { ShareLink("CSV 공유", item: url) }
                    }
                    Text(tester.isJoint ? "A/B는 높이별 모델을 비교하고 C는 두 높이를 공동 학습합니다. 모두 자력계로 접촉을 추정하는 실험 기능입니다. 색이 틀릴 수 있고, 0/3 mm 외 높이와 다른 자세는 검증하지 않았습니다. 실제 펜의 기울기·회전은 측정하지 않습니다. iPad가 움직이거나 센서가 끊기면 배경을 다시 맞춥니다." : "선택한 자세·높이를 유지하는 위치 추정 모델입니다. 실제 펜의 기울기·회전·접촉 여부는 측정하지 않습니다. 높이가 달라도 점이 표시될 수 있습니다. 펜을 이동 배치한 뒤 궤적을 지우고 테스트하세요. iPad가 움직이거나 센서가 끊기면 배경을 다시 맞춥니다.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(26).frame(maxWidth: 1000).frame(maxWidth: .infinity)
            }.background(Color(uiColor: .systemGroupedBackground)).navigationTitle("MagAir Research · A/B/C 테스트 1.22")
                .navigationBarTitleDisplayMode(.inline)
        }
        .onAppear { tester.active = !collector.sessionOpen; UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear {
            tester.active = false; tester.invalidate("배경을 다시 맞추고 테스트하세요")
            if !collector.sessionOpen { UIApplication.shared.isIdleTimerDisabled = false }
        }
        .onChange(of: collector.sessionOpen) { _, open in
            tester.active = !open
            if open { tester.invalidate("수집 세션이 열렸습니다") }
        }
        .onChange(of: tester.guide) { _, _ in tester.clearTrail() }
    }
}

struct GridLiveCanvas: View {
    var estimate: GridEstimate?
    var trail: [GridTrailPoint]
    var guide: GridGuide
    var aspect: Double
    var gridSize: Int = 5
    var gridColumns: Int? = nil
    var gridRows: Int? = nil
    var pointColor: Color = .teal
    var columns: Int { gridColumns ?? gridSize }
    var rows: Int { gridRows ?? gridSize }
    var body: some View {
        GeometryReader { geo in
            Canvas { context, _ in
                let w = min(geo.size.width-110, (geo.size.height-90)*aspect)
                let r = CGRect(x: (geo.size.width-w)/2, y: 45, width: w, height: w/aspect)
                func p(_ point: Point2D) -> CGPoint { .init(x: r.minX+point.x*r.width, y: r.minY+point.y*r.height) }
                context.draw(Text("위 · iPad 쪽").font(.headline), at: .init(x: r.midX,y: 14))
                context.draw(Text("아래 · 사용자 쪽").font(.headline), at: .init(x: r.midX,y: r.maxY+25))
                for i in 0..<rows {
                    let s = Double(i)/Double(rows-1)
                    var h = Path(); h.move(to: p(.init(x: 0,y: s))); h.addLine(to: p(.init(x: 1,y: s)))
                    context.stroke(h, with: .color(.gray.opacity(0.25)), lineWidth: 1)
                    context.draw(Text("\(i+1)행").font(.caption2), at: .init(x: r.minX-27,y: r.minY+s*r.height))
                    for j in 0..<columns {
                        let q = p(.init(x: Double(j)/Double(columns-1),y: s))
                        context.fill(Path(ellipseIn: CGRect(x: q.x-3,y: q.y-3,width: 6,height: 6)), with: .color(.gray.opacity(0.6)))
                    }
                }
                for i in 0..<columns {
                    let s = Double(i)/Double(columns-1)
                    var v = Path(); v.move(to: p(.init(x: s,y: 0))); v.addLine(to: p(.init(x: s,y: 1)))
                    context.stroke(v, with: .color(.gray.opacity(0.25)), lineWidth: 1)
                    context.draw(Text(columns > 9 ? "\(i+1)" : "\(i+1)열").font(.caption2), at: .init(x: r.minX+s*r.width,y: r.minY-14))
                }
                if columns == 21 { context.stroke(Path(r), with: .color(.red), lineWidth: 1.5) }
                if let first = guide.endpoints.first, let last = guide.endpoints.last {
                    var line = Path(); line.move(to: p(first)); line.addLine(to: p(last))
                    context.stroke(line, with: .color(.gray.opacity(0.55)), style: StrokeStyle(lineWidth: 5,dash: [8,5]))
                }
                for (i, q) in trail.enumerated() where i > 0 && !q.beginsSegment {
                    var segment = Path(); segment.move(to: p(trail[i-1].point)); segment.addLine(to: p(q.point))
                    let color: Color = q.state == .air ? .purple : .teal
                    context.stroke(segment, with: .color(color.opacity(0.65)), lineWidth: 3)
                }
                if let e = estimate, e.showCandidate {
                    let q = p(e.point), circle = Path(ellipseIn: CGRect(x: q.x-9,y: q.y-9,width: 18,height: 18))
                    if e.accepted { context.fill(circle, with: .color(pointColor)) }
                    else { context.stroke(circle, with: .color(.orange),lineWidth: 3) }
                }
            }
        }.background(.background,in: RoundedRectangle(cornerRadius: 18))
            .accessibilityLabel(estimate.map { "추정 위치 왼쪽에서 \(Int($0.point.x*100))퍼센트, 위에서 \(Int($0.point.y*100))퍼센트" } ?? "격자 지도 · 추정 위치 없음")
    }
}
