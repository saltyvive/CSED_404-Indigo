import SwiftUI
import Combine

final class GridLiveTester: ObservableObject {
    @Published var model: GridLiveModel?
    @Published var baseline: [Double]?
    @Published var calibrating = false
    @Published var remaining = 5.0
    @Published var status = "펜을 멀리 두고 배경을 맞추세요"
    @Published var estimate: GridEstimate?
    @Published var exportURL: URL?
    @Published var logStatus = "배경을 맞추면 테스트 기록이 자동 저장됩니다"
    @Published var baselineAge = 0.0
    @Published var guide: GridGuide = .free
    @Published var trail: [GridTrailPoint] = []
    private var lastAcceptedTime: Double?

    func clearTrail() { trail = []; lastAcceptedTime = nil }

    var active = false
    private var projector: GridProjector?
    private var calibrationStart = 0.0
    private var calibrationSamples: [(Double, [Double])] = []
    private var baselineTime = 0.0
    private var recent: [(Double, [Double])] = []
    private var lastDisplay = 0.0
    private var lastSensorTime = 0.0
    private var logURL: URL?
    private var handle: FileHandle?
    private let io = DispatchQueue(label: "MagAir.gridLive.log")
    private var lastSync = 0.0

    init() {
        do {
            guard let url = Bundle.main.url(forResource: "grid_model", withExtension: "json") else {
                status = "격자 학습 모델을 찾을 수 없습니다"; return
            }
            let loaded = try JSONDecoder().decode(GridLiveModel.self, from: Data(contentsOf: url))
            guard let projector = GridProjector(model: loaded) else { status = "격자 학습 모델 형식 오류"; return }
            self.model = loaded; self.projector = projector
        } catch { status = "모델 읽기 실패: \(error.localizedDescription)" }
    }

    func calibrate() {
        guard active, model != nil else { return }
        closeLog(reason: "background_recalibration")
        clearTrail()
        baseline = nil; estimate = nil; recent = []; calibrationSamples = []; exportURL = nil
        calibrationStart = ProcessInfo.processInfo.systemUptime
        calibrating = true; remaining = 5; baselineAge = 0
        status = "준비 2초 · 펜슬을 충분히 멀리 치우세요"
    }

    func invalidate(_ message: String) {
        clearTrail()
        baseline = nil; estimate = nil; calibrating = false; recent = []
        closeLog(reason: message); status = message
    }

