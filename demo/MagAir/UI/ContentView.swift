import SwiftUI
import Charts

private let ink = Color(red: 0.08, green: 0.17, blue: 0.23)
private let accent = Color(red: 0.10, green: 0.61, blue: 0.54)

struct ContentView: View {
    @ObservedObject var collector: Collector
    @State private var showSetup = false
    @State private var showLibrary = false
    @State private var showHelp = false
    @State private var confirmEnd = false
    var body: some View {
        NavigationSplitView {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("MagAir").font(.system(size: 34, weight: .bold, design: .rounded)).foregroundStyle(ink)
                        Text("화면 밖, 작은 입력 공간").font(.subheadline).foregroundStyle(.secondary)
                        Label(collector.sensorFresh ? "자력계 연결됨" : "센서 확인 필요", systemImage: collector.sensorFresh ? "checkmark.circle.fill" : "exclamationmark.circle")
                            .font(.caption).foregroundStyle(collector.sensorFresh ? accent : .orange)
                    }.padding(.vertical, 8)
                }
                Section("처음에는 이것만 · 자 / 격자 없이") {
                    ForEach(ProtocolKind.basic) { kind in protocolButton(kind) }
                }
                Section("추가: 접촉 · 약 1cm 공중 비교") {
                    ForEach(ProtocolKind.heightStudies) { kind in protocolButton(kind) }
                }
                Section {
                    DisclosureGroup("나중에 · 정밀 / 추가 측정") {
                        ForEach(ProtocolKind.advanced) { kind in protocolButton(kind) }
                    }
                }
            }
            .listStyle(.sidebar)
            .navigationSplitViewColumnWidth(min: 260, ideal: 290, max: 330)
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("PENCIL 90° · 로고는 왼쪽").font(.caption.weight(.bold))
                    Text(collector.selected.isHeightStudy ? "높이는 화면 안내에 맞추세요.\n아이패드와 스탠드는 고정." : "펜 끝은 책상에 가볍게.\n아이패드와 스탠드는 고정.").font(.caption).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(22).background(.regularMaterial)
            }
        } detail: {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    header
                    if !collector.sessionOpen { welcome }
                    experimentCard
                    sensorCard
                    Text(collector.notice).font(.footnote).foregroundStyle(.secondary)
                    Label("화면의 점은 이동 안내입니다. 펜의 실제 추정 위치가 아닙니다.", systemImage: "info.circle")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(28).frame(maxWidth: 1050)
                    .frame(maxWidth: .infinity)
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("측정 스튜디오")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button { showHelp = true } label: { Label("실험 안내", systemImage: "questionmark.circle") }
                    Button { collector.refreshLibrary(); showLibrary = true } label: { Label("저장 기록", systemImage: "folder") }
                        .disabled(collector.recording)
                    Button { showSetup = true } label: { Label("설정", systemImage: "slider.horizontal.3") }
                        .disabled(collector.sessionOpen || collector.isClosing)
                }
            }
        }
        .sheet(isPresented: $showSetup) { SetupView(collector: collector) }
        .sheet(isPresented: $showLibrary) { LibraryView(collector: collector) }
        .sheet(isPresented: $showHelp) { HelpView() }
        .alert("확인", isPresented: Binding(get: { collector.errorMessage != nil }, set: { if !$0 { collector.errorMessage = nil } })) {
            Button("확인", role: .cancel) { collector.errorMessage = nil }
        } message: { Text(collector.errorMessage ?? "") }
        .confirmationDialog("현재 세션을 저장하고 종료할까요?", isPresented: $confirmEnd, titleVisibility: .visible) {
            Button("세션 저장·종료") { collector.endSession() }
            Button("취소", role: .cancel) {}
        } message: { Text("진행 중인 측정은 미완료로 표시됩니다. 저장 기록에서 ZIP 파일을 내보낼 수 있습니다.") }
    }

    private func protocolButton(_ kind: ProtocolKind) -> some View {
        Button { collector.select(kind) } label: {
            HStack {
                Text(kind.title).font(.subheadline.weight(.semibold))
                Spacer()
                if collector.selected == kind { Image(systemName: "circle.inset.filled").foregroundStyle(accent) }
            }.foregroundStyle(ink).padding(.vertical, 7)
        }.disabled(collector.recording || collector.isClosing)
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 8) {
                Text("CRITICAL REGION / PILOT 01").font(.caption.weight(.bold)).tracking(1.8).foregroundStyle(accent)
                Text("작은 움직임을 기록하다").font(.largeTitle.weight(.bold)).foregroundStyle(ink)
                Text("자력계 3축 + iPad IMU · 기기 내 저장").foregroundStyle(.secondary)
            }
            Spacer()
            if collector.sessionOpen {
                Button("세션 종료", role: .destructive) { confirmEnd = true }.buttonStyle(.bordered)
            }
        }
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("자가 없어도 시작할 수 있습니다", systemImage: "rectangle.and.pencil.and.ellipsis")
                .font(.headline)
            Text("이미 그려둔 사각형의 네 모서리만 사용합니다. 위쪽은 iPad 쪽, 아래쪽은 사용자 쪽입니다. 먼저 네 위치의 신호가 구별되는지 확인하고, 격자 측정은 나중에 합니다.")
                .font(.subheadline).foregroundStyle(.secondary)
            Button(collector.setup.confirmed ? "실험 조건 확인 완료 · 수정" : "실험 조건 확인") { showSetup = true }
                .buttonStyle(.borderedProminent)
            Text("가로 : 세로 = \(collector.setup.aspect, specifier: "%.2f") : 1 · 조건 확인 후 아래 ‘측정 시작’을 누르면 새 세션도 자동으로 생성됩니다.")
                .font(.footnote).foregroundStyle(.secondary)
        }.padding(22).frame(maxWidth: .infinity, alignment: .leading).background(.background, in: RoundedRectangle(cornerRadius: 20))
    }

    private var experimentCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text(collector.selected.title).font(.title2.weight(.bold)).foregroundStyle(ink)
                    Text(collector.selected.summary).font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
                if collector.recording {
                    Label("REC", systemImage: "record.circle.fill").font(.caption.weight(.bold)).foregroundStyle(.red)
                }
            }
            RegionView(kind: collector.selected, target: collector.guidePoint, aspect: collector.setup.aspect,
                       active: collector.recording, phase: collector.phaseText)
                .frame(height: 320)
            if collector.selected == .corners {
                Text("① 화면에 표시된 모서리에 펜 끝을 댑니다. ② 측정 버튼을 누릅니다. ③ 준비 3초 동안 자세를 잡고, 이어지는 측정 3초 동안 움직이지 마세요. 저장되면 다음 모서리로 옮깁니다.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            if collector.selected.isHeightStudy {
                VStack(alignment: .leading, spacing: 7) {
                    Text("높이는 책상에서 펜 끝까지 · 약 1cm").font(.headline).foregroundStyle(accent)
                    Text(collector.selected == .cornersHeight
                         ? "같은 모서리에서 접촉 → 수직으로 들기 → 공중 정지 → 다시 접촉합니다. 화면 안내와 소리에 맞추세요. 네 모서리 × 3회, 총 12번입니다."
                         : "먼저 같은 방향의 ‘접촉 테두리’를 재고, 같은 경로를 약 1cm 띄워 따라가세요. 펜 기울기와 로고 방향은 그대로 유지합니다.")
                    Text("눈대중 높이입니다. 실제 높이나 접촉 여부를 센서로 측정한 값으로 저장하지 않습니다.")
                        .font(.caption).foregroundStyle(.secondary)
                }.font(.subheadline).padding(14).background(accent.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
            }
            HStack(alignment: .center, spacing: 18) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(collector.phaseText).font(.title3.weight(.semibold)).foregroundStyle(ink)
                    if let spec = collector.currentSpec, let point = spec.point {
                        Text("\(collector.planIndex + 1) / \(collector.plan.count)  ·  \(spec.repetition)회차  ·  \(spec.locationName)")
                            .font(.subheadline.monospacedDigit())
                        if !collector.selected.isCornerStudy { Text("x \(point.x, specifier: "%.3f")  ·  y \(point.y, specifier: "%.3f")")
                            .font(.caption.monospaced()).foregroundStyle(.secondary)
                        }
                    } else if collector.recording {
                        Text("\(max(0, collector.elapsed - 3), specifier: "%.1f")초 / \(collector.selected.duration, specifier: "%.0f")초")
                            .font(.subheadline.monospacedDigit())
                    }
                }
                Spacer()
                if collector.recording {
                    Button("중단 · 다시 측정", role: .destructive) { collector.abortTrial() }.buttonStyle(.bordered)
                } else {
                    if collector.planIndex > 0 {
                        Button("직전 재측정") { collector.redoPrevious() }.buttonStyle(.bordered)
                            .disabled(!collector.sessionOpen)
                    }
                    Button {
                        if !collector.setup.confirmed { showSetup = true }
                        else { collector.startTrial() }
                    } label: {
                        Label(!collector.setup.confirmed ? "실험 조건 확인" : (collector.selected.isStatic || collector.selected.isCornerStudy ? "위치 준비 완료 · 측정" : "측정 시작"), systemImage: "play.fill")
                    }.buttonStyle(.borderedProminent).controlSize(.large)
                        .disabled(collector.isClosing || (collector.setup.confirmed && (!collector.sensorFresh || (collector.sessionOpen && collector.currentSpec == nil))))
                }
            }
            if !collector.recording, let reason = collector.startBlockReason {
                Label(reason, systemImage: "info.circle.fill")
                    .font(.subheadline).foregroundStyle(.orange)
            }
            ProgressView(value: collector.progress).tint(accent)
            if collector.sessionOpen, !collector.recording, collector.currentSpec == nil,
               let i = ProtocolKind.basic.firstIndex(of: collector.selected), i + 1 < ProtocolKind.basic.count {
                Button("다음: \(ProtocolKind.basic[i + 1].title)") { collector.select(ProtocolKind.basic[i + 1]) }
                    .buttonStyle(.borderedProminent)
            }
            HStack {
                Toggle("안내음", isOn: $collector.soundEnabled).toggleStyle(.switch).fixedSize().font(.caption)
                Spacer()
                if collector.deviceMoving { Label("아이패드 움직임 감지", systemImage: "exclamationmark.triangle.fill").font(.caption).foregroundStyle(.orange) }
            }
        }.padding(22).background(.background, in: RoundedRectangle(cornerRadius: 22))
    }

    private var sensorCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("자기장 실시간 모니터").font(.headline).foregroundStyle(ink)
                Spacer()
                Text(collector.sensorFresh ? String(format: "실측 %.1f Hz", collector.actualHz) : "수신 없음")
                    .font(.caption.monospacedDigit()).foregroundStyle(collector.sensorFresh ? accent : .orange)
            }
            HStack(spacing: 28) {
                fieldValue("Bx", collector.field?.x, color: .blue)
                fieldValue("By", collector.field?.y, color: .orange)
                fieldValue("Bz", collector.field?.z, color: accent)
                fieldValue("|B|", collector.field?.magnitude, color: .secondary)
            }
            Chart {
                ForEach(collector.history) { item in
                    LineMark(x: .value("t", item.t), y: .value("µT", item.x), series: .value("axis", "Bx")).foregroundStyle(.blue)
                    LineMark(x: .value("t", item.t), y: .value("µT", item.y), series: .value("axis", "By")).foregroundStyle(.orange)
                    LineMark(x: .value("t", item.t), y: .value("µT", item.z), series: .value("axis", "Bz")).foregroundStyle(accent)
                }
            }.chartXAxis(.hidden).frame(height: 130)
            Text("원시 자기장 · µT  /  요청 50 Hz, 실제 간격은 센서 타임스탬프로 기록합니다.")
                .font(.caption).foregroundStyle(.secondary)
            Divider()
            Label(collector.pencilStatus, systemImage: "pencil.tip.crop.circle").font(.subheadline)
            Text("펜슬 자세는 화면 접촉·호버 때만 보조 기록합니다. 책상에서의 기울기·축 회전각은 측정되지 않으며, 화면 기준 각도와 책상 기준 90°는 다릅니다.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(22).background(.background, in: RoundedRectangle(cornerRadius: 22))
    }

    private func fieldValue(_ label: String, _ value: Double?, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.caption.weight(.bold)).foregroundStyle(color)
            Text(value.map { String(format: "%.1f µT", $0) } ?? "— µT").font(.title3.monospacedDigit().weight(.semibold))
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct RegionView: View {
    var kind: ProtocolKind
    var target: Point2D?
    var aspect: Double
    var active: Bool
    var phase: String
    var body: some View {
        GeometryReader { geo in
            let maxWidth = geo.size.width - 88
            let maxHeight = geo.size.height - 55
            let w = min(maxWidth, maxHeight * aspect)
            let h = w / aspect
            let rect = CGRect(x: (geo.size.width-w)/2, y: 27, width: w, height: h)
            Canvas { context, _ in
                context.fill(Path(roundedRect: rect, cornerRadius: 12), with: .color(accent.opacity(0.05)))
                context.stroke(Path(roundedRect: rect, cornerRadius: 4), with: .color(ink.opacity(0.3)), lineWidth: 1.5)
                for i in (kind.isGrid ? Array(0...4) : []) {
                    let f = Double(i)/4
                    var line = Path()
                    line.move(to: CGPoint(x: rect.minX + w*f, y: rect.minY))
                    line.addLine(to: CGPoint(x: rect.minX + w*f, y: rect.maxY))
                    line.move(to: CGPoint(x: rect.minX, y: rect.minY+h*f))
                    line.addLine(to: CGPoint(x: rect.maxX, y: rect.minY+h*f))
                    context.stroke(line, with: .color(ink.opacity(0.1)), style: StrokeStyle(lineWidth: 1, dash: [4,4]))
                }
                if kind.isGrid {
                    let n = kind == .gridTrain ? 5 : 4
                    for r in 0..<n {
                        for c in 0..<n {
                            let off = kind == .gridTest ? 0.5 : 0.0
                            let p = CGPoint(x: rect.minX + w*(Double(c)+off)/4, y: rect.minY + h*(Double(r)+off)/4)
                            context.fill(Path(ellipseIn: CGRect(x: p.x-3, y: p.y-3, width: 6, height: 6)), with: .color(ink.opacity(0.35)))
                        }
                    }
                }
                let pathPoints = kind.path
                if !pathPoints.isEmpty {
                    var path = Path()
                    for (i, p) in pathPoints.enumerated() {
                        let point = CGPoint(x: rect.minX+w*p.x, y: rect.minY+h*p.y)
                        if i == 0 { path.move(to: point) } else { path.addLine(to: point) }
                    }
                    context.stroke(path, with: .color(accent.opacity(0.55)), style: StrokeStyle(lineWidth: 3, dash: [8,5]))
                }
                if let target {
                    let center = CGPoint(x: rect.minX+w*target.x, y: rect.minY+h*target.y)
                    context.fill(Path(ellipseIn: CGRect(x: center.x-17, y: center.y-17, width: 34, height: 34)), with: .color(accent.opacity(0.18)))
                    context.fill(Path(ellipseIn: CGRect(x: center.x-8, y: center.y-8, width: 16, height: 16)), with: .color(accent))
                }
                context.draw(Text(kind.isGrid ? "(0, 0)" : "왼쪽 위 · iPad 쪽").font(.caption).foregroundColor(.secondary), at: CGPoint(x: rect.minX, y: 10))
                if !kind.isGrid {
                    context.draw(Text("오른쪽 위").font(.caption).foregroundColor(.secondary), at: CGPoint(x: rect.maxX, y: 10))
                    context.draw(Text("왼쪽 아래").font(.caption).foregroundColor(.secondary), at: CGPoint(x: rect.minX, y: rect.maxY+19))
                    context.draw(Text("오른쪽 아래").font(.caption).foregroundColor(.secondary), at: CGPoint(x: rect.maxX, y: rect.maxY+19))
                }
                context.draw(Text("x →").font(.caption).foregroundColor(.secondary), at: CGPoint(x: rect.maxX+27, y: rect.minY))
                context.draw(Text("y ↓").font(.caption).foregroundColor(.secondary), at: CGPoint(x: rect.minX-27, y: rect.maxY))
                context.draw(Text(kind.isGrid ? "사용자 쪽 · (1, 1)" : "사용자 쪽").font(.caption).foregroundColor(.secondary), at: CGPoint(x: rect.midX, y: rect.maxY+19))
                if kind.isBaseline {
                    context.draw(Text("펜슬을 멀리").font(.headline).foregroundColor(ink), at: CGPoint(x: rect.midX, y: rect.midY))
                }
                if kind == .free {
                    context.draw(Text("자유 궤적 30초").font(.headline).foregroundColor(ink), at: CGPoint(x: rect.midX, y: rect.midY))
                }
            }
        }.accessibilityLabel("직사각형 안내. \(phase). \(target.map { "목표 x \($0.x), y \($0.y)" } ?? "")")
    }
}

