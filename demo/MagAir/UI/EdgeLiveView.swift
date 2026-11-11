import SwiftUI
import Combine

final class EdgeLiveTester: ObservableObject {
    @Published var model: EdgeLiveModel?
    @Published var baseline: [Double]?
    @Published var calibrating = false
    @Published var remaining = 5.0
    @Published var status = "펜을 멀리 두고 배경을 맞추세요"
    @Published var estimate: EdgeEstimate?
    @Published var exportURL: URL?
    @Published var logStatus = "배경을 맞추면 테스트 기록이 자동 저장됩니다"
    @Published var baselineAge = 0.0
    var active = false
    private var projector: EdgeProjector?
    private var calibrationStart = 0.0
    private var calibrationSamples: [(Double, [Double])] = []
    private var baselineTime = 0.0
    private var recent: [(Double, [Double])] = []
    private var lastDisplay = 0.0
    private var lastSensorTime = 0.0
    private var logURL: URL?
    private var handle: FileHandle?
    private let io = DispatchQueue(label: "MagAir.edgeLive.log")
    private var lastSync = 0.0

    init() {
        do {
            guard let url = Bundle.main.url(forResource: "edge_model", withExtension: "json") else {
                status = "변 학습 모델을 찾을 수 없습니다"; return
            }
            let loaded = try JSONDecoder().decode(EdgeLiveModel.self, from: Data(contentsOf: url))
            guard let projector = EdgeProjector(model: loaded) else { status = "변 학습 모델 형식 오류"; return }
            self.model = loaded; self.projector = projector
        } catch { status = "모델 읽기 실패: \(error.localizedDescription)" }
    }

    func calibrate() {
        guard active, model != nil else { return }
        closeLog(reason: "background_recalibration")
        baseline = nil; estimate = nil; recent = []; calibrationSamples = []; exportURL = nil
        calibrationStart = ProcessInfo.processInfo.systemUptime
        calibrating = true; remaining = 5; baselineAge = 0
        status = "준비 2초 · 펜슬을 충분히 멀리 치우세요"
    }

