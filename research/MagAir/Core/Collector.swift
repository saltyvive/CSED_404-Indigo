import Foundation
import Combine
import CoreMotion
import UIKit
import AudioToolbox

struct FieldSample: Identifiable {
    var t: Double
    var x: Double
    var y: Double
    var z: Double
    var id: Double { t }
    var magnitude: Double { sqrt(x*x + y*y + z*z) }
}

final class Collector: ObservableObject {
    let liveTester = LiveTester()
    let edgeLiveTester = EdgeLiveTester()
    let gridLiveTester = GridLiveTester()
    @Published var setup = Setup()
    @Published var selected: ProtocolKind = .baselineBefore
    @Published var edgeScenario: EdgeScenario?
    @Published var printedBatch: PrintedGridBatch?
    @Published var printedCampaign = PrintedGridCampaign()
    @Published var printedCompleted: [String: String] = [:] // batch ID -> durable session ID
    @Published var printedReady = false
    var nextPrintedBatch: PrintedGridBatch {
        PrintedGridBatch.all.first { printedCompleted[$0.id] == nil } ?? PrintedGridBatch.all[0]
    }
    @Published var denseCompleted = Set(UserDefaults.standard.stringArray(forKey: "denseGrid.completed.v1") ?? [])
    var nextDenseCollection: EdgeScenario {
        EdgeScenario.denseTraining.first { !denseCompleted.contains($0.rawValue) } ?? .grid9Train1A
    }
    @Published var manifest: SessionManifest?
    @Published var activeTrial: TrialRecord?
    @Published var plan: [TrialSpec] = []
    @Published var planIndex = 0
    @Published var elapsed = 0.0
    @Published var field: FieldSample?
    @Published var history: [FieldSample] = []
    @Published var actualHz = 0.0
    @Published var gravity: [Double] = []
    @Published var ipadInclinationDegrees: Double?
    private var latestInclination: IPadInclinationSnapshot?
    @Published var deviceMoving = false
    @Published var notice = "센서를 확인하고 있습니다."
    @Published var errorMessage: String?
    @Published var library: [URL] = []
    @Published var archiveURL: URL?
    @Published var isExporting = false
    @Published var isClosing = false
    @Published var soundEnabled = true
    @Published var sensorFresh = false
    @Published var pencilStatus = "화면 감지 없음 · 책상 영역에서는 정상"

