import SwiftUI
import Combine

struct LiveTrailPoint {
    var point: Point2D
    var segment: Int
}

final class LiveTester: ObservableObject {
    @Published var model: LiveModel?
    @Published var modeID = "surface"
    @Published var baseline: [Double]?
    @Published var calibrating = false
    @Published var calibrationRemaining = 5.0
    @Published var status = "펜을 멀리 두고 배경 맞추기를 시작하세요"
    @Published var point: Point2D?
    @Published var residual: Double?
    @Published var trail: [LiveTrailPoint] = []
    @Published var exportURL: URL?
    @Published var baselineShift: Double?
    private var calibrationStart = 0.0
    private var calibrationSamples: [[Double]] = []
    private var recent: [(Double, [Double])] = []
    private var lastDisplay = 0.0
    private var lastSensorTime = 0.0
    private var segment = 0
    private var logRows: [String] = []
    var active = false
    var currentMode: LiveMode? { model?.modes.first { $0.id == modeID } }

    init() {
        do {
            guard let url = Bundle.main.url(forResource: "live_model", withExtension: "json") else {
                status = "학습 모델을 찾을 수 없습니다"; return
            }
            let loaded = try JSONDecoder().decode(LiveModel.self, from: Data(contentsOf: url))
            guard loaded.isValid else { status = "학습 모델 형식이 올바르지 않습니다"; return }
            model = loaded
        } catch { status = "모델 읽기 실패: \(error.localizedDescription)" }
    }

    func calibrate() {
        guard model != nil else { return }
        baseline = nil; calibrationSamples = []; recent = []; point = nil; residual = nil
        calibrating = true; calibrationStart = ProcessInfo.processInfo.systemUptime; calibrationRemaining = 5
        status = "준비 2초 · 펜슬을 충분히 멀리 치우세요"; segment += 1
    }

    func changeMode() {
        point = nil; residual = nil; recent = []; segment += 1; trail = []
        status = baseline == nil ? "먼저 배경 맞추기를 해 주세요" : "선택한 높이와 자세로 펜을 움직이세요"
    }

    func invalidate(_ message: String) {
        guard baseline != nil || calibrating else { return }
        baseline = nil; calibrating = false; point = nil; residual = nil; recent = []
        segment += 1; status = message
    }

    func deviceMoved() {
        if calibrating && ProcessInfo.processInfo.systemUptime - calibrationStart < 2 { return }
        invalidate("iPad 움직임 감지 · 고정 상태를 확인하고 배경을 다시 맞추세요")
    }

    func checkStale(now: Double) {
        if active && (baseline != nil || calibrating) && now - lastSensorTime > 1.0 {
            invalidate("센서 수신이 끊겼습니다 · 배경을 다시 맞추세요")
        }
    }

    func receive(timestamp: Double, field: [Double]) {
        guard active, field.count == 3, field.allSatisfy(\.isFinite) else { return }
        lastSensorTime = timestamp
        if calibrating {
            let elapsed = timestamp - calibrationStart
            calibrationRemaining = max(0, 5-elapsed)
            if elapsed >= 2 && elapsed < 5 { calibrationSamples.append(field) }
            status = elapsed < 2 ? "준비 중 · 펜슬을 충분히 멀리" : "배경 측정 중 · iPad와 주변 물체를 고정"
            if elapsed >= 5 {
                calibrating = false
                guard calibrationSamples.count >= 100 else { status = "배경 샘플 부족 · 다시 시도하세요"; return }
                let b = (0..<3).map { axis in medianValue(calibrationSamples.map { $0[axis] }) }
                let noise = sqrt(calibrationSamples.reduce(0.0) { sum, v in
                    sum + zip(v, b).reduce(0.0) { $0 + pow($1.0 - $1.1, 2) }
                } / Double(calibrationSamples.count))
                guard noise < 3 else { status = "배경 측정 중 자기장이 변했습니다 · 펜을 치우고 다시 시도하세요"; return }
                baseline = b
                baselineShift = model.map { m in sqrt(zip(b, m.baselineReferenceUT).reduce(0.0) { $0 + pow($1.0 - $1.1, 2) }) }
                status = "배경 준비 완료 · 이제 사각형에서 펜을 움직이세요"
                calibrationSamples = []
            }
            return
        }
        guard let baseline, let mode = currentMode else { return }
        recent.append((timestamp, field)); recent.removeAll { timestamp - $0.0 > 0.12 }
        guard timestamp - lastDisplay >= 0.09, recent.count >= 3 else { return }
        lastDisplay = timestamp
        let filtered = (0..<3).map { axis in medianValue(recent.map { $0.1[axis] }) - baseline[axis] }
        guard let estimate = mode.project(filtered) else { point = nil; segment += 1; return }
        residual = estimate.residual; status = estimate.reason
        if estimate.accepted {
            point = estimate.point // Keep outside-margin values visible; no artificial clipping.
            trail.append(.init(point: estimate.point, segment: segment))
            if trail.count > 600 { trail.removeFirst(trail.count - 600) }
        } else { point = nil; segment += 1 }
        if logRows.count < 18000 {
            logRows.append(csvRow([number(timestamp), mode.id] + field.map(number) + baseline.map(number) + filtered.map(number) +
                                 [number(estimate.point.x), number(estimate.point.y), number(estimate.residual),
                                  estimate.accepted ? "1" : "0", estimate.reason]))
        }
    }

