import SwiftUI

struct EdgeStudyView: View {
    @ObservedObject var collector: Collector
    @State private var showSetup = false
    @State private var showLibrary = false
    @State private var confirmEnd = false
    var scenario: EdgeScenario { collector.edgeScenario ?? collector.nextDenseCollection }
    var spec: TrialSpec? { collector.activeTrial?.spec ?? collector.currentSpec }
    var finished: Bool { !collector.plan.isEmpty && collector.currentSpec == nil && !collector.sessionOpen }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text(scenario.isGridMap ? "\(scenario.gridSize)×\(scenario.gridSize) 격자 좌표 수집" : (scenario.isGridPath ? "그려둔 선을 내 속도로" : "한 변씩, 내 속도로")).font(.largeTitle.bold())
                    Text("지금은 9×9 학습입니다. 16A부터 18C까지 9묶음 → 새 지도 제작 → 자유 실시간 테스트 → 별도 검증 순서입니다. 14·15는 지금 하지 않아도 됩니다.")
                        .font(.headline).foregroundStyle(.teal)
                    Picker("측정 묶음", selection: Binding(get: { scenario }, set: { collector.selectEdge($0) })) {
                        ForEach(EdgeScenario.denseTraining + EdgeScenario.allCases.filter { $0.denseRound == nil }) {
                            Text($0.title + (collector.denseCompleted.contains($0.rawValue) ? " ✓ 저장됨" : "")).tag($0)
                        }
                    }.pickerStyle(.menu).disabled(collector.sessionOpen || collector.isClosing)
                    Text(scenario.summary).foregroundStyle(.secondary)
                    if let round = scenario.denseRound {
                        Text("학습 \(round)/3회차 · 묶음 \((scenario.denseIndex ?? 0)+1)/9 · 저장 완료 이력 \(collector.denseCompleted.count)/9")
                            .font(.headline)
                    }
                    if collector.sessionOpen && collector.edgeScenario == nil {
                        Text("이전 수집의 세션이 열려 있습니다. 해당 세션을 저장·종료한 뒤 한 변씩 수집을 시작하세요.")
                            .foregroundStyle(.orange)
                    } else {
                        if !collector.sessionOpen && !finished { preparation }
                        if finished { completion } else { measurement }
                    }
                    HStack(spacing: 22) {
                        Label(collector.sensorFresh ? "자력계 수신 중" : "자력계 연결 대기", systemImage: "waveform.path")
                        if let f = collector.field {
                            Text(String(format: "Bx %.1f   By %.1f   Bz %.1f µT", f.x, f.y, f.z)).monospacedDigit()
                        }
                    }.font(.footnote)
                    Text(collector.notice).font(.footnote).foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 8) {
                        Text("펜슬 자세 센서에 관하여").font(.headline)
                        Text("Apple Pencil 2의 자이로·가속도 원시 데이터는 공개 API로 받을 수 없습니다. 이 앱이 기록하는 IMU는 iPad의 센서입니다. 책상에서의 펜 기울기·축 회전각은 측정하지 않으며, 자세 검사는 사람이 수행한 동작 이름만 기록합니다.")
                    }.font(.footnote).padding(18).background(.teal.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
                }.padding(26).frame(maxWidth: 1000).frame(maxWidth: .infinity)
            }.background(Color(uiColor: .systemGroupedBackground))
                .navigationTitle("MagAir · 좌표 수집 1.12")
                .toolbar {
                    ToolbarItemGroup(placement: .topBarTrailing) {
                        Button("저장 기록") { collector.refreshLibrary(); showLibrary = true }.disabled(collector.recording)
                        Button("실험 조건") { showSetup = true }.disabled(collector.sessionOpen || collector.isClosing)
                        if collector.sessionOpen { Button("중간 저장·종료") { confirmEnd = true } }
                    }
                }
        }
        .onAppear { if collector.edgeScenario == nil && !collector.sessionOpen { collector.selectEdge(collector.nextDenseCollection) } }
        .sheet(isPresented: $showSetup) { SetupView(collector: collector) }
        .sheet(isPresented: $showLibrary) { LibraryView(collector: collector) }
        .alert("측정 안내", isPresented: Binding(get: { collector.errorMessage != nil }, set: { if !$0 { collector.errorMessage = nil } })) {
            Button("확인", role: .cancel) {}
        } message: { Text(collector.errorMessage ?? "") }
        .confirmationDialog("현재까지 저장하고 이 묶음을 종료할까요?", isPresented: $confirmEnd, titleVisibility: .visible) {
            Button("중간 저장·종료") { collector.endSession(status: "partial_edge_study") }
            Button("계속 측정", role: .cancel) {}
        } message: { Text("진행 중인 항목은 제외됩니다. 마지막 배경이 없는 묶음은 모델 학습에 사용하지 않습니다.") }
    }

    private var preparation: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(scenario.isGridMap ? "책상 위 \(scenario.gridSize * scenario.gridSize)개 표식 · 테두리 포함" : "책상 위 준비").font(.headline)
            if scenario.denseRound != nil {
                Text("9×9 = 총 81개 점입니다. 위(iPad 쪽)가 1행, 아래(사용자 쪽)가 9행이고 왼쪽부터 1–9열입니다. 가운데는 5행 5열, 기존 5×5 점은 홀수 행·홀수 열입니다.\n각 점을 서로 다른 회차에 3번 다시 놓아 측정하며 모두 학습에 사용합니다. 세 회차 동안 같은 배치를 유지하세요. 자동 저장된 묶음 사이에는 쉬어도 됩니다.")
                DisclosureGroup("9×9 표식 배치 미리보기 · 가운데 5행 5열") {
                    GridCollectionDiagram(target: .init(x: 0.5, y: 0.5), row: 5,
                                          aspect: collector.setup.aspect, gridSize: 9).frame(height: 380)
                    Text("배치 확인용 그림입니다. 실제 측정 위치는 아래 항목의 주황색 점을 따르세요.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if scenario.isGridPath {
                Text("표시된 선 위를 편한 속도로 한 번 왕복합니다. 준비 3초 뒤 출발하고, 출발점으로 돌아온 뒤 직접 완료하세요. 화면에는 움직이는 안내점이나 실시간 추정을 보여주지 않습니다. 종이에 그린 선만 따라주세요.")
            }
            Text(scenario.isGridMap ? "주황색 점에 펜 끝을 가볍게 놓고 직접 시작하세요. 준비 3초 뒤 3초 정지합니다. 펜은 책상과 수직·로고 왼쪽을 유지하세요. 이동 중 값에는 위치 정답을 붙이지 않습니다. 각 행의 앞뒤 배경 안내 때마다 펜을 충분히 멀리 치우세요." : "위쪽은 iPad 쪽, 아래쪽은 사용자 쪽입니다. 펜 끝은 책상에 가볍게, 수직으로 세우고 로고는 왼쪽. iPad·스탠드·케이블 배치는 유지하세요.")
            Button(collector.setup.confirmed ? "실험 조건 확인 완료 · 수정" : "실험 조건 확인하고 준비 완료") { showSetup = true }
                .buttonStyle(.borderedProminent)
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading).background(.background, in: RoundedRectangle(cornerRadius: 18))
    }

    private var measurement: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("\(collector.planIndex + 1) / \(collector.plan.count) 항목").font(.headline.monospacedDigit())
                Spacer()
                Text(spec?.kind.title ?? "측정 묶음을 선택하세요").foregroundStyle(.secondary)
            }
            if spec?.kind.isBaseline == true {
                VStack(alignment: .leading, spacing: 10) {
                    Label("펜슬을 멀리 치우세요", systemImage: "arrow.up.right").font(.title2.bold())
                    Text("준비 3초 → 배경 10초 · 끝날 때까지 펜을 멀리 두세요.")
                }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
                    .background(.teal.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
            } else if scenario.isGridPath {
                GridLiveCanvas(estimate: nil, trail: [], guide: GridGuide(rawValue: spec?.guidePathID ?? "") ?? .free,
                               aspect: collector.setup.aspect).frame(height: 300)
            } else if scenario.isGridMap {
                GridCollectionDiagram(target: spec?.point, row: spec?.gridRow, aspect: collector.setup.aspect, gridSize: scenario.gridSize)
                    .frame(height: scenario.denseRound == nil ? 300 : 380)
            } else {
                EdgeDiagram(edge: spec?.edge, target: spec?.point, aspect: collector.setup.aspect)
                    .frame(height: 240)
            }
            if let spec {
                Text(spec.point != nil || spec.guidePathID != nil ? spec.locationName : (spec.gridRow.map { "\($0)행 · 배경 자기장" } ?? spec.edge?.title ?? "배경 자기장"))
                    .font(.title2.bold())
                Text(spec.instruction ?? "").font(.body).fixedSize(horizontal: false, vertical: true)
                Text(collector.phaseText).font(.title3.bold()).foregroundStyle(collector.recording ? .teal : .primary)
                if collector.recording {
                    if spec.isManual {
                        Text("왕복 속도는 자유 · 경과 \(max(0, collector.elapsed - 3), specifier: "%.0f")초 · 3분 이내 완료")
                            .font(.subheadline.monospacedDigit())
                    } else {
                        ProgressView(value: collector.progress)
                        Text("준비 3초 + 측정 \(Int(spec.duration))초 · 남은 시간 \(max(0, 3 + spec.duration - collector.elapsed), specifier: "%.0f")초")
                            .font(.subheadline.monospacedDigit())
                    }
                }
            }
            HStack(spacing: 14) {
                if collector.recording {
                    if spec?.isManual == true {
                        Button("왕복 완료 · 저장") { collector.finishSweep() }.buttonStyle(.borderedProminent).controlSize(.large)
                            .disabled(collector.elapsed < 7 || collector.activeTrial?.endUptime != nil)
                    }
                    Button("이 항목 취소·재측정", role: .destructive) { collector.abortTrial() }.buttonStyle(.bordered)
                } else {
                    Button(!collector.setup.confirmed ? "먼저 실험 조건 확인" : (spec?.kind.isBaseline == true ? "펜을 멀리 두었음 · 배경 10초 측정" : "준비 완료 · 이 항목 측정")) {
                        if !collector.setup.confirmed { showSetup = true } else { collector.startTrial() }
                    }.buttonStyle(.borderedProminent).controlSize(.large)
                        .disabled(collector.isClosing || (collector.setup.confirmed && !collector.sensorFresh))
                    if collector.planIndex > 0 && collector.sessionOpen {
                        Button("직전 항목 다시") { collector.redoPrevious() }.buttonStyle(.bordered)
                    }
                }
            }
            if !collector.sensorFresh { Text("센서 수신이 확인되면 측정 버튼이 활성화됩니다.").font(.footnote).foregroundStyle(.orange) }
            Toggle("단계 안내음", isOn: $collector.soundEnabled).font(.footnote).fixedSize()
            Text("그림의 점은 놓아야 할 기준점입니다. 측정한 펜 위치가 아닙니다. 왕복 중에는 움직이는 안내점이 없습니다.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(22).background(.background, in: RoundedRectangle(cornerRadius: 20))
    }

    private var completion: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(collector.isClosing ? "파일을 저장하고 있습니다" : "이 측정 묶음이 끝났습니다", systemImage: "checkmark.circle.fill")
                .font(.title2.bold()).foregroundStyle(.teal)
            if let next = scenario.nextDense {
                Text("이 묶음은 자동 저장됐습니다. 잠깐 쉬었다가 다음 묶음으로 진행하세요. 18C까지 모두 마친 뒤 알려주면 됩니다. 배치는 그대로 유지하세요.")
                Button("다음: \(next.title)") { collector.selectEdge(next) }
                    .buttonStyle(.borderedProminent).disabled(collector.isClosing)
            } else {
                Text(scenario.denseRound == nil ? "수집 완료라고 알려주세요. 마지막 배경까지 완료한 묶음은 자동 저장·종료됩니다." : "9×9 학습 수집을 마쳤습니다. 이제 수집 완료라고 알려주세요. 새 자료를 분석해 지도를 만든 뒤 실시간 테스트에 반영합니다. 현재 테스트 탭은 아직 기존 5×5 모델입니다.")
            }
            Text("맥북과 연결되어 있으면 직접 가져올 수 있으니 ZIP을 따로 옮기지 않아도 됩니다.")
            Button("저장 기록 · ZIP 공유 (선택)") { collector.refreshLibrary(); showLibrary = true }.buttonStyle(.borderedProminent)
                .disabled(collector.isClosing)
            Button("같은 묶음 처음부터 다시") { collector.selectEdge(scenario) }.buttonStyle(.bordered).disabled(collector.isClosing)
        }.padding(22).background(.background, in: RoundedRectangle(cornerRadius: 20))
    }
}

