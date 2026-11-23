import SwiftUI

struct PrintedGridStudyView: View {
    @ObservedObject var collector: Collector
    @State private var showSetup = false
    @State private var showLibrary = false
    @State private var confirmEnd = false
    @State private var confirmNew = false
    var batch: PrintedGridBatch { collector.printedBatch ?? collector.nextPrintedBatch }
    var spec: TrialSpec? { collector.activeTrial?.spec ?? collector.currentSpec }
    var finished: Bool { collector.printedBatch != nil && !collector.plan.isEmpty && collector.currentSpec == nil }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("스윗 스팟 · 273점 수집").font(.largeTitle.bold())
                            Text("50 × 30 mm · 간격 2.5 mm · 21열 × 13행").foregroundStyle(.secondary)
                            Text(collector.printedCampaign.pose.summary).font(.subheadline.bold()).foregroundStyle(.teal)
                        }
                        Spacer()
                        Text("\(collector.printedCompleted.count) / 39행 저장")
                            .font(.headline.monospacedDigit()).foregroundStyle(.teal)
                    }
                    ProgressView(value: Double(collector.printedCompleted.count), total: 39)
                    HStack {
                        Picker("측정 묶음", selection: Binding(get: { batch }, set: { collector.selectPrinted($0) })) {
                            ForEach(PrintedGridBatch.all) { item in
                                Text(item.title + (collector.printedCompleted[item.id] == nil ? "" : " ✓")).tag(item)
                            }
                        }.pickerStyle(.menu)
                        Spacer()
                        Button("미완료 행으로") { collector.selectPrinted(collector.nextPrintedBatch) }
                            .disabled(collector.printedCompleted.count == 39)
                    }.disabled(collector.sessionOpen || collector.isClosing)
                    if collector.sessionOpen && collector.printedBatch == nil {
                        Text("다른 수집 세션이 열려 있습니다. 해당 화면에서 저장·종료한 뒤 시작하세요.").foregroundStyle(.orange)
                    } else if finished {
                        completion
                    } else {
                        if !collector.printedReady {
                            VStack(alignment: .leading, spacing: 9) {
                                Text("종이와 iPad 고정 · 장치의 각도와 펜촉 높이 확인").font(.headline)
                                Text("위쪽(iPad 쪽)이 1행, 아래쪽이 13행입니다. 왼쪽부터 1–21열이며 중앙은 7행 11열입니다.")
                                Button("배치 확인하고 준비 완료") { showSetup = true }.buttonStyle(.borderedProminent)
                            }.padding(18).background(.teal.opacity(0.06), in: RoundedRectangle(cornerRadius: 14))
                        }
                        measurement
                    }
                    DisclosureGroup("전체 측정 순서 · 쉬는 방법") {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("같은 φ=0°·θ=90°·α=0°·높이 0 mm로 3회차까지 수집합니다. 2회차는 먼저 1회차 모델로 평가하고, 3회차는 1+2회차 모델로 먼저 평가한 뒤 학습에 합칩니다.")
                            Text("1회차: 1 → 13행\n2회차: 13 → 1행, 각 행의 이동 방향 반대\n3회차: 7, 1, 13, 4, 10, 2, 12, 5, 9, 3, 11, 6, 8행")
                            Text("한 행: 시작 배경(수동) → 첫 점에 놓고 연속 시작 → 이동·준비 3초 + 정지 2초로 21점 자동 진행 → 종료 배경(수동) → 저장. 배경은 준비 3초 + 측정 10초입니다.")
                            Text("자동 진행 기준 행당 약 2분 20초이며, 처음 위치 맞춤·배경 이동·휴식 시간은 별도입니다. 자동 저장된 행 사이에 쉬세요. 잠금·앱 종료·중간 종료로 끊긴 행은 시작 배경부터 다시 재며, 완료된 다른 행은 유지합니다.")
                            Text("인쇄 도면을 100% 크기로 사용하세요. 종이·iPad·스탠드·케이블을 옮기거나 펜 자세를 바꿨다면 ‘새 배치로 시작’을 사용합니다. 이전 파일은 보존됩니다.")
                            Text("실시간 테스트에는 첫 회차 273점으로 만든 임시 모델이 적용됐습니다. 2회차 13행이 끝나면 먼저 분석을 요청하세요. 3회차는 평가를 마친 새 모델을 적용한 뒤 시작합니다.")
                        }.font(.subheadline).padding(.vertical, 8)
                    }
                    HStack {
                        Label(collector.sensorFresh ? "자력계 수신 중" : "자력계 연결 대기", systemImage: "waveform.path")
                        if let field = collector.field {
                            Text(String(format: "Bx %.1f · By %.1f · Bz %.1f µT", field.x, field.y, field.z)).monospacedDigit()
                        }
                    }.font(.footnote)
                    Text(collector.ipadInclinationDegrees.map { String(format: "iPad 화면 경사 %.1f° · 수평 0° / 직립 90° · 중력 센서", $0) } ?? "iPad 경사각 · 동작 센서 수신 대기")
                        .font(.footnote.monospacedDigit())
                    if collector.deviceMoving {
                        Text("iPad 움직임이 감지됐습니다. 배치가 바뀌었다면 이 행을 중단하고 새 배치로 시작하세요.").foregroundStyle(.orange)
                    }
                    Text(collector.notice).font(.footnote).foregroundStyle(.secondary)
                    Text("기록하는 IMU는 iPad의 센서입니다. 책상 위 Pencil의 기울기·축 회전·실제 높이는 측정하지 않습니다. 홀더는 자세를 유지하는 용도이며 점의 좌표는 사람이 확인한 표식 위치입니다.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(24).frame(maxWidth: 1000).frame(maxWidth: .infinity)
            }.background(Color(uiColor: .systemGroupedBackground))
                .safeAreaInset(edge: .bottom) {
                    if !finished && collector.printedBatch != nil {
                        controls.padding(.horizontal, 24).padding(.vertical, 12)
                            .frame(maxWidth: .infinity).background(.regularMaterial)
                    }
                }
                .navigationTitle("MagAir Research · 도면 수집 1.16.2")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItemGroup(placement: .topBarTrailing) {
                        Button("저장 기록") { collector.refreshLibrary(); showLibrary = true }
                            .disabled(collector.recording || collector.isClosing)
                        Button("배치 조건") { showSetup = true }.disabled(collector.sessionOpen || collector.isClosing)
                        Menu("수집 관리") {
                            Button("새 배치로 시작") { confirmNew = true }.disabled(collector.sessionOpen || collector.isClosing)
                            if collector.sessionOpen && collector.printedBatch != nil {
                                Button("이 행 중간 종료", role: .destructive) { confirmEnd = true }
                            }
                        }
                    }
                }
        }
        .onAppear {
            if !collector.sessionOpen && collector.printedBatch == nil { collector.selectPrinted(collector.nextPrintedBatch) }
            #if DEBUG && targetEnvironment(simulator)
            // Visual QA only: no fake sensor stream and no stored measurement.
            if ProcessInfo.processInfo.arguments.contains("--preview-printed-target") {
                collector.selectPrinted(.init(pass: 1, row: 7)); collector.planIndex = 11
            }
            if ProcessInfo.processInfo.arguments.contains("--preview-printed-setup") { showSetup = true }
            #endif
        }
        .sheet(isPresented: $showSetup) { PrintedGridSetupView(collector: collector) }
        .onDisappear {
            if collector.printedSequence.running { collector.abortTrial(reason: "left_printed_screen") }
        }
        .sheet(isPresented: $showLibrary) { LibraryView(collector: collector) }
        .alert("측정 안내", isPresented: Binding(get: { collector.errorMessage != nil }, set: { if !$0 { collector.errorMessage = nil } })) {
            Button("확인", role: .cancel) { collector.errorMessage = nil }
        } message: { Text(collector.errorMessage ?? "") }
        .confirmationDialog("이 행을 중간 종료할까요?", isPresented: $confirmEnd, titleVisibility: .visible) {
            Button("원본 저장 후 이 행 중단", role: .destructive) { collector.endSession(status: "partial_printed_grid") }
        } message: { Text("현재 행은 미완료로 남고 시작 배경부터 다시 측정합니다. 이미 완료된 다른 행은 유지합니다.") }
        .confirmationDialog("새 배치의 수집을 시작할까요?", isPresented: $confirmNew, titleVisibility: .visible) {
            Button("이전 파일 보존 · 새 39묶음 시작") { collector.newPrintedCampaign(); showSetup = true }
        } message: { Text("새 수집 번호로 구분해 이전 배치와 섞이지 않게 합니다. 현재 배치를 유지하고 있다면 취소하세요.") }
    }

    private var measurement: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("\(batch.pass)/3회차 · \(batch.row)행 · \(batch.direction)").font(.title3.bold())
                Spacer()
                Text("항목 \(collector.planIndex + 1)/23").monospacedDigit()
            }
            if let spec {
                if spec.kind.isBaseline {
                    Label(spec.edgeAction == "before" ? "시작 배경 · 펜을 멀리" : "종료 배경 · 펜을 멀리", systemImage: "arrow.up.right")
                        .font(.title2.bold()).padding(.vertical, 16)
                } else {
                    HStack(alignment: .firstTextBaseline) {
                        Text("\(spec.gridRow ?? 0)행  \(spec.gridColumn ?? 0)열").font(.system(size: 34, weight: .bold, design: .rounded))
                        Spacer()
                        if let mm = spec.nominalPointMM {
                            Text("왼쪽에서 \(mm.x, specifier: "%.1f") mm · 위에서 \(mm.y, specifier: "%.1f") mm")
                                .font(.subheadline.monospacedDigit())
                        }
                    }
                    PrintedGridDiagram(row: batch.row, column: spec.gridColumn).frame(height: 350)
                }
                Text(spec.instruction ?? "").fixedSize(horizontal: false, vertical: true)
            }
            Toggle("행 안 자동 진행", isOn: $collector.printedSequence.enabled).disabled(collector.recording)
            Toggle("준비·측정·이동 안내음", isOn: $collector.soundEnabled).font(.footnote)
            Text("짧은 음: 준비 · 높은 음: 정지 측정 시작 · 두 번 음: 다음 점으로 이동. 이동이 늦거나 잘못 놓았으면 일시정지 후 다시 측정하세요.").font(.footnote)
            if let reason = collector.printedEvaluationBlockReason { Text(reason).foregroundStyle(.orange) }
            Text("주황색은 놓을 위치 안내입니다. 자동 진행 중 표식에 실제로 도착했는지는 감지하지 못합니다. 안내에 맞춰 움직이고 준비가 부족하면 멈추세요.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(20).background(.background, in: RoundedRectangle(cornerRadius: 18))
    }

    private var controls: some View {
        HStack(spacing: 20) {
            VStack(alignment: .leading, spacing: 5) {
                Text(collector.phaseText).font(.headline).foregroundStyle(.teal)
                if collector.recording, let spec {
                    Text("남은 시간 \(max(0, (collector.activeTrial?.settleSeconds ?? spec.preparationSeconds ?? 3) + spec.duration - collector.elapsed), specifier: "%.0f")초").monospacedDigit()
                    ProgressView(value: collector.progress)
                } else if !collector.sensorFresh {
                    Text("자력계 연결 대기").font(.caption).foregroundStyle(.orange)
                } else if let spec, spec.point != nil {
                    Text(spec.locationName).font(.subheadline)
                }
            }
            Spacer(minLength: 0)
            if collector.recording {
                Button("일시정지 · 이 점 다시", role: .destructive) { collector.abortTrial() }.buttonStyle(.bordered)
            } else {
                if collector.sessionOpen && collector.planIndex > 0 {
                    Button("직전 다시") { collector.redoPrevious() }.buttonStyle(.bordered)
                }
                Button(!collector.printedReady ? "먼저 배치 확인" : (spec?.kind.isBaseline == true ? "펜을 멀리 두었음 · 배경 시작" : (collector.printedSequence.enabled ? "이 점에 놓았음 · 연속 시작" : "이 점에 놓았음 · 측정 시작"))) {
                    if !collector.printedReady { showSetup = true } else { collector.startTrial() }
                }.buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(collector.isClosing || spec == nil || collector.printedEvaluationBlockReason != nil || (collector.printedReady && !collector.sensorFresh))
            }
        }.frame(maxWidth: 950)
    }

    private var completion: some View {
        VStack(alignment: .leading, spacing: 14) {
            if collector.isClosing {
                ProgressView("이 행을 저장하는 중입니다")
            } else if collector.printedCompleted[batch.id] != nil {
                Label("\(batch.row)행 저장 완료 · 쉬어도 됩니다", systemImage: "checkmark.circle.fill").font(.title2.bold()).foregroundStyle(.teal)
                if collector.printedCompleted.count == 39 {
                    Text("273점 × 3회 수집을 모두 마쳤습니다. 수집 완료라고 알려주세요. 자료를 가져와 분석하고 새 모델을 적용하겠습니다.")
                } else {
                    Text("배치를 그대로 유지하세요. 다음 행은 새 시작 배경부터 측정합니다.")
                    Button("다음 미완료: \(collector.nextPrintedBatch.title)") { collector.selectPrinted(collector.nextPrintedBatch) }
                        .buttonStyle(.borderedProminent).controlSize(.large)
                }
                Button("이 행 처음부터 다시 측정") { collector.selectPrinted(batch) }.buttonStyle(.bordered)
            } else {
                Text("완료 여부를 확인하지 못했습니다. ‘저장 기록’과 오류 안내를 확인해 주세요. 원본이 남아 있을 수 있으니 재측정 전에 분석을 요청하세요.").foregroundStyle(.orange)
                Button("이 행 다시 준비") { collector.selectPrinted(batch) }.buttonStyle(.borderedProminent)
            }
            Text("맥북에 연결되어 있으면 직접 자료를 가져올 수 있습니다. ZIP을 하나씩 옮길 필요는 없습니다.").font(.footnote)
        }.padding(22).background(.background, in: RoundedRectangle(cornerRadius: 18))
    }
}