    func invalidate(_ message: String) {
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
                status = "배경 준비 완료 · 위쪽·아래쪽·왼쪽·오른쪽 변을 번갈아 움직여 보세요"
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
        columns += [result.edge.rawValue, number(result.parameter), number(result.point.x), number(result.point.y), number(result.residual)]
        columns += [number(result.limit), number(result.signal), result.accepted ? "1" : "0", result.showCandidate ? "1" : "0"]
        columns += [result.ambiguous ? "1" : "0", number(baselineAge), result.otherEdge?.rawValue ?? ""]
        columns.append(result.otherEdgeResidual.map(number) ?? "")
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
            let folder = SessionStore.root.deletingLastPathComponent().appendingPathComponent("MagAirEdgeLiveTests")
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
            let url = folder.appendingPathComponent("EdgeLive-\(stamp)-\(UUID().uuidString.prefix(6)).csv")
            let header = ["timestamp_s", "callback_unix_s", "bx_uT", "by_uT", "bz_uT", "baseline_x_uT", "baseline_y_uT", "baseline_z_uT",
                          "filtered_delta_x_uT", "filtered_delta_y_uT", "filtered_delta_z_uT", "estimated_edge", "estimated_parameter",
                          "estimated_x", "estimated_y", "residual_uT", "residual_limit_uT", "signal_uT", "accepted", "candidate_shown", "ambiguous", "baseline_age_s",
                          "other_edge", "other_edge_residual_uT"]
            try Data(csvRow(header).utf8).write(to: url, options: .atomic)
            if let model {
                try JSONEncoder().encode(model).write(to: url.deletingPathExtension().appendingPathExtension("model.json"), options: .atomic)
            }
            let metadata: [String: Any] = ["baselineUT": baseline, "baselineNoiseUT": noise, "baselineTimestamp": baselineTime,
                                         "calibrationSamples": calibrationSamples.map { [$0.0] + $0.1 },
                                         "filter": "causal component median, 0.12 seconds; no coordinate smoothing or prediction",
                                         "scope": "One-dimensional candidates on trained edges only; no ground-truth coordinates or Pencil IMU."]
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

struct EdgeLiveView: View {
    @ObservedObject var collector: Collector
    @ObservedObject var tester: EdgeLiveTester
    var startValidation: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("네 변 실시간 테스트").font(.largeTitle.bold())
                    Text("01 위쪽·03 아래쪽·06 왼쪽·08 오른쪽의 각 5개 위치 × 2회로 만든 모델입니다. 센서값으로 네 변 중 어느 변인지와 그 변에서의 위치를 함께 추정합니다. 변은 자동으로 구분합니다.")
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 12) {
                        Text("① 같은 배치  ② 배경 맞추기  ③ 네 변을 번갈아 이동").font(.headline)
                        Text("펜 끝은 책상에 가볍게, 수직으로 세우고 로고는 왼쪽. iPad·스탠드·케이블·주변 물체를 수집 때와 같은 위치에 두세요.")
                        Text("위쪽·아래쪽은 좌우 왕복, 왼쪽·오른쪽은 위아래 왕복입니다. 각 변을 확인한 뒤 모서리를 거쳐 테두리를 이어 움직여 보세요. 사각형 내부와 공중은 아직 학습하지 않았습니다.")
                            .font(.subheadline).foregroundStyle(.secondary)
                        Button(tester.calibrating ? "배경 측정 중… \(Int(ceil(tester.remaining)))초" : "펜을 멀리 두었음 · 배경 맞추기 5초") { tester.calibrate() }
                            .buttonStyle(.borderedProminent).controlSize(.large)
                            .disabled(!collector.sensorFresh || collector.sessionOpen || collector.isClosing || tester.calibrating || tester.model == nil)
                        if collector.sessionOpen { Text("수집 세션을 저장·종료한 뒤 테스트하세요.").foregroundStyle(.orange) }
                        if !collector.sensorFresh { Text("자력계 수신 대기 중입니다.").foregroundStyle(.orange) }
                        if tester.baseline != nil {
                            Text("배경 측정 후 \(tester.baselineAge, specifier: "%.0f")초 · 약 1분마다 펜을 치우고 다시 맞춰 주세요. 1분이 지나도 자동 중단되지 않습니다.")
                                .font(.footnote).foregroundStyle(tester.baselineAge > 60 ? .orange : .secondary)
                        }
                    }.padding(20).background(.background, in: RoundedRectangle(cornerRadius: 18))
                    EdgeLiveCanvas(estimate: tester.estimate, aspect: tester.model?.aspect ?? 1.5,
                                   edges: tester.model?.curves.map(\.edge) ?? []).frame(height: 340)
                    VStack(alignment: .leading, spacing: 8) {
                        Text(tester.status).font(.headline)
                        if let e = tester.estimate, e.showCandidate {
                            Text("\(e.accepted ? "추정한 변" : "참고 후보 변"): \(e.edge.title)")
                                .font(.title2.bold()).foregroundStyle(e.accepted ? .teal : .orange)
                            Text("\(e.accepted ? "추정" : "참고 후보") 위치: \(e.edge == .left || e.edge == .right ? "위에서" : "왼쪽에서") \(e.parameter * 100, specifier: "%.1f")%")
                                .font(.title2.monospacedDigit()).foregroundStyle(e.accepted ? .teal : .orange)
                            Text("모델과 자기장 차이 \(e.residual, specifier: "%.1f") µT / 표시 기준 \(e.limit, specifier: "%.1f") µT")
                                .monospacedDigit()
                            if let other = e.otherEdge, let difference = e.otherEdgeResidual {
                                Text("두 번째 후보(\(other.title))의 자기장 차이: \(difference, specifier: "%.1f") µT")
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                        Text("● 청록색: 모델의 신호 범위 안  ·  ◯ 주황색: 맞지 않는 참고 후보\n색과 µT 차이는 위치 오차나 정확도 %가 아닙니다. 주황색 점은 잘 맞는 결과로 세지 않습니다.")
                            .font(.footnote).foregroundStyle(.secondary)
                        Text("네 모서리는 각각 두 변이 공유하는 위치입니다. 모서리 근처에서는 변 이름이 바뀔 수 있으니 점의 위치도 함께 보세요. 점을 모서리에 강제로 고정하지 않습니다.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        Text("다음 수집: 9×9 반복 학습 · 81점 × 3회").font(.headline)
                        Text("9×9 자료로 새 지도를 만든 뒤 ‘격자 내부 테스트’에서 자유롭게 확인합니다. 그다음 별도 검증을 진행합니다. 이 화면은 기존 네 변 모델입니다.")
                        Button("9×9 학습 수집으로 이동") { startValidation() }
                            .buttonStyle(.bordered).disabled(collector.sessionOpen || collector.isClosing || tester.calibrating)
                    }.padding(20).background(.teal.opacity(0.07), in: RoundedRectangle(cornerRadius: 18))
                    Text(tester.logStatus).font(.footnote)
                    HStack {
                        Button("기록 공유본 만들기 (선택)") { tester.shareSnapshot() }.buttonStyle(.bordered)
                        if let url = tester.exportURL { ShareLink("CSV 공유", item: url) }
                    }
                    Text("원시 자력계에서 새 배경을 빼고, 최근 0.12초의 중앙값을 사용합니다. 측정하지 않은 펜 위치를 속도로 채우지 않습니다. 펜슬의 IMU·기울기·접촉 여부는 이 화면에서 측정하지 않습니다.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(26).frame(maxWidth: 1000).frame(maxWidth: .infinity)
            }.background(Color(uiColor: .systemGroupedBackground)).navigationTitle("MagAir · 네 변 모델 1.11")
        }
        .onAppear {
            tester.active = !collector.sessionOpen
            UIApplication.shared.isIdleTimerDisabled = true
        }
        .onDisappear {
            tester.active = false; tester.invalidate("배경을 다시 맞추고 테스트하세요")
            if !collector.sessionOpen { UIApplication.shared.isIdleTimerDisabled = false }
        }
        .onChange(of: collector.sessionOpen) { _, open in
            tester.active = !open
            if open { tester.invalidate("수집 세션이 열렸습니다") }
        }
    }
}

struct EdgeLiveCanvas: View {
    var estimate: EdgeEstimate?
    var aspect: Double
    var edges: [StudyEdge]
    var body: some View {
        GeometryReader { geo in
            Canvas { context, _ in
                let width = min(geo.size.width - 170, (geo.size.height - 95) * aspect)
                let rect = CGRect(x: (geo.size.width - width)/2, y: 50, width: width, height: width/aspect)
                context.stroke(Path(rect), with: .color(.gray.opacity(0.25)), lineWidth: 2)
                context.draw(Text("위쪽 변 · iPad 쪽").font(.headline), at: .init(x: rect.midX, y: 18))
                context.draw(Text("사각형 내부는 아직 학습하지 않았습니다").font(.caption).foregroundColor(.secondary), at: .init(x: rect.midX, y: rect.midY))
                func point(_ p: Point2D) -> CGPoint { .init(x: rect.minX + p.x*rect.width, y: rect.minY + p.y*rect.height) }
                for edge in edges {
                    var line = Path(); line.move(to: point(edge.point(0))); line.addLine(to: point(edge.point(1)))
                    context.stroke(line, with: .color(.teal), lineWidth: 4)
                    for i in 0...4 {
                        let p = point(edge.point(Double(i)/4))
                        context.fill(Path(ellipseIn: .init(x: p.x-3, y: p.y-3, width: 6, height: 6)), with: .color(.teal))
                        let horizontal = edge == .top || edge == .bottom
                        let dx = horizontal ? 0.0 : (edge == .left ? -28.0 : 28.0)
                        let dy = horizontal ? (edge == .bottom ? -24.0 : 24.0) : 0.0
                        context.draw(Text("\(i*25)%").font(.caption), at: .init(x: p.x + dx, y: p.y + dy))
                    }
                }
                if let e = estimate, e.showCandidate {
                    let p = CGPoint(x: rect.minX + e.point.x*rect.width, y: rect.minY + e.point.y*rect.height)
                    let circle = Path(ellipseIn: .init(x: p.x-10, y: p.y-10, width: 20, height: 20))
                    if e.accepted { context.fill(circle, with: .color(.teal)) }
                    else { context.stroke(circle, with: .color(.orange), lineWidth: 3) }
                }
                context.draw(Text("아래쪽 변 · 사용자 쪽").font(.headline), at: .init(x: rect.midX, y: rect.maxY+22))
                if edges.contains(.left) {
                    context.draw(Text("왼쪽").font(.caption.bold()), at: .init(x: rect.minX-62, y: rect.midY-12))
                    context.draw(Text("위→아래").font(.caption2), at: .init(x: rect.minX-62, y: rect.midY+8))
                }
                if edges.contains(.right) {
                    context.draw(Text("오른쪽").font(.caption.bold()), at: .init(x: rect.maxX+62, y: rect.midY-12))
                    context.draw(Text("위→아래").font(.caption2), at: .init(x: rect.maxX+62, y: rect.midY+8))
                }
            }
        }.background(.background, in: RoundedRectangle(cornerRadius: 18))
            .accessibilityLabel(estimate.map { "\($0.accepted ? "추정" : "참고 후보"): \($0.edge.title), \(Int($0.parameter * 100))퍼센트" } ?? "네 변 지도 · 현재 추정 없음")
    }
}