    func saveLog() {
        guard !logRows.isEmpty else { status = "저장할 테스트 결과가 없습니다"; return }
        do {
            let folder = SessionStore.root.deletingLastPathComponent().appendingPathComponent("MagAirLiveTests")
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
            let url = folder.appendingPathComponent("Live-\(stamp)-\(UUID().uuidString.prefix(6)).csv")
            let header = csvRow(["timestamp_s", "mode", "bx_uT", "by_uT", "bz_uT", "baseline_x_uT", "baseline_y_uT", "baseline_z_uT", "filtered_delta_x_uT", "filtered_delta_y_uT", "filtered_delta_z_uT", "estimated_x", "estimated_y", "residual_uT", "displayed", "status"])
            try Data((header + logRows.joined()).utf8).write(to: url, options: .atomic)
            if let model { try JSONEncoder().encode(model).write(to: url.deletingPathExtension().appendingPathExtension("model.json"), options: .atomic) }
            exportURL = url; logRows = []
        } catch { status = "테스트 저장 실패: \(error.localizedDescription)" }
    }
}

struct LiveTestView: View {
    @ObservedObject var collector: Collector
    @ObservedObject var tester: LiveTester
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("실시간 위치 테스트").font(.largeTitle.bold())
                        Text("수집한 네 모서리의 자기장으로 위치를 추정합니다. 사각형 내부·글씨 정확도는 아직 검증되지 않았습니다.")
                            .foregroundStyle(.secondary)
                    }
                    if collector.sessionOpen {
                        Label("데이터 수집 세션을 종료한 뒤 테스트하세요", systemImage: "info.circle").foregroundStyle(.orange)
                    }
                    VStack(alignment: .leading, spacing: 12) {
                        Text("① 같은 배치 유지  ② 펜을 멀리 두고 배경 맞추기  ③ 모드 선택 후 움직이기").font(.headline)
                        Text("iPad·스탠드·사각형·주변 물체 위치는 수집 때와 같아야 합니다. 배경 보정만으로 달라진 배치를 복구할 수는 없습니다. 펜은 책상과 수직, 로고는 왼쪽입니다.").font(.subheadline).foregroundStyle(.secondary)
                        HStack {
                            Button(tester.calibrating ? "배경 측정 중…" : "펜을 멀리 두었음 · 배경 맞추기 (5초)") { tester.calibrate() }
                                .buttonStyle(.borderedProminent).disabled(!collector.sensorFresh || collector.sessionOpen || tester.calibrating || tester.model == nil)
                            if tester.calibrating { Text("\(tester.calibrationRemaining, specifier: "%.0f")초").monospacedDigit() }
                        }
                        if !collector.sensorFresh {
                            Label("자력계 수신을 기다리는 중입니다. 수신되면 배경 맞추기 버튼이 활성화됩니다.", systemImage: "info.circle")
                                .font(.caption).foregroundStyle(.orange)
                        }
                        Picker("펜 높이", selection: $tester.modeID) {
                            Text("책상 접촉").tag("surface")
                            Text("약 1cm 공중").tag("air")
                        }.pickerStyle(.segmented).disabled(tester.calibrating)
                        Text(tester.modeID == "surface" ? "펜 끝을 표면에 가볍게 대고 움직이세요." : "펜 끝을 책상에서 약 1cm 띄우세요. 높이 오차가 위치 오차로 섞일 수 있습니다.")
                            .font(.subheadline)
                    }.padding(20).background(.background, in: RoundedRectangle(cornerRadius: 18))
                    LiveMapCanvas(tester: tester).frame(height: 430)
                    Text("현재 모델은 이동 중 표시가 자주 보류될 수 있습니다. 앱이 멈춘 것이 아니라, 받은 신호를 네 모서리 보간으로 설명하기 어려운 상태입니다.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(tester.status).font(.headline).foregroundStyle(tester.point == nil ? .secondary : .primary)
                            if let p = tester.point {
                                Text("추정 x \(p.x, specifier: "%.2f") · y \(p.y, specifier: "%.2f")").monospacedDigit()
                            }
                            if let r = tester.residual {
                                Text("모델과 자기장 차이 \(r, specifier: "%.1f") µT · 위치 오차나 신뢰도 %가 아닙니다").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        Spacer()
                        Button("궤적 지우기") { tester.trail = [] }.buttonStyle(.bordered)
                    }
                    if let shift = tester.baselineShift, shift > 15 {
                        Label("수집 때보다 배경 자기장이 크게 달라졌습니다. 네 모서리부터 확인하세요.", systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                    }
                    HStack {
                        Button("테스트 기록 저장") { tester.saveLog() }.buttonStyle(.bordered)
                        if let url = tester.exportURL { ShareLink("저장한 CSV 공유", item: url) }
                    }
                    Text("표시된 점은 센서로 계산한 추정치입니다. 손의 실제 위치·접촉 여부·높이를 직접 측정하지 않습니다. 기준에서 벗어나면 현재 점을 숨기고 궤적을 끊습니다. 약 0.12초의 자기장 중앙값 필터를 사용하며, 표시 지연이 있을 수 있습니다. 테스트 기록은 최대 30분씩 저장하세요.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(28).frame(maxWidth: 1050).frame(maxWidth: .infinity)
            }.background(Color(uiColor: .systemGroupedBackground)).navigationTitle("MagAir · Live Pilot")
        }
        .onAppear { tester.active = !collector.sessionOpen }
        .onDisappear { tester.active = false; tester.invalidate("배경을 다시 맞추고 테스트하세요") }
        .onChange(of: tester.modeID) { _, _ in tester.changeMode() }
        .onChange(of: collector.sessionOpen) { _, open in tester.active = !open }
    }
}