struct GridCollectionDiagram: View {
    var target: Point2D?
    var row: Int?
    var aspect: Double
    var gridSize: Int = 5
    var body: some View {
        GeometryReader { geo in
            Canvas { context, _ in
                let w = min(geo.size.width - 110, (geo.size.height - 95) * aspect)
                let r = CGRect(x: (geo.size.width-w)/2, y: 52, width: w, height: w/aspect)
                func p(_ x: Double, _ y: Double) -> CGPoint { .init(x: r.minX+x*r.width, y: r.minY+y*r.height) }
                context.draw(Text("위 · iPad 쪽").font(.caption.bold()), at: .init(x: r.midX, y: 8))
                context.draw(Text("아래 · 사용자 쪽").font(.caption.bold()), at: .init(x: r.midX, y: r.maxY+24))
                for i in 0..<gridSize {
                    let s = Double(i)/Double(gridSize-1)
                    var horizontal = Path(); horizontal.move(to: p(0,s)); horizontal.addLine(to: p(1,s))
                    var vertical = Path(); vertical.move(to: p(s,0)); vertical.addLine(to: p(s,1))
                    context.stroke(horizontal, with: .color(row == i+1 ? .teal.opacity(0.5) : .gray.opacity(0.2)), lineWidth: row == i+1 ? 3 : 1)
                    context.stroke(vertical, with: .color(.gray.opacity(0.2)), lineWidth: 1)
                    context.draw(Text("\(i+1)열").font(.caption), at: .init(x: p(s,0).x, y: r.minY-20))
                    context.draw(Text("\(i+1)행").font(.caption), at: .init(x: r.minX-32, y: p(0,s).y))
                    for j in 0..<gridSize {
                        let q = p(Double(j)/Double(gridSize-1),s)
                        context.fill(Path(ellipseIn: .init(x: q.x-4, y: q.y-4, width: 8, height: 8)), with: .color(.teal))
                    }
                }
                if let target {
                    let q = p(target.x,target.y)
                    context.fill(Path(ellipseIn: .init(x: q.x-11, y: q.y-11, width: 22, height: 22)), with: .color(.orange))
                    context.stroke(Path(ellipseIn: .init(x: q.x-16, y: q.y-16, width: 32, height: 32)), with: .color(.orange), lineWidth: 2)
                }
            }
        }.accessibilityLabel(target.map { "목표 위치: 위에서 \(Int(($0.y*Double(gridSize-1)).rounded())+1)행, 왼쪽에서 \(Int(($0.x*Double(gridSize-1)).rounded())+1)열. 실제 추정 위치가 아닙니다." } ?? "배경 측정 · 펜슬을 멀리 치우세요")
    }
}

