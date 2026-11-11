import Foundation

@main
struct CoreTests {
    static func main() throws {
        for scenario in EdgeScenario.allCases {
            let plan = scenario.make(block: 9)
            precondition(plan.first?.edgeAction == "before" && plan.last?.edgeAction == "after")
            let baselineKind: ProtocolKind = scenario.isGridMap || scenario.isGridPath ? .mapBaseline : .edgeBaseline
            precondition(plan.first?.kind == baselineKind && plan.last?.kind == baselineKind)
            precondition(Set(plan.map(\.id)).count == plan.count)
            precondition(plan.allSatisfy { $0.scenarioID == scenario.rawValue })
            let holds = plan.filter { $0.kind == .edgeHold }
            if scenario.isTraining {
                precondition(holds.count == 10 && holds.allSatisfy { $0.dataset == "edge_train" })
                for rep in 1...2 { precondition(holds.filter { $0.repetition == rep }.count == 5) }
            } else { precondition(holds.allSatisfy { $0.dataset == "edge_test" }) }
            for sweep in plan.filter({ $0.kind == .edgeSweep }) {
                var record = TrialRecord(spec: sweep, startUptime: 100)
                precondition(sweep.point == nil && sweep.isManual)
                precondition(record.annotation(at: 110).point == nil)
                precondition(record.annotation(at: 110).source == "known_edge_only")
                precondition(record.instructedHeightMM(at: 110) == 0)
                record.endUptime = 113.7
                precondition(record.annotation(at: 113.69).phase == "move")
                precondition(record.annotation(at: 113.7).phase == "outside")
            }
        }
        for scenario in [EdgeScenario.gridHorizontal, .gridVertical, .gridDiagonal] {
            let plan = scenario.make(block: 10)
            precondition(plan.count == (scenario == .gridDiagonal ? 6 : 15))
            for sweep in plan.filter({ $0.kind == .mapSweep }) {
                precondition(sweep.isManual && sweep.point == nil && sweep.purpose == "grid_path_test")
                let guide = GridGuide(rawValue: sweep.guidePathID!)!
                precondition(guide.endpoints.count == 2 && guide != .free)
                let group = plan.filter { $0.calibrationGroup == sweep.calibrationGroup }
                precondition(group.count == 3 && group.first?.edgeAction == "before" && group.last?.edgeAction == "after")
                var record = TrialRecord(spec: sweep, startUptime: 100)
                for t in [103.0, 104, 117, 175] {
                    precondition(record.annotation(at: t).point == nil && record.annotation(at: t).source == "known_path_only")
                    precondition(record.instructedHeightMM(at: t) == 0)
                }
                record.endUptime = 118
                precondition(record.annotation(at: 118).phase == "outside")
            }
        }
        let mapTrain = EdgeScenario.gridMapTrain.make(block: 1)
        let mapTest = EdgeScenario.gridMapTest.make(block: 2)
        for plan in [mapTrain, mapTest] {
            precondition(plan.count == 35)
            let holds = plan.filter { $0.kind == .mapHold }
            precondition(holds.count == 25 && Set(holds.map(\.pointID)).count == 25)
            precondition(holds.filter { $0.point!.x > 0 && $0.point!.x < 1 && $0.point!.y > 0 && $0.point!.y < 1 }.count == 9)
            for row in 1...5 {
                let group = plan.filter { $0.calibrationGroup == "row\(row)" }
                precondition(group.count == 7 && group.first?.edgeAction == "before" && group.last?.edgeAction == "after")
                precondition(group.first?.kind == .mapBaseline && group.last?.kind == .mapBaseline)
                for hold in group.filter({ $0.kind == .mapHold }) {
                    precondition(hold.point == Point2D(x: Double(hold.gridColumn!-1)/4, y: Double(row-1)/4))
                    let record = TrialRecord(spec: hold, startUptime: 100)
                    precondition(record.annotation(at: 103).phase == "hold" && record.annotation(at: 103).source == "manual_static_target")
                    precondition(record.annotation(at: 102).source == "guide_only" && record.instructedHeightMM(at: 103) == 0)
                }
            }
        }
        precondition(mapTrain.filter { $0.kind == .mapHold }.allSatisfy { $0.dataset == "grid_map_train" })
        precondition(mapTest.filter { $0.kind == .mapHold }.allSatisfy { $0.dataset == "grid_map_test" })
        precondition(mapTrain.compactMap(\.point) != mapTest.compactMap(\.point))
        try JSONEncoder().encode(mapTrain).write(to: URL(fileURLWithPath: CommandLine.arguments[1]).appendingPathComponent("grid-map-plan.json"))
        var densePlans: [String: [TrialSpec]] = [:]
        for scenario in EdgeScenario.denseTraining {
            let plan = scenario.make(block: 1)
            precondition(plan.count == 33 && plan.filter { $0.kind == .mapHold }.count == 27)
            precondition(plan.allSatisfy { $0.gridSize == 9 && $0.repetition == scenario.denseRound })
            for row in scenario.denseRows {
                let group = plan.filter { $0.gridRow == row }
                precondition(group.count == 11 && group.first?.edgeAction == "before" && group.last?.edgeAction == "after")
                let holds = group.filter { $0.kind == .mapHold }
                precondition(Set(holds.compactMap(\.gridColumn)) == Set(1...9))
                for hold in holds {
                    precondition(hold.dataset == "grid9_train")
                    precondition(hold.point == .init(x: Double(hold.gridColumn!-1)/8, y: Double(row-1)/8))
                    let record = TrialRecord(spec: hold, startUptime: 100)
                    precondition(record.annotation(at: 103).source == "manual_static_target")
                    precondition(record.annotation(at: 102).source == "guide_only")
                }
            }
            densePlans[scenario.rawValue] = plan
        }
        for repetition in 1...3 {
            let holds = densePlans.values.flatMap { $0 }.filter { $0.kind == .mapHold && $0.repetition == repetition }
            precondition(holds.count == 81 && Set(holds.map(\.pointID)).count == 81)
        }
        precondition(EdgeScenario.grid9Train3C.nextDense == nil && EdgeScenario.grid9Train1C.nextDense == .grid9Train2A)
        precondition(GridGuide.denseRow9.endpoints == [.init(x: 0,y: 1), .init(x: 1,y: 1)])
        precondition(GridGuide.denseCol5.endpoints == [.init(x: 0.5,y: 0), .init(x: 0.5,y: 1)])
        precondition(GridGuide.options(gridSize: 9).count == 21 && GridGuide.options(gridSize: 5).count == 13)
        try JSONEncoder().encode(densePlans).write(to: URL(fileURLWithPath: CommandLine.arguments[1]).appendingPathComponent("grid9-plans.json"))
        let pose = TrialRecord(spec: EdgeScenario.pose.make(block: 1)[1], startUptime: 100)
        precondition(pose.annotation(at: 103).phase == "pose_reference")
        precondition(pose.annotation(at: 106).phase == "pose_change")
        precondition(pose.annotation(at: 110).phase == "pose_return")
        precondition(pose.annotation(at: 110).source == "manual_pose_probe")
        for edge in StudyEdge.allCases {
            for s in [0.0, 0.25, 0.5, 0.75, 1.0] { precondition(edge.parameter(edge.point(s)) == s) }
        }
        let training = TrialSpec.make(.gridTrain, block: 1)
        let testing = TrialSpec.make(.gridTest, block: 2)
        precondition(training.count == 75 && testing.count == 32)
        precondition(Set(training.map(\.id)).count == 75)
        for rep in 1...3 {
            let points = training.filter { $0.repetition == rep }.compactMap(\.point)
            precondition(points.count == 25)
            precondition(Set(points.map { "\($0.x),\($0.y)" }).count == 25)
        }
        precondition(!testing.contains { t in training.contains { $0.point == t.point } })
        let corners = TrialSpec.make(.corners, block: 3)
        precondition(corners.count == 12 && Set(corners.map(\.id)).count == 12)
        precondition(corners[0].point == Point2D(x: 0, y: 0))
        precondition(corners[1].point == Point2D(x: 1, y: 0))
        precondition(corners[2].point == Point2D(x: 1, y: 1))
        precondition(corners[3].point == Point2D(x: 0, y: 1))
        precondition(Set(corners.compactMap(\.point).map { "\($0.x),\($0.y)" }).count == 4)
        precondition(corners.last?.repetition == 3 && corners[0].duration == 3)
        precondition(TrialRecord(spec: corners[0], startUptime: 100).annotation(at: 103).phase == "hold")
        precondition(TrialRecord(spec: corners[0], startUptime: 100).annotation(at: 103).source == "manual_static_target")
        precondition(training.map(\.id) == TrialSpec.make(.gridTrain, block: 1).map(\.id))
        precondition(ProtocolKind.clockwise.target(at: 3) == Point2D(x: 1, y: 0))
        precondition(ProtocolKind.clockwise.target(at: 6) == Point2D(x: 1, y: 1))
        precondition(ProtocolKind.counterclockwise.target(at: 3) == Point2D(x: 0, y: 1))
        precondition(ProtocolKind.diagonalDown.target(at: 6) == Point2D(x: 1, y: 1))
        precondition(ProtocolKind.clockwise.target(at: 12) == Point2D(x: 0, y: 0))
        let record = TrialRecord(spec: training[0], startUptime: 100)
        precondition(record.annotation(at: 99).phase == "outside")
        precondition(record.annotation(at: 102.999).phase == "settle")
        precondition(record.annotation(at: 103).phase == "hold")
        precondition(record.annotation(at: 105.999).source == "manual_static_target")
        precondition(record.annotation(at: 106).phase == "outside")
        var aborted = record
        aborted.endUptime = 104
        aborted.status = "aborted"
        precondition(aborted.annotation(at: 104.1).phase == "outside")
        let moving = TrialRecord(spec: TrialSpec.make(.clockwise, block: 3)[0], startUptime: 100)
        precondition(moving.annotation(at: 107).source == "guide_only")
        let heightSpecs = TrialSpec.make(.cornersHeight, block: 4)
        precondition(heightSpecs.count == 12 && heightSpecs.allSatisfy { $0.nominalLiftMM == 10 })
        precondition(heightSpecs.map(\.point) == corners.map(\.point))
        let height = TrialRecord(spec: heightSpecs[0], startUptime: 100)
        let heightPhases: [(Double, String, Double?)] = [
            (102.9, "settle", nil), (103, "surface_hold", 0), (105.999, "surface_hold", 0),
            (106, "lift_transition", nil), (108, "air_hold", 10), (110.999, "air_hold", 10),
            (111, "lower_transition", nil), (113, "surface_return", 0), (116, "outside", nil)
        ]
        for (time, phase, mm) in heightPhases {
            precondition(height.annotation(at: time).phase == phase)
            precondition(height.instructedHeightMM(at: time) == mm)
        }
        precondition(height.annotation(at: 108).source == "manual_height_instruction")
        precondition(!ProtocolKind.cornersHeight.isStatic && ProtocolKind.cornersHeight.dataset == "height_paired")
        var abortedHeight = height
        abortedHeight.endUptime = 109
        precondition(abortedHeight.instructedHeightMM(at: 109) == nil)
        for (surface, air) in [(ProtocolKind.clockwise, ProtocolKind.clockwiseAir), (.counterclockwise, .counterclockwiseAir)] {
            precondition(surface.path == air.path && surface.duration == air.duration)
            let airRecord = TrialRecord(spec: TrialSpec.make(air, block: 5)[0], startUptime: 100)
            precondition(airRecord.instructedHeightMM(at: 104) == 10)
            precondition(airRecord.annotation(at: 104).source == "guide_only")
        }
        precondition(moving.instructedHeightMM(at: 104) == 0)
        // An older saved trial without the additive height field must still decode.
        let legacy = Data("{\"id\":\"old\",\"kind\":\"corners\",\"repetition\":1,\"pointID\":\"top_left\"}".utf8)
        let legacySpec = try JSONDecoder().decode(TrialSpec.self, from: legacy)
        precondition(legacySpec.nominalLiftMM == nil)
        precondition(csvRow(["a,b", "quote\"", "line\nnext"]) == "\"a,b\",\"quote\"\"\",\"line\nnext\"\n")
        precondition(SessionArchive.crc32(Data("123456789".utf8)) == 0xcbf43926)
        let directory = URL(fileURLWithPath: CommandLine.arguments[1]).appendingPathComponent("archive-fixture")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data("한글,1\nquoted,\"value\"\n".utf8).write(to: directory.appendingPathComponent("test.csv"))
        try Data().write(to: directory.appendingPathComponent("empty.txt"))
        try SessionArchive.create(from: directory, to: directory.deletingLastPathComponent().appendingPathComponent("test.zip"))
        var manifest = SessionManifest(id: "SYNTHETIC-STORE-TEST", startedAt: "test", anchorUptime: 100, anchorUnix: 1000,
                                       device: "test", osVersion: "test", setup: Setup(), availableSensors: [:])
        let storage = try SessionStore(manifest: manifest, root: directory)
        let prefix = ["100", "1000", "100", "trial", "gridTrain", "train", "1", "r1c1", "hold", "0", "0", "manual_static_target", "", "none"]
        storage.append(stream: "magnetometer", fields: prefix + ["1", "2", "3"])
        var saved = false
        storage.checkpoint(manifest) { success in precondition(success); saved = true }
        let deadline = Date().addingTimeInterval(5)
        while !saved && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.01)) }
        precondition(saved)
        let rows = try String(contentsOf: storage.directory.appendingPathComponent("magnetometer.csv"), encoding: .utf8)
        precondition(rows.split(separator: "\n").count == 2)
        precondition(rows.contains("manual_static_target,,none,1,2,3"))
        precondition(rows.split(separator: "\n").allSatisfy { $0.split(separator: ",", omittingEmptySubsequences: false).count == 17 })
        for stream in SessionStore.columns.keys {
            precondition(FileManager.default.fileExists(atPath: storage.directory.appendingPathComponent(stream + ".csv").path))
        }
        manifest.status = "completed"
        var closed = false
        storage.close(manifest) { success in precondition(success); closed = true }
        while !closed && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.01)) }
        precondition(closed)
        let diskManifest = try JSONDecoder().decode(SessionManifest.self, from: Data(contentsOf: storage.directory.appendingPathComponent("manifest.json")))
        precondition(diskManifest.status == "completed")
        print("Core tests passed: grid, splits, timing, path direction, CSV, CRC, ZIP, durable checkpoint and close")
    }
}