struct SetupView: View {
    @ObservedObject var collector: Collector
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                Section("장비와 고정 조건") {
                    Text("iPad Pro 11형 4세대 · 기기 식별자와 iPadOS 버전은 자동 저장됩니다.").font(.footnote)
                    TextField("펜슬 모델", text: $collector.setup.pencil)
                    TextField("측정 평면", text: $collector.setup.plane)
                    TextField("아이패드 각도", text: $collector.setup.standAngle)
                    TextField("펜 끝 높이", text: $collector.setup.heightNote)
                    Text("기본 자세: 책상에 수직 90°, Apple 로고는 사용자 기준 왼쪽, 펜 끝은 표면에 가볍게 접촉.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("직사각형") {
                    Picker("대략적인 가로 : 세로", selection: $collector.setup.aspect) {
                        Text("1 : 1.5 (세로가 김)").tag(1.0/1.5)
                        Text("1.5 : 1 (가로가 김)").tag(1.5)
                        Text("1 : 1").tag(1.0)
                    }
                    TextField("실측 가로 mm · 모르면 비워두기", text: $collector.setup.widthMM).keyboardType(.decimalPad)
                    TextField("실측 세로 mm · 모르면 비워두기", text: $collector.setup.heightMM).keyboardType(.decimalPad)
                    Text("첫 실험에는 자·격자·중앙 표식이 필요 없습니다. 기존 직사각형의 네 모서리만 사용합니다. 치수는 모르면 비워두세요.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("환경 기록") {
                    TextField("케이스 / 충전 연결 / 스탠드 / 위치 설명", text: $collector.setup.environment, axis: .vertical).lineLimit(3...6)
                    Text("충전 케이블, 케이스, 주변 금속과 자석은 측정 중 그대로 유지하세요. 설치 후 케이블을 뺄 경우 배경 측정 전에 빼세요.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("센서 범위") {
                    Text("수집: iPad 자력계·가속도계·자이로·기기 자세. 화면 밖 Apple Pencil의 원시 IMU는 수집되지 않습니다. 펜의 90°와 로고 방향은 직접 유지해야 합니다.")
                        .font(.subheadline)
                    Text("아래 버튼을 누르면 배치·좌표 방향·펜 자세를 확인한 것으로 저장합니다.").font(.footnote).foregroundStyle(.secondary)
                    Button {
                        collector.setup.confirmed = true
                        dismiss()
                    } label: {
                        Label("이 조건으로 준비 완료", systemImage: "checkmark.circle.fill")
                            .frame(maxWidth: .infinity).padding(.vertical, 6)
                    }.buttonStyle(.borderedProminent)
                }
            }
            .navigationTitle("실험 조건")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("이 조건으로 준비 완료") { collector.setup.confirmed = true; dismiss() }
                }
            }
        }.frame(minWidth: 500, minHeight: 600)
    }
}