    let motion = CMMotionManager()
    private var store: SessionStore?
    private var timer: Timer?
    private var sensorTimes: [Double] = []
    private var lastDisplay = 0.0
    private var lastCue = ""
    private var blockNumber = 0
    private var attemptNumber = 0
    private var lastWarning = 0.0
    private var lastCheckpoint = 0.0
    private var counts: [String: Int] = [:]
    private var waitingForTail = false
    private var lastPencilEvent = 0.0
    var now: Double { ProcessInfo.processInfo.systemUptime }
    var recording: Bool { activeTrial != nil }
    var sessionOpen: Bool { store != nil }
    var capabilities: [String: Bool] {
        ["magnetometer": motion.isMagnetometerAvailable, "accelerometer": motion.isAccelerometerAvailable,
         "gyroscope": motion.isGyroAvailable, "device_motion": motion.isDeviceMotionAvailable]
    }
    var currentSpec: TrialSpec? { plan.indices.contains(planIndex) ? plan[planIndex] : nil }
    var startBlockReason: String? {
        if isClosing { return "이전 세션을 저장하고 있습니다." }
        if !setup.confirmed { return "먼저 ‘실험 조건 확인’을 누르고 ‘이 조건으로 준비 완료’를 눌러 주세요." }
        if !sensorFresh { return "자력계 데이터를 기다리고 있습니다. 아래 센서 상태를 확인하세요." }
        if sessionOpen && currentSpec == nil { return "이 동작은 완료됐습니다. 왼쪽 목록에서 다음 동작을 선택하세요." }
        return nil
    }
    var guidePoint: Point2D? {
        if let trial = activeTrial { return trial.annotation(at: min(now, trial.plannedEnd - 0.001)).point }
        return currentSpec?.point ?? selected.path.first
    }
    var phaseText: String {
        guard let trial = activeTrial else {
            if !setup.confirmed { return "실험 조건을 확인해 주세요" }
            if !sessionOpen { return "준비되면 측정 시작을 누르세요" }
            return currentSpec == nil ? "이 동작 완료 · 다음 동작을 선택하세요" : "위치를 잡고 시작하세요"
        }
        if waitingForTail { return "마지막 센서 데이터를 저장하는 중" }
        if now < trial.activeStart { return "준비  \(max(1, Int(ceil(trial.activeStart - now))))" }
        let activeElapsed = now - trial.activeStart
        func remaining(_ end: Double) -> Int { max(1, Int(ceil(end - activeElapsed))) }
        switch trial.annotation(at: now).phase {
        case "pose_reference": return "펜 끝 고정 · 수직 / 로고 왼쪽으로 정지"
        case "pose_change": return trial.spec.edgeAction == "tilt" ? "펜 끝 고정 · 사용자 쪽으로 조금 기울이세요" : "펜 끝 고정 · 축 방향만 조금 돌리세요"
        case "pose_return": return "원래 수직 자세 / 로고 왼쪽으로 돌아오세요"
        case "hold": return "그대로 정지하세요"
        case "baseline": return "펜슬을 멀리 두세요"
        case "contact_instruction": return "중앙 · 표면에 가볍게 대세요"
        case "lift_instruction": return "중앙 · 조금 들어 올리세요"
        case "roll_instruction": return "위치는 고정 · 축만 돌렸다 돌아오세요"
        case "surface_hold": return "책상에 접촉 · 정지 \(remaining(3))초"
        case "lift_transition": return "수직으로 약 1cm 들어 올리세요 · \(remaining(5))초"
        case "air_hold": return "약 1cm 공중 · 정지 \(remaining(8))초"
        case "lower_transition": return "같은 위치로 내려놓으세요 · \(remaining(10))초"
        case "surface_return": return "다시 책상에 접촉 · 정지 \(remaining(13))초"
        default:
            if trial.spec.isManual { return "편한 속도로 왕복 · 돌아온 뒤 완료를 누르세요" }
            return trial.spec.kind.isAirPath ? "약 1cm 공중에서 테두리를 따라가세요" : "점을 따라 움직이세요"
        }
    }
    var progress: Double {
        guard let trial = activeTrial else { return 0 }
        return min(1, max(0, (elapsed - trial.settleSeconds) / trial.spec.duration))
    }