struct PrintedGridSetupView: View {
    @ObservedObject var collector: Collector
    @Environment(\.dismiss) private var dismiss
    @State private var setup = PrintedGridCampaign().setup
    @State private var checked = false
    @State private var pose = PrintedGridPose()
    var body: some View {
        NavigationStack {
            Form {
                Section("이번 도면") {
                    Text("A4 가로 · 실제 크기 100% · 스윗 스팟 50 × 30 mm")
                    Text("왼쪽 아래 오프셋: 용지 왼쪽에서 115 mm, 아래에서 55 mm. 앱의 1행은 사각형의 위쪽(iPad 쪽), 1열은 왼쪽입니다.")
                    Text("한 배치에서는 φ·θ·α·높이를 고정합니다. 기본값은 φ=0°, θ=90°, α=0°, 높이=0 mm·접촉입니다. 이번에는 같은 조건으로 3회차까지 이어갑니다.")
                }
                Section("펜 장치 설정 · 수집 라벨") {
                    HStack {
                        Text("φ · 홀더 회전각 (°)"); Spacer()
                        TextField("0–360", value: $pose.phiDegrees, format: .number).keyboardType(.decimalPad).multilineTextAlignment(.trailing)
                    }
                    Text("위에서 볼 때 시계방향 +, 기존 데모의 홀더 방향이 0°. 책상 수직축을 중심으로 홀더 전체를 회전합니다. 펜 자체의 축 회전과 다릅니다. 360°는 0°로 저장합니다.").font(.footnote)
                    HStack {
                        Text("θ · 지면과의 각도 (°)"); Spacer()
                        TextField("0–90", value: $pose.thetaDegrees, format: .number).keyboardType(.decimalPad).multilineTextAlignment(.trailing)
                    }
                    Text("α=0일 때 수평 0° · 수직 90°. α를 바꿔도 이 θ 라벨을 최종 지면 각도로 다시 계산하지 않습니다.").font(.footnote)
                    HStack {
                        Text("α · 옆 기울임 (°)"); Spacer()
                        TextField("−90~+90", value: $pose.alphaDegrees, format: .number)
                            .keyboardType(.numbersAndPunctuation).multilineTextAlignment(.trailing)
                    }
                    Text("초기 펜의 책상 투영선을 경첩 축으로 옆으로 기울입니다. 장치 기준 오른쪽이 +이며 이 기준은 φ와 함께 돌아갑니다. θ=90°에서는 투영선 대신 장치 기준선을 사용합니다.").font(.footnote)
                    if pose.alphaLabelSource?.hasPrefix("user_confirmed_retrospective") == true {
                        Text("기존 첫 회차 α=0°는 사용자 확인으로 보완한 라벨입니다. 원본 측정 파일은 변경하지 않았습니다.").font(.footnote).foregroundStyle(.secondary)
                    }
                    Picker("펜촉 상태", selection: Binding(get: { pose.tipContact }, set: { pose.tipContact = $0; if $0 { pose.tipHeightMM = 0 } })) {
                        Text("표면 접촉").tag(true)
                        Text("공중").tag(false)
                    }.pickerStyle(.segmented)
                    HStack {
                        Text("펜촉의 지면 높이 (mm)"); Spacer()
                        TextField("0 이상", value: $pose.tipHeightMM, format: .number).keyboardType(.decimalPad).multilineTextAlignment(.trailing)
                            .disabled(pose.tipContact)
                    }
                    TextField("φ=0 기준 방향 / 펜 고정 설명", text: $pose.referenceNote, axis: .vertical).lineLimit(2...5)
                    if pose.needsHingeReference {
                        TextField("φ=0의 경첩 기준선 / θ를 낮출 때 기울어지는 쪽 (필수)", text: $pose.tiltDirectionAtPhiZero, axis: .vertical)
                    }
                    Text("장치에서 맞춘 값을 사람이 입력합니다. 실제 펜의 각도·높이·접촉을 센서로 읽은 값은 아닙니다. 공중에서는 펜촉의 수직 아래에 해당하는 표식을 맞춥니다.").font(.footnote)
                }.disabled(collector.printedCampaign.hasStarted)
                Section("iPad 경사각 · 센서 자동 기록") {
                    Text(collector.ipadInclinationDegrees.map { String(format: "현재 화면 경사 %.1f°", $0) } ?? "동작 센서 수신 대기")
                        .font(.title3.monospacedDigit())
                    Text("화면 평면과 중력 기준 수평면 사이의 각도입니다. 눕히면 0°, 세우면 90°입니다. 행 시작 값과 측정 중 연속 값을 기록합니다. iPad 높이는 센서로 측정하지 않으므로 아래 메모에 적으세요.").font(.footnote)
                }
                Section("배치 기록") {
                    TextField("iPad 각도 / 높이 설명", text: $setup.standAngle)
                    TextField("홀더 / 충전 / 케이스 / 주변 물체 설명", text: $setup.environment, axis: .vertical).lineLimit(3...6)
                    if collector.printedCampaign.hasStarted {
                        Text("이 배치는 이미 수집을 시작해 조건이 고정됐습니다. 배치가 달라졌다면 닫은 뒤 수집 관리 → 새 배치로 시작을 선택하세요.").font(.footnote)
                    }
                }.disabled(collector.printedCampaign.hasStarted)
                Section {
                    Toggle("인쇄 크기·방향과 고정 상태를 확인했음", isOn: $checked)
                    Text("완료된 행 이후 쉬었다 이어갈 때에도 종이·iPad·스탠드·케이블·펜 자세가 같아야 합니다. 이동하는 홀더는 배경 측정 때 펜슬과 함께 같은 먼 위치에 두세요.")
                    if !pose.readyForCollection {
                        Text("φ 0–360°, θ 0–90°, α −90~+90°를 입력하세요. 접촉 높이는 0 mm, 공중 높이는 0보다 커야 합니다. θ<90° 또는 α≠0°이면 φ=0에서의 경첩 기준선도 적으세요.").foregroundStyle(.orange)
                    }
                    Button("이 조건으로 준비 완료") { collector.confirmPrintedSetup(setup, pose: pose); dismiss() }
                        .buttonStyle(.borderedProminent).disabled(!checked || !pose.readyForCollection)
                }
            }.navigationTitle("스윗 스팟 배치 확인")
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } } }
        }.onAppear { setup = collector.printedCampaign.setup; pose = collector.printedCampaign.pose }
    }
}