struct LibraryView: View {
    @ObservedObject var collector: Collector
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("세션 하나가 ZIP 파일 하나입니다. 공유 → AirDrop으로 맥북에 보내거나 ‘파일에 저장’을 선택하세요.")
                    if collector.sessionOpen { Text("내보내려면 먼저 현재 세션을 종료하세요.").foregroundStyle(.orange) }
                    if collector.isExporting { ProgressView("ZIP 준비 중") }
                    if let url = collector.archiveURL {
                        ShareLink(item: url) { Label("준비된 ZIP 공유", systemImage: "square.and.arrow.up") }
                        Text(url.lastPathComponent).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Section("저장된 세션 · \(collector.library.count)개") {
                    if collector.library.isEmpty { Text("저장된 세션이 없습니다.").foregroundStyle(.secondary) }
                    ForEach(collector.library, id: \.path) { directory in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(directory.lastPathComponent).font(.subheadline.monospaced()).textSelection(.enabled)
                            if let data = try? Data(contentsOf: directory.appendingPathComponent("manifest.json")),
                               let session = try? JSONDecoder().decode(SessionManifest.self, from: data) {
                                Text("완료 측정 \(session.trials.filter { $0.status == "completed" }.count)개 · 상태 \(session.status)")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Button("이 세션 ZIP 만들기") { collector.archiveURL = nil; collector.export(directory) }
                                .disabled(collector.sessionOpen || collector.isExporting || collector.isClosing)
                        }.padding(.vertical, 6)
                    }
                }
                Section {
                    Text("파일 앱 → 나의 iPad → MagAir → MagAirSessions에서도 원본 폴더를 확인할 수 있습니다. 앱이 종료된 기록은 마지막 자동 저장 지점까지 남으며, 미완료 측정은 분석에서 제외합니다.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }.navigationTitle("저장 기록")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("닫기") { dismiss() } } }
        }.frame(minWidth: 500, minHeight: 600)
    }
}

struct HelpView: View {
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            List {
                Section("첫 실험 · 자 없이 약 6–10분") {
                    Text("1. 기존 사각형을 그대로 사용합니다. 네 모서리만 구별하면 됩니다. 위쪽은 iPad 쪽, 아래쪽은 사용자 쪽입니다. 새 격자를 그릴 필요가 없습니다.")
                    Text("2. 실험 조건에서 ‘이 조건으로 준비 완료’를 누르고 ‘시작 배경 자기장’의 ‘측정 시작’을 누릅니다. 세션은 자동으로 만들어집니다. 펜슬을 멀리 치운 뒤 수치가 배경 수준으로 돌아왔는지 확인하세요.")
                    Text("3. ‘네 모서리에서 멈추기’를 선택합니다. 화면에 나온 모서리에 펜 끝을 대고 측정 버튼을 누르세요. 3초는 자세를 잡는 시간, 그 다음 3초는 움직이지 않고 재는 시간입니다.")
                    Text("4. 왼쪽 위 → 오른쪽 위 → 오른쪽 아래 → 왼쪽 아래를 세 번 반복합니다. 총 12번 측정이며, 다음 위치로 옮길 때마다 버튼을 누릅니다.")
                    Text("5. 시계 / 반시계 테두리와 양쪽 대각선을 따라갑니다. 화면의 점은 시간 안내일 뿐 실제 위치를 측정하지 않습니다. 정답 궤적이 필요하면 별도의 위쪽 카메라 촬영 등이 필요합니다.")
                    Text("6. ‘종료 배경 자기장’을 측정한 뒤 세션 종료 → 저장 기록 → ZIP 만들기 → 공유합니다.")
                }
                Section("5 × 5와 4 × 4는 언제 하나요?") {
                    Text("나중에 영역 안쪽의 좌표까지 학습할 때 사용합니다. 5 × 5는 서로 다른 25곳을 알려주는 학습용 측정입니다. 각 위치에서 세 번 재므로 총 75번입니다.")
                    Text("4 × 4는 학습한 점 사이의 16곳을 따로 재서 위치 예측이 맞는지 확인하는 검증용 측정입니다. 두 번씩 총 32번입니다. 지금은 하지 않아도 됩니다.")
                    Text("네 모서리만으로는 안쪽의 정확한 좌표나 글씨 복원 성능을 검증할 수 없습니다. 먼저 네 위치의 신호가 구별되고 반복되는지부터 확인합니다.")
                }
                Section("접촉과 공중 비교 · 약 1cm") {
                    Text("높이 기준은 책상에서 펜 끝까지입니다. 처음에는 약 1cm만 띄우세요. 자가 없으므로 눈대중 목표이며, 정확한 높이로 분석하지 않습니다. 매번 최대한 같은 높이·같은 펜 자세를 유지하세요.")
                    Text("‘모서리 접촉 ↔ 공중’: 모서리에 댄 채 시작 → 준비 3초 → 접촉 정지 3초 → 2초에 들어 올리기 → 공중 정지 3초 → 2초에 내리기 → 접촉 정지 3초. 네 모서리를 세 번 반복합니다.")
                    Text("‘공중 테두리’: 기존의 접촉 테두리와 같은 속도·방향으로 약 1cm 띄워 움직입니다. 시계와 반시계가 따로 있습니다. 이동 중 실제 높이와 경로는 직접 측정되지 않습니다.")
                    Text("멀리 들어 신호가 사라지는 조건은 배경 확인에 가까워서, 첫 높이 비교는 가까운 1cm로 제한합니다. 필요하면 받은 데이터를 보고 다음 높이를 정합니다.")
                }
                Section("재현성을 위한 약속") {
                    Text("펜은 책상과 90°, 로고는 왼쪽입니다. 기본 측정은 펜 끝을 표면에 대고, 공중 비교에서는 높이 안내를 따릅니다. 책상과 iPad·스탠드·케이블을 움직이지 마세요. 안내음은 단계가 바뀔 때 울립니다.")
                    Text("흔들렸다면 ‘중단 · 다시 측정’ 또는 ‘직전 재측정’을 누르세요. 이전 시도는 지우지 않고 분석 제외 표시를 합니다.")
                    Text("실험 중 앱을 배경으로 보내거나 화면을 잠그면 세션을 중단 저장합니다. 돌아와 새 세션을 시작하세요. 센서가 없거나 수신이 끊기면 유효한 측정을 시작할 수 없습니다.")
                }
                Section("결과의 의미") {
                    Text("데이터 수집 탭의 점은 이동 안내입니다. 별도의 ‘실시간 테스트’ 탭에는 네 모서리 자기장으로 보간한 추정점이 표시됩니다. 내부 좌표와 글씨 복원 정확도는 아직 검증하지 않았습니다.")
                    Text("들기 / 축 회전은 위치 변화와 자기장 변화가 얼마나 혼동되는지 보는 추가 실험입니다. 자력계가 접촉이나 펜 자세를 직접 측정하는 것은 아닙니다.")
                }
            }.navigationTitle("실험 안내")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("닫기") { dismiss() } } }
        }.frame(minWidth: 500, minHeight: 600)
    }
}