struct EdgeDiagram: View {
    var edge: StudyEdge?
    var target: Point2D?
    var aspect: Double
    var body: some View {
        GeometryReader { geo in
            Canvas { context, _ in
                let w = min(geo.size.width - 100, (geo.size.height - 76) * aspect)
                let r = CGRect(x: (geo.size.width - w)/2, y: 35, width: w, height: w/aspect)
                func p(_ point: Point2D) -> CGPoint { .init(x: r.minX + point.x*r.width, y: r.minY + point.y*r.height) }
                context.stroke(Path(r), with: .color(.gray.opacity(0.35)), lineWidth: 2)
                context.draw(Text("위 · iPad 쪽").font(.caption), at: .init(x: r.midX, y: 12))
                context.draw(Text("아래 · 사용자 쪽").font(.caption), at: .init(x: r.midX, y: r.maxY + 25))
                if let edge {
                    var line = Path(); line.move(to: p(edge.point(0))); line.addLine(to: p(edge.point(1)))
                    context.stroke(line, with: .color(.teal), lineWidth: 5)
                    for i in 0...4 {
                        let q = p(edge.point(Double(i)/4))
                        context.fill(Path(ellipseIn: .init(x: q.x-5, y: q.y-5, width: 10, height: 10)), with: .color(.teal))
                        let horizontal = edge == .top || edge == .bottom
                        context.draw(Text("\(i*25)%").font(.caption2), at: .init(x: q.x + (horizontal ? 0 : -28), y: q.y + (horizontal ? 16 : 0)))
                    }
                } else {
                    context.draw(Text("펜슬을 멀리 치우세요").font(.headline), at: .init(x: r.midX, y: r.midY))
                }
                if let target {
                    let q = p(target)
                    context.stroke(Path(ellipseIn: .init(x: q.x-13, y: q.y-13, width: 26, height: 26)), with: .color(.orange), lineWidth: 4)
                }
            }
        }.accessibilityLabel(edge?.title ?? "펜슬을 멀리 두는 배경 측정")
    }
}