    func deviceMoved() {
        guard active, baseline != nil || calibrating else { return }
        if calibrating && ProcessInfo.processInfo.systemUptime - calibrationStart < 2 { return }
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
            remaining = max(0, 5 - elapsed)
            status = elapsed < 2 ? "준비 중 · 펜슬을 충분히 멀리" : "배경 측정 중 · 배치를 유지하세요"
            if elapsed >= 2 && elapsed < 5 { calibrationSamples.append((timestamp, field)) }
            if elapsed >= 5 {
                calibrating = false
                guard calibrationSamples.count >= 100,
                      let first = calibrationSamples.first, let last = calibrationSamples.last,
                      last.0 - first.0 >= 2.5,
                      zip(calibrationSamples, calibrationSamples.dropFirst()).allSatisfy({ $1.0 - $0.0 <= 0.15 }) else {
                    status = "배경 샘플 부족 또는 수신 공백 · 다시 시도하세요"; return
                }
                let b = (0..<3).map { axis in medianValue(calibrationSamples.map { $0.1[axis] }) }
                let noise = sqrt(calibrationSamples.reduce(0.0) { sum, sample in
                    sum + zip(sample.1, b).reduce(0.0) { $0 + pow($1.0 - $1.1, 2) }
                } / Double(calibrationSamples.count))
                guard noise < 3 else { status = "배경이 불안정합니다 · 펜을 치우고 다시 시도하세요"; return }
                baseline = b; baselineTime = timestamp
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
        guard let result = projector.project(filtered) else { estimate = nil; return }
        estimate = result; status = result.reason
        var columns = [number(timestamp), number(Date().timeIntervalSince1970)]
        columns += field.map(number)
        columns += baseline.map(number)
        columns += filtered.map(number)
        columns += [number(result.point.x), number(result.point.y), number(result.residual)]
        columns += [number(result.limit), number(result.signal), result.accepted ? "1" : "0", result.showCandidate ? "1" : "0"]
        columns += [result.ambiguous ? "1" : "0", number(baselineAge), number(result.otherLocationResidual), guide.rawValue]
        if result.accepted {
            let begins = lastAcceptedTime.map { timestamp-$0 > 0.3 } ?? true
            trail.append(GridTrailPoint(time: timestamp, point: result.point, beginsSegment: begins))
            lastAcceptedTime = timestamp
        } else { lastAcceptedTime = nil }
        trail.removeAll { timestamp-$0.time > 8 }
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

    private func startLog(baseline: [Double], noise: Double) {
        do {
            let folder = SessionStore.root.deletingLastPathComponent().appendingPathComponent("MagAirGridLiveTests")
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
            let url = folder.appendingPathComponent("GridLive-\(stamp)-\(UUID().uuidString.prefix(6)).csv")
            let header = ["timestamp_s", "callback_unix_s", "bx_uT", "by_uT", "bz_uT", "baseline_x_uT", "baseline_y_uT", "baseline_z_uT",
                          "filtered_delta_x_uT", "filtered_delta_y_uT", "filtered_delta_z_uT", "estimated_x", "estimated_y",
                          "residual_uT", "residual_limit_uT", "signal_uT", "accepted", "candidate_shown", "ambiguous", "baseline_age_s",
                          "distant_location_residual_uT", "display_guide_only"]
            try Data(csvRow(header).utf8).write(to: url, options: .atomic)
            if let model {
                try JSONEncoder().encode(model).write(to: url.deletingPathExtension().appendingPathExtension("model.json"), options: .atomic)
            }
            let metadata: [String: Any] = ["baselineUT": baseline, "baselineNoiseUT": noise, "baselineTimestamp": baselineTime,
                                         "calibrationSamples": calibrationSamples.map { [$0.0] + $0.1 },
                                         "filter": "causal component median, 0.12 seconds; no coordinate smoothing or prediction",
                                         "scope": "Two-dimensional search over the entire grid surface. display_guide_only never constrains prediction and is not timestamped ground truth. No Pencil IMU or measured contact."]
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
}

struct GridLiveView: View {
    @ObservedObject var collector: Collector
    @ObservedObject var tester: GridLiveTester
    var collect: (EdgeScenario) -> Void
    var gridSize: Int { tester.model?.xKnots.count == 9 ? 9 : 5 }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("격자 내부 실시간 테스트").font(.largeTitle.bold())
                    Text(gridSize == 9 ? "9×9 반복 정지점으로 만든 지도입니다. 점 사이 위치는 보간으로 추정합니다. 먼저 자유 테스트하고, 이후 새 자료로 검증합니다." : "현재는 11번의 기존 5×5 지도입니다. 9×9 자료 수집만으로 자동 갱신되지는 않습니다. 16A–18C 완료 후 새 지도를 제작·반영합니다.")
                        .foregroundStyle(.secondary)
                    if let model = tester.model, let included = model.movementIncludedRows, !included.isEmpty {
                        Text("학습점 \(model.trainingTrialIDs.count)개 · \(included.map(String.init).joined(separator: ", "))행도 포함했습니다. 사용자 요청으로 움직임 경고가 있는 행을 포함한 시험 모델이며, 경고 기록은 보존합니다.")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                    if let model = tester.model, !model.excludedRows.isEmpty {
                        Text("학습에 사용한 점 \(model.trainingTrialIDs.count)개 · \(model.excludedRows.map(String.init).joined(separator: ", "))행은 iPad 움직임 경고로 제외했습니다. 이 줄은 주변 줄에서 보간하므로 오차가 더 클 수 있습니다.")
                            .font(.subheadline).foregroundStyle(.orange)
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        Text("① 펜을 멀리  ② 배경 맞추기  ③ 책상에 대고 이동").font(.headline)
                        Text("iPad·스탠드·케이블을 같은 배치로 유지하세요. 펜은 책상에 수직, 로고는 왼쪽입니다.")
                        Button(tester.calibrating ? "배경 측정 중… \(Int(ceil(tester.remaining)))초" : "펜을 멀리 두었음 · 배경 맞추기 5초") { tester.calibrate() }
                            .buttonStyle(.borderedProminent).controlSize(.large)
                            .disabled(!collector.sensorFresh || collector.sessionOpen || collector.isClosing || tester.calibrating || tester.model == nil)
                        if collector.sessionOpen { Text("수집을 저장·종료한 뒤 테스트하세요.").foregroundStyle(.orange) }
                        if !collector.sensorFresh { Text("자력계 수신 대기 중입니다.").foregroundStyle(.orange) }
                        if tester.baseline != nil {
                            Text("배경 측정 후 \(tester.baselineAge, specifier: "%.0f")초 · 약 1분마다 다시 맞춰 주세요. 1분이 지나도 중단되지 않습니다.")
                                .font(.footnote).foregroundStyle(tester.baselineAge > 60 ? .orange : .secondary)
                        }
                    }.padding(18).background(.background, in: RoundedRectangle(cornerRadius: 18))
                    HStack {
                        Picker("따라 그릴 안내선", selection: $tester.guide) {
                            ForEach(GridGuide.options(gridSize: gridSize)) { Text($0.title).tag($0) }
                        }.pickerStyle(.menu)
                        Spacer()
                        Button("궤적 지우기") { tester.clearTrail() }.buttonStyle(.bordered)
                    }
                    Text(tester.guide == .free ? "가운데에 놓고 자유롭게 움직여 보세요. 안내선은 현재 \(gridSize)×\(gridSize) 모델 기준입니다." : "회색 굵은 선을 편한 속도로 한 번 왕복하세요. 끝점에서 잠깐 멈춰도 됩니다.")
                        .font(.subheadline)
                    GridLiveCanvas(estimate: tester.estimate, trail: tester.trail, guide: tester.guide,
                                   aspect: tester.model?.aspect ?? 1.5, gridSize: gridSize).frame(height: 380)
                    Text(tester.status).font(.headline)
                    if let e = tester.estimate, e.showCandidate {
                        Text("왼쪽에서 \(e.point.x*100, specifier: "%.0f")% · 위에서 \(e.point.y*100, specifier: "%.0f")%")
                            .font(.title2.monospacedDigit()).foregroundStyle(e.accepted ? .teal : .orange)
                        Text("자기장 차이 \(e.residual, specifier: "%.1f") / 기준 \(e.limit, specifier: "%.1f") µT · 떨어진 다른 후보의 차이 \(e.otherLocationResidual, specifier: "%.1f") µT")
                            .font(.footnote.monospacedDigit())
                    }
                    Text("● 청록색: 표시 기준을 통과한 추정점 · ◯ 주황색: 불확실한 후보\n궤적은 최근 8초의 청록색 점만 연결합니다. 회색 안내선은 추정에 사용하지 않습니다. 선 위에 붙어 보이는지 직접 확인해 주세요.")
                        .font(.footnote).foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 10) {
                        Text("9×9 반복 학습 → 자유 테스트 → 별도 검증").font(.headline)
                        Text("81개 위치를 3회씩 모두 학습용으로 수집합니다. 16A부터 18C까지 9묶음을 마친 뒤 알려주세요. 14·15 이동 검증은 지금 진행하지 않아도 됩니다.")
                            .font(.subheadline)
                        HStack {
                            Button("9×9 학습 수집으로 이동") { collect(collector.nextDenseCollection) }
                        }.buttonStyle(.bordered).disabled(collector.sessionOpen || collector.isClosing || tester.calibrating)
                    }.padding(18).background(.teal.opacity(0.06), in: RoundedRectangle(cornerRadius: 18))
                    Text(tester.logStatus).font(.footnote)
                    HStack {
                        Button("기록 공유본 만들기 (선택)") { tester.shareSnapshot() }.buttonStyle(.bordered)
                        if let url = tester.exportURL { ShareLink("CSV 공유", item: url) }
                    }
                    Text("같은 자세·책상 접촉 조건의 초기 모델입니다. 펜의 기울기·축 회전·접촉 여부는 측정하지 않습니다. 펜을 들어 옮길 때 궤적이 생길 수 있으니 내려놓고 궤적을 지우세요. iPad가 움직이거나 센서가 끊기면 배경을 다시 맞춥니다.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(26).frame(maxWidth: 1000).frame(maxWidth: .infinity)
            }.background(Color(uiColor: .systemGroupedBackground)).navigationTitle("MagAir · 2차원 지도 1.12")
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
    var body: some View {
        GeometryReader { geo in
            Canvas { context, _ in
                let w = min(geo.size.width-110, (geo.size.height-90)*aspect)
                let r = CGRect(x: (geo.size.width-w)/2, y: 45, width: w, height: w/aspect)
                func p(_ point: Point2D) -> CGPoint { .init(x: r.minX+point.x*r.width, y: r.minY+point.y*r.height) }
                context.draw(Text("위 · iPad 쪽").font(.headline), at: .init(x: r.midX,y: 14))
                context.draw(Text("아래 · 사용자 쪽").font(.headline), at: .init(x: r.midX,y: r.maxY+25))
                for i in 0..<gridSize {
                    let s = Double(i)/Double(gridSize-1)
                    var h = Path(); h.move(to: p(.init(x: 0,y: s))); h.addLine(to: p(.init(x: 1,y: s)))
                    var v = Path(); v.move(to: p(.init(x: s,y: 0))); v.addLine(to: p(.init(x: s,y: 1)))
                    context.stroke(h, with: .color(.gray.opacity(0.25)), lineWidth: 1)
                    context.stroke(v, with: .color(.gray.opacity(0.25)), lineWidth: 1)
                    context.draw(Text("\(i+1)행").font(.caption), at: .init(x: r.minX-27,y: r.minY+s*r.height))
                    context.draw(Text("\(i+1)열").font(.caption), at: .init(x: r.minX+s*r.width,y: r.minY-14))
                    for j in 0..<gridSize {
                        let q = p(.init(x: Double(j)/Double(gridSize-1),y: s))
                        context.fill(Path(ellipseIn: CGRect(x: q.x-3,y: q.y-3,width: 6,height: 6)), with: .color(.gray.opacity(0.6)))
                    }
                }
                if let first = guide.endpoints.first, let last = guide.endpoints.last {
                    var line = Path(); line.move(to: p(first)); line.addLine(to: p(last))
                    context.stroke(line, with: .color(.gray.opacity(0.55)), style: StrokeStyle(lineWidth: 5,dash: [8,5]))
                }
                var path = Path()
                for (i, q) in trail.enumerated() {
                    if i == 0 || q.beginsSegment { path.move(to: p(q.point)) } else { path.addLine(to: p(q.point)) }
                }
                context.stroke(path, with: .color(.teal.opacity(0.65)), lineWidth: 3)
                if let e = estimate, e.showCandidate {
                    let q = p(e.point), circle = Path(ellipseIn: CGRect(x: q.x-9,y: q.y-9,width: 18,height: 18))
                    if e.accepted { context.fill(circle, with: .color(.teal)) }
                    else { context.stroke(circle, with: .color(.orange),lineWidth: 3) }
                }
            }
        }.background(.background,in: RoundedRectangle(cornerRadius: 18))
            .accessibilityLabel(estimate.map { "추정 위치 왼쪽에서 \(Int($0.point.x*100))퍼센트, 위에서 \(Int($0.point.y*100))퍼센트" } ?? "격자 지도 · 추정 위치 없음")
    }
}
