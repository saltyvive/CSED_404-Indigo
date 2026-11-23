import Foundation

/// Called on the main thread; file operations execute in order on a private serial queue.
final class SessionStore {
    let directory: URL
    private let queue = DispatchQueue(label: "MagAir.files", qos: .utility)
    private var handles: [String: FileHandle] = [:]
    private var pending: [String: String] = [:]
    private var firstError: Error?
    var onError: ((String) -> Void)?
    static let baseColumns = ["timestamp_s", "unix_s", "received_uptime_s", "trial_id", "protocol", "dataset", "repetition", "point_id", "phase", "target_x", "target_y", "label_source", "instructed_tip_height_mm", "height_label_source", "fixture_phi_deg", "fixture_theta_deg", "fixture_alpha_deg", "fixture_tip_state", "fixture_pose_source", "fixture_alpha_source"]
    static let columns = [
        "magnetometer": ["bx_uT", "by_uT", "bz_uT"],
        "accelerometer": ["ax_g", "ay_g", "az_g"],
        "gyroscope": ["rx_rad_s", "ry_rad_s", "rz_rad_s"],
        "device_motion": ["gravity_x_g", "gravity_y_g", "gravity_z_g", "user_ax_g", "user_ay_g", "user_az_g", "rx_rad_s", "ry_rad_s", "rz_rad_s", "quaternion_x", "quaternion_y", "quaternion_z", "quaternion_w", "ipad_screen_inclination_deg"],
        "pencil_events": ["event_type", "event_phase", "timestamp_basis", "pose_valid", "window_x_pt", "window_y_pt", "altitude_rad", "azimuth_rad", "roll_rad", "hover_z_normalized", "force", "estimated_properties", "expecting_updates", "estimation_update_index", "interface_orientation"]
    ]
    static var root: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("MagAirSessions", isDirectory: true)
    }
    init(manifest: SessionManifest, root: URL = SessionStore.root) throws {
        directory = root.appendingPathComponent(manifest.id, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        for (stream, columns) in Self.columns {
            let url = directory.appendingPathComponent(stream + ".csv")
            try Data(csvRow(Self.baseColumns + columns).utf8).write(to: url)
            handles[stream] = try FileHandle(forWritingTo: url)
            try handles[stream]?.seekToEnd()
        }
        try Self.encode(manifest).write(to: directory.appendingPathComponent("manifest.json"), options: .atomic)
        let readme = """
        MagAir schema 2. See manifest.json for setup, trial status, and coordinate conventions.
        CSV streams are independent events; timestamp_s is Core Motion uptime, NOT a shared row index.
        unix_s = anchorUnix + timestamp_s - anchorUptime. received_uptime_s measures callback delivery time.
        Magnetometer: raw 3-axis microtesla. Accelerometer: g. Gyroscope: rad/s.
        Device motion: iPad gravity, user acceleration, rotation, quaternion; xArbitraryZVertical reference.
        ipad_screen_inclination_deg = acos(abs(gravity_z)/norm(gravity))*180/pi, 0=flat,90=upright.
        This is screen plane vs gravity-defined horizontal, not desk-relative if the desk is tilted.
        manifest.ipadInclinationAtStart is a fresh row/session-start snapshot; per-sample values are in device_motion.csv.
        This is iPad IMU, NOT Apple Pencil IMU. No physical pencil coordinates are directly sensed.
        pencil_events.csv contains opportunistic screen touch/hover only, NOT raw Pencil IMU.
        Pencil altitude is relative to the screen, azimuth to window coordinates, NOT the desk plane.
        A2051 roll is unsupported: roll_rad is empty. hover_z_normalized is NOT millimeters.
        Hover timestamp is callback uptime, touch timestamp is UITouch event time; see timestamp_basis.
        Events outside screen/hover range are absent. Never forward-fill pose through missing periods.
        Touch estimates may be corrected later: use estimation_update_index and estimated flags.
        manual_static_target = user-confirmed approximate point, not instrumented ground truth.
        instructed_tip_height_mm is a nominal instruction, NOT a measured height or contact sensor.
        Height target 10 mm means approximately 1 cm above the desk, not screen-hover distance.
        Height transitions are unlabeled; exclude them from steady surface-vs-air comparisons.
        manual_height_instruction trials are separate from 2D coordinate training.
        guide_only = desired motion, NEVER measured ground truth. Exclude settle/outside phases.
        Edge studies: manifest trial.spec.edge/scenarioID/edgeAction identify the assigned task.
        edge_train and edge_test are split by entire scenario/session; never train on edge_test.
        known_edge_only = self-paced sweep on a named edge; target_x/y are empty, speed/position unknown.
        manual_pose_probe = instructed fixed-tip tilt/roll, NOT measured angle; exclude from position training.
        Edge blocks require both before and after edgeBaseline trials. Last baseline auto-closes the block.
        Grid map scenarios: gridMapTrain / gridMapTest; grid_map_test is held out from training.
        Historical gridMapTrain/Test: 25 manual points, x=(column-1)/4, y=(row-1)/4.
        Dense grid9Train1A...grid9Train3C: gridSize=9, x=(column-1)/8, y=(row-1)/8.
        All 3 passes are grid9_train. Each batch contains 3 rows, 27 holds and 6 backgrounds.
        repetition identifies the pass (1...3), calibrationGroup pairs passN-rowR baselines.
        Do not pool historical 5x5 with dense data automatically; verify unchanged setup.
        Raw high-frequency samples are not independent repeated placements.
        App 1.16 printed timingRevision=printed_2s_prepare_2s_hold_v2: holds prepare 2s + capture 2s.
        App 1.16.2 timingRevision=printed_3s_prepare_2s_hold_v3: holds prepare 3s + capture 2s.
        Baselines remain prepare 3s + capture 10s. Missing timingRevision means historical 3s+3s holds.
        acquisitionSeconds/preparationSeconds persist per-hold timing; trial.settleSeconds is authoritative.
        startTrigger records manual or automatic_next_hold. Automatic progression only connects holds.
        scheduled_static_target_unverified is an instructed target, NOT sensed arrival/contact/stability.
        Pause/cancel excludes the current attempt; background and first hold always require a person.
        evaluationModelSHA256 / evaluationTrainingPasses freeze the pre-update model used for pass 2 or 3.
        App 1.17 also records evaluationKNNModelSHA256 for the frozen B model before pass 3.
        Printed grid: manifest.printedGrid identifies sweetspot_21x13_v1 and a unique campaignID.
        App 1.17.1 schedules pass 3 rows 1...13; passes 1/2 keep their historical order.
        rowOrderRevision/scheduledRowOrder record the intended row order; session timestamps record actual collection order.
        All 39 batches (13 rows x 3 passes) are ONE training campaign: 273 targets x 3 independent placements.
        Each batch has one row: before background + 21 holds + after background; all 23 must complete.
        printed_grid_train and printed_grid_baseline never mix automatically with historical datasets.
        gridColumns=21, gridRows=13; gridSize is absent. x=(column-1)/20, y=(row-1)/12.
        nominalPointMM=(2.5*(column-1),2.5*(row-1)) from sweet spot TOP LEFT, not measured tip coordinates.
        Printed geometry is 50x30 mm; A4 landscape lower-left offset is (115,55) mm.
        Paper lower-left coordinates=(115+50*x,85-30*y). Pose and contact are operator instructions, not sensors.
        printedGrid.pose and trial.spec.fixturePose record operator-set phi/theta/alpha/height/contact and their reference.
        phi: whole-holder yaw about desk vertical, clockwise from above; demo fixture orientation=0 (360=0).
        phi is NOT Pencil axial roll. At theta=90, phi still identifies the fixture's material orientation.
        theta: Pencil elevation above desk at alpha=0; horizontal=0, vertical=90.
        alpha: [-90,90] about the initial desk-projection hinge; positive toward fixture-local right (rotates with phi).
        At theta=90 the projection vanishes: record the fixture hinge reference in tiltDirectionAtPhiZero.
        Theta is not recomputed as the final elevation after alpha. Missing legacy alpha is unknown, not zero.
        fixture_alpha_source distinguishes newly entered values from explicit retrospective user confirmation.
        fixture_phi_deg / fixture_theta_deg / fixture_alpha_deg / fixture_tip_state / fixture_pose_source / fixture_alpha_source are filled only during steady holds.
        Heights in instructed_tip_height_mm use the fixture target during holds; air targets are vertical projections onto paper.
        Do not attach pose/height/contact labels to backgrounds, movement, settling or idle samples.
        campaignID changes when setup changes; do not pool campaigns just because dimensions match.
        Interrupted rows restart from a fresh before baseline; incomplete row sessions are excluded.
        A replacement row keeps its prior files. Select one complete session per batch explicitly for training.
        manifest trial.spec.calibrationGroup pairs each row's before/after mapBaseline; do not use one session-wide baseline.
        gridRow/gridColumn are 1-based; row 1 is iPad side, column 1 is user's left.
        Grid path scenarios 13/14/15: gridHorizontal/gridVertical/gridDiagonal. grid_path_test is not coordinate training.
        mapSweep / known_path_only = self-paced out-and-back on manifest spec.guidePathID; target_x/y stay empty.
        Path ID identifies an instructed line, NOT actual position, speed, or direction at a given time.
        Each path has its own before/after mapBaseline using the same calibrationGroup.
        Exclude trials whose status is not completed. Repeated attempts have unique trial IDs.
        Keep whole trials / repetitions together when splitting training and evaluation data.
        Historical unknown lengths are not millimeters. Printed geometry is nominal; verify actual print scale.
        Active/aborted sessions can contain partial data; retain manifest with all CSV files.
        """
        try Data(readme.utf8).write(to: directory.appendingPathComponent("README.txt"))
    }
    static func encode(_ manifest: SessionManifest) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(manifest)
    }
    private func fail(_ error: Error) {
        guard firstError == nil else { return }
        firstError = error
        DispatchQueue.main.async { self.onError?(error.localizedDescription) }
    }
    func append(stream: String, fields: [String]) {
        let row = csvRow(fields)
        queue.async {
            guard self.firstError == nil else { return }
            self.pending[stream, default: ""] += row
            if self.pending[stream, default: ""].utf8.count > 8192 {
                do { try self.flush(stream) } catch { self.fail(error) }
            }
        }
    }
    private func flush(_ stream: String) throws {
        guard let content = pending[stream], !content.isEmpty else { return }
        try handles[stream]?.write(contentsOf: Data(content.utf8))
        pending[stream] = ""
    }
    func checkpoint(_ manifest: SessionManifest, completion: ((Bool) -> Void)? = nil) {
        queue.async {
            do {
                for stream in self.handles.keys {
                    try self.flush(stream)
                    try self.handles[stream]?.synchronize()
                }
                try Self.encode(manifest).write(to: self.directory.appendingPathComponent("manifest.json"), options: .atomic)
            } catch { self.fail(error) }
            let success = self.firstError == nil
            DispatchQueue.main.async { completion?(success) }
        }
    }
    func close(_ manifest: SessionManifest, completion: @escaping (Bool) -> Void) {
        checkpoint(manifest)
        queue.async {
            for handle in self.handles.values {
                do { try handle.close() } catch { self.fail(error) }
            }
            self.handles = [:]
            let success = self.firstError == nil
            DispatchQueue.main.async { completion(success) }
        }
    }
}