struct PrintedGridDiagram: View {
    var row: Int
    var column: Int?
    var body: some View {
        GeometryReader { geo in
            Canvas { context, _ in
                let width = max(10, min(geo.size.width - 76, (geo.size.height - 70)*5/3))
                let rect = CGRect(x: (geo.size.width-width)/2, y: 35, width: width, height: width*3/5)
                func p(_ c: Int, _ r: Int) -> CGPoint {
                    .init(x: rect.minX + Double(c-1)*width/20, y: rect.minY + Double(r-1)*rect.height/12)
                }
                context.draw(Text("위 · iPad 쪽 / 50 mm").font(.caption.bold()), at: .init(x: rect.midX, y: 3))
                context.draw(Text("아래 · 사용자 쪽 / 중앙 7행 11열").font(.caption), at: .init(x: rect.midX, y: rect.maxY+26))
                var line = Path(); line.move(to: p(1,row)); line.addLine(to: p(21,row))
                context.stroke(line, with: .color(.teal.opacity(0.3)), lineWidth: 8)
                context.stroke(Path(rect), with: .color(.red), lineWidth: 1.5)
                for c in 1...21 {
                    context.draw(Text("\(c)").font(.system(size: 11, weight: c == column ? .bold : .regular)), at: .init(x: p(c,1).x, y: rect.minY-13))
                }
                for r in 1...13 {
                    context.draw(Text("\(r)행").font(.system(size: 11, weight: r == row ? .bold : .regular)), at: .init(x: rect.minX-24, y: p(1,r).y))
                    for c in 1...21 {
                        let q = p(c,r)
                        context.fill(Path(ellipseIn: CGRect(x: q.x-2.5, y: q.y-2.5, width: 5, height: 5)), with: .color(.black))
                    }
                }
                if let column {
                    let q = p(column,row)
                    context.fill(Path(ellipseIn: CGRect(x: q.x-6, y: q.y-6, width: 12, height: 12)), with: .color(.orange))
                    context.stroke(Path(ellipseIn: CGRect(x: q.x-10, y: q.y-10, width: 20, height: 20)), with: .color(.orange), lineWidth: 2)
                }
            }
        }.accessibilityLabel("21열 13행 도면. 위에서 \(row)행, 왼쪽에서 \(column ?? 0)열이 목표 위치입니다.")
    }
}
