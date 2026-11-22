import Foundation

enum PrintedGridProtocolTests {
    static func run() throws {
        precondition(PrintedGridPose().isValid)
        var air = PrintedGridPose(phiDegrees: 360, thetaDegrees: 60, tipHeightMM: 5, tipContact: false)
        precondition(!air.isValid) // A tilted run needs its zero-yaw tilt direction.
        air.tiltDirectionAtPhiZero = "toward iPad"
        precondition(air.isValid && air.canonical.phiDegrees == 0)
        let airPlan = PrintedGridBatch.all[0].make(block: 1, pose: air)
        precondition(airPlan.first?.fixturePose == nil && airPlan.last?.fixturePose == nil)
        let airTrial = TrialRecord(spec: airPlan[1], startUptime: 100)
        precondition(airTrial.instructedHeightMM(at: 102) == nil)
        precondition(airTrial.instructedHeightMM(at: 104) == 5)
        precondition(airPlan[1].fixturePose?.csvLabels(phase: "hold")[2] == "air")
        for phase in ["settle", "idle", "outside", "baseline", "move"] {
            precondition(air.csvLabels(phase: phase) == ["", "", "", ""])
        }
        var invalid = air; invalid.tipContact = true; precondition(!invalid.isValid)
        invalid = air; invalid.tipHeightMM = 0; precondition(!invalid.isValid)
        invalid = air; invalid.phiDegrees = -1; precondition(!invalid.isValid)
        invalid = air; invalid.thetaDegrees = 91; precondition(!invalid.isValid)
        invalid = air; invalid.tipHeightMM = .nan; precondition(!invalid.isValid)
        precondition(ipadScreenInclination(gravity: [0,0,-1]) == 0)
        precondition(ipadScreenInclination(gravity: [0,0,1]) == 0)
        precondition(ipadScreenInclination(gravity: [1,0,0]) == 90)
        precondition(ipadScreenInclination(gravity: [0,-1,0]) == 90)
        precondition(abs(ipadScreenInclination(gravity: [0,sqrt(3)/2,-0.5])! - 60) < 1e-9)
        precondition(ipadScreenInclination(gravity: [0,0,0]) == nil)
        precondition(ipadScreenInclination(gravity: [.nan,0,1]) == nil)
        precondition(PrintedGridBatch.all.count == 39)
        precondition(Set(PrintedGridBatch.all.map(\.id)).count == 39)
        var plans: [String: [TrialSpec]] = [:]
        for pass in 1...3 {
            let batches = PrintedGridBatch.all.filter { $0.pass == pass }
            precondition(Set(batches.map(\.row)) == Set(1...13))
            let points = batches.flatMap { $0.make(block: 1) }.filter { $0.kind == .mapHold }
            precondition(points.count == 273 && Set(points.map(\.pointID)).count == 273)
            precondition(points.filter { $0.point!.x == 0 || $0.point!.x == 1 || $0.point!.y == 0 || $0.point!.y == 1 }.count == 64)
            precondition(points.allSatisfy { $0.purpose == "printed_grid_train" })
            for point in points {
                let mm = point.nominalPointMM!, normalized = point.point!
                precondition(mm.x == Double(point.gridColumn!-1)*2.5 && mm.y == Double(point.gridRow!-1)*2.5)
                precondition(abs(normalized.x*50-mm.x) < 1e-9 && abs(normalized.y*30-mm.y) < 1e-9)
                let record = TrialRecord(spec: point, startUptime: 100)
                precondition(record.annotation(at: 102).source == "guide_only")
                precondition(record.annotation(at: 104).source == "manual_static_target")
                precondition(record.instructedHeightMM(at: 104) == 0)
            }
        }
        for row in 1...13 {
            precondition(PrintedGridBatch(pass: 1, row: row).columns == PrintedGridBatch(pass: 2, row: row).columns.reversed())
        }
        for batch in PrintedGridBatch.all {
            let plan = batch.make(block: 1)
            precondition(plan.count == 23 && plan.first?.edgeAction == "before" && plan.last?.edgeAction == "after")
            precondition(Set(plan.compactMap(\.gridColumn)) == Set(1...21))
            var session = SessionManifest(id: "synthetic", startedAt: "test", anchorUptime: 0, anchorUnix: 0,
                                          device: "test", osVersion: "test", setup: PrintedGridCampaign().setup, availableSensors: [:])
            session.status = "completed"
            session.printedGrid = .init(campaignID: "campaign", batch: batch)
            var time = 100.0
            session.trials = plan.map { spec in
                var t = TrialRecord(spec: spec, startUptime: time)
                t.status = "completed"; t.endUptime = t.plannedEnd; time = t.plannedEnd + 1
                return t
            }
            precondition(batch.accepts(session, campaignID: "campaign"))
            precondition(!batch.accepts(session, campaignID: "another-setup"))
            var bad = session; bad.trials.removeLast()
            precondition(!batch.accepts(bad, campaignID: "campaign"))
            bad = session; bad.trials[1].spec = bad.trials[2].spec
            precondition(!batch.accepts(bad, campaignID: "campaign"))
            bad = session; bad.trials[1].status = "aborted"
            precondition(!batch.accepts(bad, campaignID: "campaign"))
            bad = session; bad.trials[1].spec.nominalPointMM?.x += 2.5
            precondition(!batch.accepts(bad, campaignID: "campaign"))
            bad = session; bad.trials[1].endUptime! -= 1
            precondition(!batch.accepts(bad, campaignID: "campaign"))
            bad = session; bad.trials[1].spec.fixturePose?.phiDegrees = 45
            precondition(!batch.accepts(bad, campaignID: "campaign"))
            bad = session; bad.status = "interrupted_background"
            precondition(!batch.accepts(bad, campaignID: "campaign"))
            // A rejected attempt remains in the audit trail but must not block a complete retry.
            var rejected = session.trials[1]; rejected.status = "invalidated"; rejected.spec.id += "-old"
            session.trials.insert(rejected, at: 1)
            precondition(batch.accepts(session, campaignID: "campaign"))
            let decoded = try JSONDecoder().decode(SessionManifest.self, from: SessionStore.encode(session))
            precondition(batch.accepts(decoded, campaignID: "campaign"))
            plans[batch.id] = plan
        }
        precondition(PrintedGridBatch.all.last?.next == nil)
        try JSONEncoder().encode(plans).write(to: URL(fileURLWithPath: CommandLine.arguments[1]).appendingPathComponent("printed-grid-plans.json"))
        print("Printed grid: 273 positions x 3 passes, physical coordinates and completion checks passed")
    }
}
