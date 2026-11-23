import Foundation

struct KNNLocation: Codable {
    var xy: [Double]
    var fieldsUT: [[Double]]
    var placementIDs: [String]
}

struct KNNLiveModel: Codable {
    var version: Int
    var method: String
    var k: Int
    var weightPower: Double
    var distanceFloorUT: Double
    var localRadiusMM: Double
    var ambiguityDistance: Double
    var ambiguityMarginUT: Double
    var residualLimitUT: Double
    var minimumSignalUT: Double
    var locations: [KNNLocation]
    var sourceSessions: [String]
    var trainingTrialIDs: [String]
    var printedGridContext: PrintedGridModelContext
    var planSHA256: String
    var scope: String

    var isValid: Bool {
        let c = printedGridContext
        guard version == 1, method == "multiprototype_local_distance_weighted_knn_v1",
              c.trainingPositions == 273, c.widthMM == 50, c.heightMM == 30, c.pose.isValid,
              !c.passes.isEmpty, Set(c.passes).count == c.passes.count, c.passes.allSatisfy({ (1...3).contains($0) }),
              locations.count == 273, (1...8).contains(k), weightPower.isFinite, weightPower > 0,
              distanceFloorUT.isFinite, distanceFloorUT > 0,
              localRadiusMM.isFinite, localRadiusMM > 0, ambiguityDistance.isFinite, ambiguityDistance > 0,
              ambiguityMarginUT.isFinite, ambiguityMarginUT >= 0, residualLimitUT.isFinite, residualLimitUT > 0,
              minimumSignalUT.isFinite, minimumSignalUT > 0,
              sourceSessions.count == 13*c.passes.count, Set(sourceSessions).count == sourceSessions.count,
              trainingTrialIDs.count == 273*c.passes.count, Set(trainingTrialIDs).count == trainingTrialIDs.count else { return false }
        for (i, location) in locations.enumerated() {
            guard location.xy.count == 2, location.xy.allSatisfy(\.isFinite),
                  abs(location.xy[0]-Double(i%21)/20) < 1e-9, abs(location.xy[1]-Double(i/21)/12) < 1e-9,
                  location.fieldsUT.count == 4*c.passes.count,
                  location.fieldsUT.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) }),
                  location.placementIDs.count == c.passes.count else { return false }
        }
        return Set(locations.flatMap(\.placementIDs)) == Set(trainingTrialIDs)
    }
}

/// Distinct target neighbors; repeats supply alternate magnetic patterns, not extra votes.
struct KNNProjector {
    let model: KNNLiveModel
    init?(model: KNNLiveModel) {
        guard model.isValid else { return nil }
        self.model = model
    }

    func project(_ b: [Double]) -> GridEstimate? {
        guard b.count == 3, b.allSatisfy(\.isFinite) else { return nil }
        let distances = model.locations.map { location in
            location.fieldsUT.map { f in
                sqrt(zip(f,b).reduce(0.0) { $0 + ($1.0-$1.1)*($1.0-$1.1) })
            }.min()!
        }
        func ordered(_ a: Int, _ b: Int) -> Bool {
            distances[a] == distances[b] ? a < b : distances[a] < distances[b]
        }
        let best = distances.indices.min(by: ordered)!
        let anchor = model.locations[best].xy, residual = distances[best]
        var other = 1e300
        for i in distances.indices {
            let p = model.locations[i].xy
            if hypot(p[0]-anchor[0],p[1]-anchor[1]) >= model.ambiguityDistance { other = min(other,distances[i]) }
        }
        let c = model.printedGridContext
        let nearby = distances.indices.filter { i in
            let p = model.locations[i].xy
            return hypot(c.widthMM*(p[0]-anchor[0]),c.heightMM*(p[1]-anchor[1])) <= model.localRadiusMM+1e-9
        }.sorted(by: ordered)
        var chosen = Array(nearby.prefix(model.k))
        let exact = chosen.filter { distances[$0] <= model.distanceFloorUT }
        let weights: [Double]
        if !exact.isEmpty { chosen = exact; weights = Array(repeating: 1, count: exact.count) }
        else { weights = chosen.map { 1/pow(max(distances[$0],model.distanceFloorUT),model.weightPower) } }
        let total = weights.reduce(0,+)
        let x = zip(chosen,weights).reduce(0.0) { $0 + model.locations[$1.0].xy[0]*$1.1 }/total
        let y = zip(chosen,weights).reduce(0.0) { $0 + model.locations[$1.0].xy[1]*$1.1 }/total
        let signal = sqrt(b.reduce(0.0) { $0+$1*$1 })
        let ambiguous = other <= residual+model.ambiguityMarginUT
        return GridEstimate(point: .init(x: x,y: y),residual: residual,limit: model.residualLimitUT,signal: signal,
                            accepted: signal >= model.minimumSignalUT && residual <= model.residualLimitUT && !ambiguous,
                            showCandidate: signal >= model.minimumSignalUT,ambiguous: ambiguous,otherLocationResidual: other)
    }
}
