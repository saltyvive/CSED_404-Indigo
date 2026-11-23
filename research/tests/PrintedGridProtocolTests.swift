import Foundation
import CryptoKit

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
        precondition(airPlan[1].fixturePose?.csvLabels(phase: "hold")[3] == "air")
        for phase in ["settle", "idle", "outside", "baseline", "move"] {
            precondition(air.csvLabels(phase: phase) == Array(repeating: "", count: 6))
        }
        var invalid = air; invalid.tipContact = true; precondition(!invalid.isValid)
        invalid = air; invalid.tipHeightMM = 0; precondition(!invalid.isValid)
        invalid = air; invalid.phiDegrees = -1; precondition(!invalid.isValid)
        invalid = air; invalid.thetaDegrees = 91; precondition(!invalid.isValid)
        for alpha in [-90.0, -15, 0, 35, 90] {
            var tilted = air; tilted.alphaDegrees = alpha
            precondition(tilted.readyForCollection)
            let decoded = try JSONDecoder().decode(PrintedGridPose.self, from: JSONEncoder().encode(tilted))
            precondition(decoded == tilted && decoded.thetaDegrees == 60)
            precondition(Double(decoded.csvLabels(phase: "hold")[2]) == alpha)
        }
        for alpha in [-91.0, 91, Double.nan] {
            invalid = air; invalid.alphaDegrees = alpha; precondition(!invalid.isValid)
        }
        var vertical = PrintedGridPose(); vertical.alphaDegrees = 10
        precondition(!vertical.readyForCollection) // Vertical needs a fixture hinge reference for nonzero alpha.
        vertical.tiltDirectionAtPhiZero = "toward iPad"; precondition(vertical.readyForCollection)
        var legacyObject = try JSONSerialization.jsonObject(with: JSONEncoder().encode(PrintedGridPose())) as! [String: Any]
        for key in ["alphaDegrees", "alphaLabelSource", "alphaDefinition"] { legacyObject.removeValue(forKey: key) }
        let legacyPose = try JSONDecoder().decode(PrintedGridPose.self, from: JSONSerialization.data(withJSONObject: legacyObject))
        precondition(legacyPose.alphaDegrees == nil && legacyPose.isValid && !legacyPose.readyForCollection)
        let annotations = try JSONDecoder().decode(FixturePoseAnnotations.self,
            from: Data(contentsOf: URL(fileURLWithPath: "MagAir/Resources/fixture_pose_annotations.json")))
        let annotation = annotations.annotations[0]
        let known = annotations.resolve(legacyPose, campaignID: annotation.campaignID, sessionID: annotation.sessionManifestSHA256.keys.first!)
        precondition(known.alphaDegrees == 0 && known.readyForCollection)
        precondition(known.alphaLabelSource == "user_confirmed_retrospective_2026-11-23")
        precondition(annotations.resolve(legacyPose, campaignID: "unrelated").alphaDegrees == nil)
        precondition(annotations.resolve(legacyPose, campaignID: annotation.campaignID, sessionID: "unlisted").alphaDegrees == nil)
        precondition(annotations.resolve(vertical, campaignID: annotation.campaignID).alphaDegrees == 10)
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
        var fastPlans: [String: [TrialSpec]] = [:]
        for batch in PrintedGridBatch.all {
            var session = SessionManifest(id: "fast", startedAt: "test", anchorUptime: 0, anchorUnix: 0,
                device: "test", osVersion: "test", setup: PrintedGridCampaign().setup, availableSensors: [:])
            session.status = "completed"
            session.printedGrid = .init(campaignID: "campaign", batch: batch)
            session.printedGrid?.timingRevision = PrintedGridMetadata.fastTimingRevision
            // Exercise the same metadata-driven factory used when Collector begins a session.
            let plan = session.printedGrid!.makePlan(block: 2)
            fastPlans[batch.id] = plan
            var time = 100.0
            session.trials = plan.map { spec in
                var t = TrialRecord(spec: spec, startUptime: time, settleSeconds: spec.preparationSeconds ?? 3)
                t.status = "completed"; t.endUptime = t.plannedEnd; time = t.plannedEnd+0.4
                if spec.kind == .mapHold {
                    precondition(t.plannedEnd-t.startUptime == 4)
                    precondition(t.annotation(at: t.startUptime+1.99).phase == "settle")
                    precondition(t.annotation(at: t.startUptime+2).source == "scheduled_static_target_unverified")
                    precondition(t.annotation(at: t.startUptime+4).phase == "outside")
                } else { precondition(t.plannedEnd-t.startUptime == 13) }
                return t
            }
            precondition(batch.accepts(session, campaignID: "campaign"))
            session.trials[1].settleSeconds = 3
            precondition(!batch.accepts(session, campaignID: "campaign"))
        }
        try JSONEncoder().encode(fastPlans).write(to: URL(fileURLWithPath: CommandLine.arguments[1]).appendingPathComponent("printed-grid-fast-plans.json"))
        var currentPlans: [String: [TrialSpec]] = [:]
        for batch in PrintedGridBatch.all {
            var session = SessionManifest(id: "prepare3", startedAt: "test", anchorUptime: 0, anchorUnix: 0,
                device: "test", osVersion: "test", setup: PrintedGridCampaign().setup, availableSensors: [:])
            session.status = "completed"
            session.printedGrid = .current(campaignID: "campaign", batch: batch, pose: .init())
            precondition(session.printedGrid?.timingRevision == PrintedGridMetadata.extendedPreparationTimingRevision)
            let plan = session.printedGrid!.makePlan(block: 3)
            currentPlans[batch.id] = plan
            var time = 100.0
            session.trials = plan.map { spec in
                var trial = TrialRecord(spec: spec, startUptime: time, settleSeconds: spec.preparationSeconds ?? 3)
                trial.status = "completed"; trial.endUptime = trial.plannedEnd; time = trial.plannedEnd+0.4
                if spec.kind == .mapHold {
                    precondition(trial.settleSeconds == 3 && spec.duration == 2 && trial.plannedEnd-trial.startUptime == 5)
                    precondition(trial.annotation(at: trial.startUptime+2.99).phase == "settle")
                    precondition(trial.annotation(at: trial.startUptime+3).source == "scheduled_static_target_unverified")
                    precondition(trial.annotation(at: trial.startUptime+5).phase == "outside")
                } else { precondition(trial.plannedEnd-trial.startUptime == 13) }
                return trial
            }
            let decoded = try JSONDecoder().decode(SessionManifest.self, from: SessionStore.encode(session))
            precondition(batch.accepts(decoded, campaignID: "campaign"))
            session.printedGrid?.timingRevision = PrintedGridMetadata.fastTimingRevision
            precondition(!batch.accepts(session, campaignID: "campaign"))
        }
        try JSONEncoder().encode(currentPlans).write(to: URL(fileURLWithPath: CommandLine.arguments[1]).appendingPathComponent("printed-grid-current-plans.json"))
        // Reproduce 1.16: a complete legacy plan was saved with the new timing declaration.
        let recoveryBatch = PrintedGridBatch(pass: 2, row: 13)
        var affected = SessionManifest(id: "timing-regression", startedAt: "test", anchorUptime: 0, anchorUnix: 0,
            device: "test", osVersion: "test", setup: PrintedGridCampaign().setup, availableSensors: [:])
        affected.status = "completed"
        affected.printedGrid = .init(campaignID: "campaign", batch: recoveryBatch)
        affected.printedGrid?.timingRevision = PrintedGridMetadata.fastTimingRevision
        var recoveryTime = 100.0
        affected.trials = recoveryBatch.make(block: 1).map { spec in
            var trial = TrialRecord(spec: spec, startUptime: recoveryTime)
            trial.status = "completed"; trial.endUptime = trial.plannedEnd; recoveryTime = trial.plannedEnd+0.4
            return trial
        }
        let affectedData = try SessionStore.encode(affected)
        let recovery = PrintedTimingAnnotations(version: 1, annotations: [.init(id: "test-recovery", campaignID: "campaign",
            sessionID: affected.id, manifestSHA256: SHA256.hash(data: affectedData).map { String(format: "%02x", $0) }.joined(),
            declaredTimingRevision: PrintedGridMetadata.fastTimingRevision,
            effectiveTimingRevision: PrintedGridMetadata.legacyTimingRevision, reason: "Regression fixture")])
        precondition(!recoveryBatch.accepts(affected, campaignID: "campaign"))
        precondition(recoveryBatch.accepts(affected, campaignID: "campaign", manifestData: affectedData, timingAnnotations: recovery))
        precondition(!recoveryBatch.accepts(affected, campaignID: "campaign", manifestData: affectedData + Data(" ".utf8), timingAnnotations: recovery))
        var incomplete = affected; incomplete.trials.removeLast()
        precondition(!recoveryBatch.accepts(incomplete, campaignID: "campaign", manifestData: affectedData, timingAnnotations: recovery))
        // Audit the actual recovered file when supplied; completion must survive decoding without rewriting it.
        if CommandLine.arguments.count > 3 {
            let url = URL(fileURLWithPath: CommandLine.arguments[3])
            let original = try Data(contentsOf: url)
            let session = try JSONDecoder().decode(SessionManifest.self, from: original)
            let timingAnnotations = try JSONDecoder().decode(PrintedTimingAnnotations.self,
                from: Data(contentsOf: URL(fileURLWithPath: "MagAir/Resources/collection_timing_annotations.json")))
            precondition(!recoveryBatch.accepts(session, campaignID: annotation.campaignID))
            precondition(recoveryBatch.accepts(session, campaignID: annotation.campaignID, manifestData: original,
                                              timingAnnotations: timingAnnotations))
            precondition(annotations.resolve(session.printedGrid!.pose, campaignID: annotation.campaignID, sessionID: session.id) == known)
            let unchanged = try Data(contentsOf: url)
            precondition(unchanged == original)
            print("Recovered real pass 2 row 13: all 23 trials accepted; original manifest unchanged")
        }
        if CommandLine.arguments.count > 4 {
            let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[4]))
            let session = try JSONDecoder().decode(SessionManifest.self, from: data)
            precondition(session.printedGrid!.batch.accepts(session, campaignID: annotation.campaignID, manifestData: data))
            precondition(session.printedGrid?.timingRevision == PrintedGridMetadata.fastTimingRevision)
            print("Real pass 2 row 12 retained with its original 2s+2s timing")
        }
        var sequence = PrintedAutoSequence()
        sequence.begin(isHold: false)
        precondition(!sequence.advance(nextIsHold: true, sensorFresh: true, deviceMoving: false))
        sequence.begin(isHold: true)
        precondition(sequence.advance(nextIsHold: true, sensorFresh: true, deviceMoving: false))
        sequence.pause(); precondition(!sequence.running)
        sequence.begin(isHold: true)
        precondition(!sequence.advance(nextIsHold: true, sensorFresh: false, deviceMoving: false))
        sequence.begin(isHold: true)
        precondition(!sequence.advance(nextIsHold: true, sensorFresh: true, deviceMoving: true))
        sequence.begin(isHold: true)
        precondition(!sequence.advance(nextIsHold: false, sensorFresh: true, deviceMoving: false))
        sequence.enabled = false; sequence.begin(isHold: true); precondition(!sequence.running)
        // Optional real-source migration audit; no file is written or re-encoded.
        if CommandLine.arguments.count > 2 {
            let root = URL(fileURLWithPath: CommandLine.arguments[2])
            var completed = Set<String>()
            for sessionID in annotation.sessionManifestSHA256.keys {
                let url = root.appendingPathComponent(sessionID).appendingPathComponent("manifest.json")
                let original = try Data(contentsOf: url)
                let session = try JSONDecoder().decode(SessionManifest.self, from: original)
                let meta = session.printedGrid!
                precondition(meta.pose.alphaDegrees == nil && meta.batch.accepts(session, campaignID: annotation.campaignID))
                precondition(annotations.resolve(meta.pose, campaignID: meta.campaignID, sessionID: session.id) == known)
                let after = try Data(contentsOf: url)
                precondition(after == original)
                completed.insert(meta.batch.id)
            }
            precondition(completed.count == 13)
            print("Legacy migration: 13 completed rows retained; raw manifests unchanged; alpha zero explicitly annotated")
        }
        print("Printed grid: 273 positions x 3 passes, physical coordinates and completion checks passed")
    }
}