/// Uncompressed ZIP (standard ZIP32) for offline AirDrop / Files export; no dependency or network.
enum SessionArchive {
    static func create(from directory: URL, to output: URL) throws {
        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.isRegularFileKey])
            .filter { (try? $0.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        var archive = Data(), central = Data()
        for file in files {
            let content = try Data(contentsOf: file)
            let name = Data((directory.lastPathComponent + "/" + file.lastPathComponent).utf8)
            guard content.count < Int(UInt32.max), archive.count < Int(UInt32.max) else {
                throw CocoaError(.fileWriteOutOfSpace)
            }
            let size = UInt32(content.count), offset = UInt32(archive.count), crc = crc32(content)
            archive.put(UInt32(0x04034b50)); archive.put(UInt16(20)); archive.put(UInt16(0x800))
            archive.put(UInt16(0)); archive.put(UInt16(0)); archive.put(UInt16(33))
            archive.put(crc); archive.put(size); archive.put(size)
            archive.put(UInt16(name.count)); archive.put(UInt16(0)); archive.append(name); archive.append(content)
            central.put(UInt32(0x02014b50)); central.put(UInt16(20)); central.put(UInt16(20)); central.put(UInt16(0x800))
            central.put(UInt16(0)); central.put(UInt16(0)); central.put(UInt16(33))
            central.put(crc); central.put(size); central.put(size)
            central.put(UInt16(name.count)); central.put(UInt16(0)); central.put(UInt16(0))
            central.put(UInt16(0)); central.put(UInt16(0)); central.put(UInt32(0)); central.put(offset); central.append(name)
        }
        let start = UInt32(archive.count)
        archive.append(central)
        archive.put(UInt32(0x06054b50)); archive.put(UInt16(0)); archive.put(UInt16(0))
        archive.put(UInt16(files.count)); archive.put(UInt16(files.count)); archive.put(UInt32(central.count))
        archive.put(start); archive.put(UInt16(0))
        try archive.write(to: output, options: .atomic)
    }
    static func crc32(_ bytes: Data) -> UInt32 {
        var crc: UInt32 = 0xffffffff
        for byte in bytes {
            crc ^= UInt32(byte)
            for _ in 0..<8 { crc = (crc >> 1) ^ ((crc & 1) != 0 ? 0xedb88320 : 0) }
        }
        return crc ^ 0xffffffff
    }
}

private extension Data {
    mutating func put<T: FixedWidthInteger>(_ value: T) {
        var value = value.littleEndian
        Swift.withUnsafeBytes(of: &value) { append(contentsOf: $0) }
    }
}