    init() {
        if let data = UserDefaults.standard.data(forKey: "printedGrid.campaign.v1"),
           var campaign = try? JSONDecoder().decode(PrintedGridCampaign.self, from: data) {
            campaign.pose = FixturePoseAnnotations.bundled.resolve(campaign.pose, campaignID: campaign.id)
            printedCampaign = campaign
        }
        if let data = UserDefaults.standard.data(forKey: "setup.v1"), let saved = try? JSONDecoder().decode(Setup.self, from: data) {
            setup = saved
            setup.confirmed = false
        }
        // One-time correction of the initial portrait default to the user's confirmed geometry.
        if !UserDefaults.standard.bool(forKey: "wideRectangleConfirmed.v1") {
            setup.aspect = 1.5
            if let data = try? JSONEncoder().encode(setup) {
                UserDefaults.standard.set(data, forKey: "setup.v1")
            }
            UserDefaults.standard.set(true, forKey: "wideRectangleConfirmed.v1")
        }
        refreshLibrary()
        startSensors()
        timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in self?.tick() }
    }

    func startSensors() {
        guard !motion.isMagnetometerActive else { return }
        let interval = 1.0 / setup.requestedHz
        motion.magnetometerUpdateInterval = interval
        motion.accelerometerUpdateInterval = interval
        motion.gyroUpdateInterval = interval
        motion.deviceMotionUpdateInterval = interval
        if motion.isMagnetometerAvailable {
            motion.startMagnetometerUpdates(to: .main) { [weak self] data, error in
                guard let self else { return }
                if let error { self.sensorError(error, channel: "magnetometer"); return }
                guard let data else { return }
                let v = data.magneticField
                self.liveTester.receive(timestamp: data.timestamp, field: [v.x, v.y, v.z])
                self.edgeLiveTester.receive(timestamp: data.timestamp, field: [v.x, v.y, v.z])
                self.gridLiveTester.receive(timestamp: data.timestamp, field: [v.x, v.y, v.z])
                self.receive("magnetometer", timestamp: data.timestamp, values: [v.x, v.y, v.z])
                self.sensorTimes.append(data.timestamp)
                self.sensorTimes.removeAll { $0 < data.timestamp - 2 }
                if self.now - self.lastDisplay >= 0.1 {
                    self.lastDisplay = self.now
                    let sample = FieldSample(t: data.timestamp, x: v.x, y: v.y, z: v.z)
                    self.field = sample
                    self.history.append(sample)
                    self.history.removeAll { $0.t < sample.t - 12 }
                    if let first = self.sensorTimes.first, let last = self.sensorTimes.last, last > first {
                        self.actualHz = Double(self.sensorTimes.count - 1) / (last - first)
                    }
                }
            }
            notice = "센서 연결 중 · 실제 수신률을 확인하세요."
        } else {
            notice = "자력계가 없습니다. 시뮬레이터에서는 화면만 확인할 수 있습니다."
        }
        if motion.isAccelerometerAvailable {
            motion.startAccelerometerUpdates(to: .main) { [weak self] data, error in
                if let error { self?.sensorError(error, channel: "accelerometer"); return }
                guard let data else { return }
                self?.receive("accelerometer", timestamp: data.timestamp, values: [data.acceleration.x, data.acceleration.y, data.acceleration.z])
            }
        }
        if motion.isGyroAvailable {
            motion.startGyroUpdates(to: .main) { [weak self] data, error in
                if let error { self?.sensorError(error, channel: "gyroscope"); return }
                guard let data else { return }
                self?.receive("gyroscope", timestamp: data.timestamp, values: [data.rotationRate.x, data.rotationRate.y, data.rotationRate.z])
            }
        }
        if motion.isDeviceMotionAvailable {
            motion.startDeviceMotionUpdates(using: .xArbitraryZVertical, to: .main) { [weak self] data, error in
                guard let self else { return }
                if let error { self.sensorError(error, channel: "device_motion"); return }
                guard let d = data else { return }
                let g = d.gravity, a = d.userAcceleration, r = d.rotationRate, q = d.attitude.quaternion
                let values = [g.x, g.y, g.z, a.x, a.y, a.z, r.x, r.y, r.z, q.x, q.y, q.z, q.w]
                let inclination = ipadScreenInclination(gravity: [g.x, g.y, g.z])
                if values.allSatisfy(\.isFinite) {
                    self.appendEvent("device_motion", timestamp: d.timestamp, columns: values.map(number) + [inclination.map(number) ?? ""])
                }
                self.latestInclination = inclination.map { .init(degrees: $0, gravity: [g.x,g.y,g.z], sensorUptime: d.timestamp) }
                let moving = sqrt(a.x*a.x + a.y*a.y + a.z*a.z) > 0.03 || sqrt(r.x*r.x + r.y*r.y + r.z*r.z) > 0.05
                if moving { self.liveTester.deviceMoved(); self.edgeLiveTester.deviceMoved(); self.gridLiveTester.deviceMoved() }
                if self.deviceMoving != moving { self.deviceMoving = moving }
                if self.gravity.isEmpty || self.now - self.lastDisplay < 0.03 {
                    self.gravity = [g.x, g.y, g.z]; self.ipadInclinationDegrees = inclination
                }
                if moving && self.recording && self.now - self.lastWarning > 3 {
                    self.lastWarning = self.now
                    self.manifest?.warnings.append("iPad movement at uptime \(number(d.timestamp)); inspect device_motion.csv")
                }
            }
        }
    }

    func stopSensors() {
        liveTester.invalidate("센서가 중단됐습니다 · 배경을 다시 맞추세요")
        edgeLiveTester.invalidate("센서가 중단됐습니다 · 배경을 다시 맞추세요")
        gridLiveTester.invalidate("센서가 중단됐습니다 · 배경을 다시 맞추세요")
        motion.stopMagnetometerUpdates(); motion.stopAccelerometerUpdates()
        motion.stopGyroUpdates(); motion.stopDeviceMotionUpdates()
        sensorFresh = false
        sensorTimes = []
        ipadInclinationDegrees = nil; latestInclination = nil
    }

    private func sensorError(_ error: Error, channel: String) {
        let message = "\(channel): \(error.localizedDescription)"
        notice = message
        manifest?.warnings.append(message)
        if channel == "magnetometer" { abortTrial(reason: "magnetometer_error") }
    }

    private func receive(_ channel: String, timestamp: Double, values: [Double]) {
        guard values.allSatisfy({ $0.isFinite }) else { return }
        appendEvent(channel, timestamp: timestamp, columns: values.map(number))
    }

    func receivePencil(_ event: PencilEvent) {
        if event.type != "touch_estimate_update" {
            lastPencilEvent = now
            if event.valid, let altitude = event.altitude {
                pencilStatus = String(format: "%@ · 화면 기준 기울기 %.1f°", event.type == "hover" ? "호버" : "접촉", altitude * 180 / .pi)
            } else {
                pencilStatus = "화면 감지 없음 · 책상 영역에서는 정상"
            }
        }
        appendEvent("pencil_events", timestamp: event.timestamp, columns: event.columns)
    }

    private func appendEvent(_ channel: String, timestamp: Double, columns: [String]) {
        guard let session = manifest, let store, timestamp >= session.anchorUptime else { return }
        counts[channel, default: 0] += 1
        // Label using sensor event time, never the callback arrival time or UI animation frame.
        let trial = session.trials.last { timestamp >= $0.startUptime && timestamp < ($0.endUptime ?? $0.plannedEnd) }
        let annotation = trial?.annotation(at: timestamp)
        let targetX = annotation?.point.map { number($0.x) } ?? ""
        let targetY = annotation?.point.map { number($0.y) } ?? ""
        let repetition = trial.map { String($0.spec.repetition) } ?? ""
        let height = trial?.instructedHeightMM(at: timestamp)
        let prefix: [String] = [number(timestamp), number(session.anchorUnix + timestamp - session.anchorUptime), number(now),
                               trial?.spec.id ?? "", trial?.spec.kind.rawValue ?? "", trial?.spec.dataset ?? "",
                               repetition, trial?.spec.pointID ?? "", annotation?.phase ?? "idle",
                               targetX, targetY, annotation?.source ?? "none",
                               height.map(number) ?? "", height == nil ? "none" : "operator_instruction_unmeasured"]
        let poseLabels = trial?.spec.fixturePose?.csvLabels(phase: annotation?.phase ?? "idle") ?? Array(repeating: "", count: 6)
        store.append(stream: channel, fields: prefix + poseLabels + columns)
    }

    private func tick() {
        if latestInclination.map({ now - $0.sensorUptime > 1.5 }) ?? false { ipadInclinationDegrees = nil }
        liveTester.checkStale(now: now)
        edgeLiveTester.checkStale(now: now)
        gridLiveTester.checkStale(now: now)
        if now - lastPencilEvent > 1.0 && !pencilStatus.hasPrefix("화면 감지 없음") {
            pencilStatus = "화면 감지 없음 · 책상 영역에서는 정상"
        }
        let fresh = sensorTimes.last.map { now - $0 < 1.5 } ?? false
        if sensorFresh != fresh { sensorFresh = fresh }
        if sessionOpen && now - lastCheckpoint > 2 {
            lastCheckpoint = now
            checkpoint()
        }
        guard let trial = activeTrial else { return }
        elapsed = now - trial.startUptime
        if !fresh && now - trial.startUptime > 2 {
            abortTrial(reason: "magnetometer_stale")
            errorMessage = "자력계 데이터 수신이 끊겨 측정을 중단했습니다. 현재 지점을 다시 측정하세요."
            return
        }
        let cue: String
        if now < trial.activeStart { cue = "count-\(Int(ceil(trial.activeStart - now)))" }
        else if now >= trial.plannedEnd { cue = "end" }
        else if trial.spec.kind == .lift { cue = "lift-\(Int((now - trial.activeStart) / 3))" }
        else if trial.spec.kind == .cornersHeight { cue = trial.annotation(at: now).phase }
        else if trial.spec.kind == .edgePose { cue = trial.annotation(at: now).phase }
        else if trial.spec.isManual { cue = "self-paced" }
        else { cue = "active-\(Int((now - trial.activeStart) / 3))" }
        if cue != lastCue {
            lastCue = cue
            if soundEnabled { AudioServicesPlaySystemSound(cue == "end" ? 1057 : 1104) }
        }
        if trial.spec.isManual && trial.endUptime == nil && now >= trial.plannedEnd {
            abortTrial(reason: "manual_sweep_timeout")
            notice = "왕복 완료가 눌리지 않아 3분 후 중단했습니다. 같은 왕복을 다시 시작하세요."
            return
        }
        let end = trial.endUptime ?? trial.plannedEnd
        if now >= end { waitingForTail = true }
        // Allow delayed sensor callbacks to arrive before marking a trial completed.
        if now >= end + 0.4 { finishTrial() }
    }

    func beginSession() {
        guard !sessionOpen, !isClosing, setup.confirmed, sensorFresh else { return }
        if printedBatch != nil && (!printedReady || !printedCampaign.pose.readyForCollection) { return }
        do {
            var sys = utsname(); uname(&sys)
            let model = withUnsafePointer(to: &sys.machine) { pointer in
                pointer.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
            }
            let date = Date(), uptime = now
            let stamp = ISO8601DateFormatter().string(from: date)
            let id = "MagAir-" + stamp.replacingOccurrences(of: ":", with: "-") + "-" + UUID().uuidString.prefix(6)
            var session = SessionManifest(id: id, startedAt: stamp, anchorUptime: uptime, anchorUnix: date.timeIntervalSince1970,
                                          device: model, osVersion: UIDevice.current.systemVersion, setup: setup, availableSensors: capabilities)
            if let printedBatch {
                session.printedGrid = .init(campaignID: printedCampaign.id, batch: printedBatch, pose: printedCampaign.pose)
            }
            if let latestInclination, now - latestInclination.sensorUptime < 1.5 { session.ipadInclinationAtStart = latestInclination }
            let newStore = try SessionStore(manifest: session)
            newStore.onError = { [weak self] message in
                guard let self else { return }
                self.errorMessage = "파일 저장 실패: \(message). 측정을 중단했습니다. 저장 공간을 확인하세요."
                self.abortTrial(reason: "write_error")
                self.endSession(status: "write_error")
            }
            store = newStore; manifest = session; counts = [:]; blockNumber = 0
            if printedBatch != nil { printedCampaign.hasStarted = true; persistPrintedCampaign() }
            UserDefaults.standard.set(try JSONEncoder().encode(setup), forKey: "setup.v1")
            UIApplication.shared.isIdleTimerDisabled = true
            if let printedBatch {
                blockNumber += 1; plan = printedBatch.make(block: blockNumber, pose: printedCampaign.pose); planIndex = 0
            } else if let edgeScenario {
                blockNumber += 1; plan = edgeScenario.make(block: blockNumber); planIndex = 0
            } else { select(selected) }
            notice = "세션 생성 완료 · 동작별 시작 버튼을 누르세요."
        } catch { errorMessage = error.localizedDescription }
    }

    func select(_ kind: ProtocolKind) {
        guard !recording, !isClosing else { return }
        guard !sessionOpen || (edgeScenario == nil && printedBatch == nil) else { return }
        edgeScenario = nil
        printedBatch = nil
        selected = kind; blockNumber += 1; plan = TrialSpec.make(kind, block: blockNumber); planIndex = 0
        elapsed = 0
    }

    func selectEdge(_ scenario: EdgeScenario) {
        guard !recording, !isClosing, !sessionOpen else { return }
        printedBatch = nil
        edgeScenario = scenario; blockNumber += 1
        plan = scenario.make(block: blockNumber); planIndex = 0; elapsed = 0
        selected = .edgeBaseline
    }

    func selectPrinted(_ batch: PrintedGridBatch) {
        guard !recording, !isClosing, !sessionOpen, PrintedGridBatch.all.contains(batch) else { return }
        printedBatch = batch; edgeScenario = nil; blockNumber += 1
        setup = printedCampaign.setup; setup.confirmed = printedReady
        plan = batch.make(block: blockNumber, pose: printedCampaign.pose); planIndex = 0; elapsed = 0
        selected = .mapBaseline
    }

    func confirmPrintedSetup(_ proposed: Setup, pose: PrintedGridPose) {
        guard !sessionOpen, !isClosing, pose.readyForCollection else { return }
        if !printedCampaign.hasStarted {
            printedCampaign.setup = proposed
            printedCampaign.pose = pose.canonical
            printedCampaign.setup.widthMM = "50"; printedCampaign.setup.heightMM = "30"
            printedCampaign.setup.aspect = 5.0/3.0
            printedCampaign.setup.plane = pose.tipContact ? "책상/종이 표면 · 펜촉 접촉" : "책상 위 공중 · 펜촉의 수직 투영 위치"
            printedCampaign.setup.heightNote = pose.canonical.summary + " · 장치 설정값, 센서 실측 아님"
        }
        printedReady = true
        setup = printedCampaign.setup; setup.confirmed = true
        persistPrintedCampaign()
        if let printedBatch { selectPrinted(printedBatch) }
    }

    func newPrintedCampaign() {
        guard !sessionOpen, !isClosing else { return }
        printedCampaign = PrintedGridCampaign(); printedReady = false
        printedCompleted = [:]; persistPrintedCampaign()
        selectPrinted(PrintedGridBatch.all[0])
    }

    private func persistPrintedCampaign() {
        if let data = try? JSONEncoder().encode(printedCampaign) {
            UserDefaults.standard.set(data, forKey: "printedGrid.campaign.v1")
        }
    }

    func finishSweep() {
        guard var trial = activeTrial, trial.spec.isManual, trial.endUptime == nil,
              now >= trial.activeStart + 4 else { return }
        trial.endUptime = now
        activeTrial = trial; update(trial); waitingForTail = true
        checkpoint()
    }

    func startTrial() {
        if !sessionOpen { beginSession() }
        guard sessionOpen, sensorFresh, !recording, !isClosing, var spec = currentSpec else { return }
        attemptNumber += 1
        spec.id += "-a\(attemptNumber)"
        let trial = TrialRecord(spec: spec, startUptime: now)
        activeTrial = trial; manifest?.trials.append(trial); elapsed = 0
        waitingForTail = false; lastCue = ""
        checkpoint()
    }

    private func finishTrial() {
        guard var trial = activeTrial else { return }
        trial.endUptime = trial.endUptime ?? trial.plannedEnd; trial.status = "completed"
        update(trial)
        activeTrial = nil; waitingForTail = false; planIndex += 1
        checkpoint()
        notice = currentSpec == nil ? "이 동작이 끝났습니다. 다음 동작을 선택하세요." : "지점 저장 완료 · 다음 위치로 옮긴 뒤 시작하세요."
        if (edgeScenario != nil || printedBatch != nil) && currentSpec == nil { endSession() }
    }

    func abortTrial(reason: String = "user_cancelled") {
        guard var trial = activeTrial else { return }
        trial.endUptime = min(now, trial.plannedEnd); trial.status = "aborted"; trial.reason = reason
        update(trial); activeTrial = nil; waitingForTail = false; elapsed = 0
        checkpoint()
        notice = "현재 측정은 제외 처리되었습니다. 같은 지점에서 다시 시작하세요."
    }

    func redoPrevious() {
        guard !recording, sessionOpen, planIndex > 0 else { return }
        let previous = plan[planIndex - 1].id + "-a"
        guard let index = manifest?.trials.lastIndex(where: { $0.status == "completed" && $0.spec.id.hasPrefix(previous) }) else { return }
        manifest?.trials[index].status = "invalidated"
        manifest?.trials[index].reason = "user_requested_repeat"
        planIndex -= 1; checkpoint()
    }

    private func update(_ trial: TrialRecord) {
        guard let index = manifest?.trials.firstIndex(where: { $0.spec.id == trial.spec.id }) else { return }
        manifest?.trials[index] = trial
    }

    private func checkpoint() {
        manifest?.sensorCounts = counts
        if let manifest { store?.checkpoint(manifest) }
    }

    func endSession(status: String = "completed") {
        guard !isClosing, let store else { return }
        abortTrial(reason: "session_ended")
        isClosing = true
        manifest?.status = status
        manifest?.endedAt = ISO8601DateFormatter().string(from: Date())
        manifest?.sensorCounts = counts
        guard let session = manifest else { isClosing = false; return }
        self.store = nil
        store.close(session) { [weak self] success in
            if success, session.status == "completed",
               let id = session.trials.first?.spec.scenarioID,
               let scenario = EdgeScenario(rawValue: id), scenario.denseRound != nil,
               session.trials.filter({ $0.status == "completed" }).count == 33 {
                self?.denseCompleted.insert(id)
                UserDefaults.standard.set(Array(self?.denseCompleted ?? []), forKey: "denseGrid.completed.v1")
            }
            self?.isClosing = false; self?.refreshLibrary()
            if session.printedGrid != nil, session.status != "completed", let batch = self?.printedBatch {
                self?.selectPrinted(batch) // Restart an interrupted row with a fresh background pair.
            }
            self?.notice = success ? "세션을 저장했습니다. 맥북에 연결되어 있으면 직접 가져올 수 있습니다. ZIP 공유는 선택입니다." : "파일 저장 중 오류가 발생했습니다. 기록이 불완전할 수 있습니다."
        }
        UIApplication.shared.isIdleTimerDisabled = false
    }

    func background() {
        if sessionOpen { endSession(status: "interrupted_background") }
        stopSensors()
    }

    func refreshLibrary() {
        library = ((try? FileManager.default.contentsOfDirectory(at: SessionStore.root, includingPropertiesForKeys: [.isDirectoryKey])) ?? [])
            .filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
        var completed: [String: String] = [:]
        for directory in library {
            guard let data = try? Data(contentsOf: directory.appendingPathComponent("manifest.json")),
                  let session = try? JSONDecoder().decode(SessionManifest.self, from: data),
                  let meta = session.printedGrid,
                  FixturePoseAnnotations.bundled.resolve(meta.pose, campaignID: meta.campaignID, sessionID: session.id) == printedCampaign.pose,
                  PrintedGridBatch.all.contains(meta.batch),
                  meta.batch.accepts(session, campaignID: printedCampaign.id) else { continue }
            // Preserve every raw session; prefer the newest complete remeasurement in the UI.
            if completed[meta.batch.id] == nil { completed[meta.batch.id] = session.id }
        }
        printedCompleted = completed
    }

    func export(_ directory: URL) {
        guard !isExporting, !isClosing, !sessionOpen else { return }
        isExporting = true
        let output = FileManager.default.temporaryDirectory.appendingPathComponent(directory.lastPathComponent + ".zip")
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try SessionArchive.create(from: directory, to: output)
                DispatchQueue.main.async { self.archiveURL = output; self.isExporting = false }
            } catch {
                DispatchQueue.main.async { self.errorMessage = error.localizedDescription; self.isExporting = false }
            }
        }
    }
}