struct LiveMapCanvas: View {
    @ObservedObject var tester: LiveTester
    var body: some View {
        GeometryReader { geo in
            let aspect = tester.model?.aspect ?? 1.5
            let w = min(geo.size.width - 100, (geo.size.height - 100)*aspect)
            let h = w/aspect
            let rect = CGRect(x: (geo.size.width-w)/2, y: 50, width: w, height: h)
            Canvas { context, _ in
                context.fill(Path(rect), with: .color(.teal.opacity(0.05)))
                context.stroke(Path(rect), with: .color(.secondary), lineWidth: 1.5)
                let cornerLabels = [(0.0, 0.0, "왼쪽 위 · iPad 쪽"), (1.0, 0.0, "오른쪽 위"), (1.0, 1.0, "오른쪽 아래"), (0.0, 1.0, "왼쪽 아래 · 사용자 쪽")]
                for (x, y, label) in cornerLabels {
                    let p = CGPoint(x: rect.minX+w*x, y: rect.minY+h*y)
                    context.fill(Path(ellipseIn: CGRect(x: p.x-4, y: p.y-4, width: 8, height: 8)), with: .color(.secondary))
                    context.draw(Text(label).font(.caption), at: CGPoint(x: p.x, y: p.y + (y == 0 ? -23 : 23)))
                }
                var path = Path()
                var previous: Int?
                for p in tester.trail {
                    let position = CGPoint(x: rect.minX+w*p.point.x, y: rect.minY+h*p.point.y)
                    if previous == p.segment { path.addLine(to: position) } else { path.move(to: position) }
                    previous = p.segment
                }
                context.stroke(path, with: .color(.teal.opacity(0.5)), style: StrokeStyle(lineWidth: 2.5, lineJoin: .round))
                if let p = tester.point {
                    let position = CGPoint(x: rect.minX+w*p.x, y: rect.minY+h*p.y)
                    context.fill(Path(ellipseIn: CGRect(x: position.x-10, y: position.y-10, width: 20, height: 20)), with: .color(.teal))
                } else {
                    context.draw(Text(tester.baseline == nil ? "배경 맞추기 후 시작" : "현재 위치 표시 보류").font(.headline).foregroundColor(.secondary), at: CGPoint(x: rect.midX, y: rect.midY))
                }
            }
        }.background(.background, in: RoundedRectangle(cornerRadius: 18))
            .accessibilityLabel("실시간 추정 위치. \(tester.status)")
    }
}
