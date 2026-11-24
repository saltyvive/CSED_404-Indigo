import Foundation
import CryptoKit

struct GridComparisonMetrics: Decodable {
    var count: Int
    var medianRadialErrorMM: Double
    var p95RadialErrorMM: Double
    var acceptedDisplayRate: Double
    var successWithin2p5MM: Double
    var successWithin5MM: Double
}

struct GridCombinationEvaluation: Decodable {
    var testPass: Int
    var role: String
    var primaryA: GridComparisonMetrics
    var primaryB: GridComparisonMetrics
}

struct GridModelEntry: Decodable, Identifiable {
    var id: String
    var passes: [Int]
    var resourceA: String
    var resourceB: String
    var sha256A: String
    var sha256B: String
    var evaluations: [GridCombinationEvaluation]
    var title: String { passes.map(String.init).joined(separator: "+") }
}

struct GridModelPair {
    let entry: GridModelEntry
    let modelA: GridLiveModel
    let modelB: KNNLiveModel
    let dataA: Data
    let dataB: Data
}

struct GridModelCondition: Identifiable {
    var id: String
    var title: String
    var defaultCombination: String
    var entries: [GridModelEntry]
}

struct GridModelLibrary {
    struct Catalog: Decodable {
        var version: Int
        var defaultCombination: String
        var entries: [GridModelEntry]
    }
    enum LoadError: LocalizedError {
        case invalid(String)
        var errorDescription: String? {
            if case .invalid(let message) = self { return message }; return nil
        }
    }
    let catalog: Catalog
    let conditions: [GridModelCondition]
    var allEntries: [GridModelEntry] { conditions.flatMap(\.entries) }
    var defaultLiveCombination: String { "hover3_1" }
    private let pairs: [String: GridModelPair]
    func pair(_ id: String) -> GridModelPair? { pairs[id] }
    func condition(for combination: String) -> GridModelCondition? {
        conditions.first { $0.entries.contains { $0.id == combination } }
    }
    func canReuseBaseline(from old: String, to new: String) -> Bool {
        guard let a = pair(old)?.modelA.printedGridContext, let b = pair(new)?.modelA.printedGridContext else { return false }
        return a.campaignID == b.campaignID && a.pose == b.pose
    }

    private static func loadPair(_ entry: GridModelEntry, passes: [Int], evaluationPasses: [Int],
                                 read: (String) throws -> Data) throws -> GridModelPair {
        let a = try read(entry.resourceA), b = try read(entry.resourceB)
        func sha(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
        guard sha(a) == entry.sha256A, sha(b) == entry.sha256B else { throw LoadError.invalid("\(entry.title) 모델 해시 불일치") }
        let modelA = try JSONDecoder().decode(GridLiveModel.self, from: a)
        let modelB = try JSONDecoder().decode(KNNLiveModel.self, from: b)
        guard modelA.isValid, modelB.isValid, let context = modelA.printedGridContext,
              entry.passes == passes, context.passes == passes, modelB.printedGridContext.passes == passes,
              context.campaignID == modelB.printedGridContext.campaignID, context.pose == modelB.printedGridContext.pose,
              context.pose.readyForCollection,
              Set(modelA.sourceSessions ?? []) == Set(modelB.sourceSessions),
              Set(modelA.trainingTrialIDs) == Set(modelB.trainingTrialIDs),
              modelA.sourceSessions?.count == 13*passes.count,
              modelA.trainingTrialIDs.count == 273*passes.count,
              entry.evaluations.map(\.testPass) == evaluationPasses,
              entry.evaluations.allSatisfy({ $0.role == (passes.contains($0.testPass) ? "training_replay" : "held_out_pass") &&
                  $0.primaryA.count == 273 && $0.primaryB.count == 273 }) else {
            throw LoadError.invalid("\(entry.title) A/B 학습 자료·평가 구분이 일치하지 않습니다")
        }
        return GridModelPair(entry: entry, modelA: modelA, modelB: modelB, dataA: a, dataB: b)
    }

    static func load(read: (String) throws -> Data) throws -> GridModelLibrary {
        let catalog = try JSONDecoder().decode(Catalog.self, from: read("model_catalog"))
        let expected = ["1", "2", "3", "12", "23", "13", "123"]
        guard catalog.version == 1, catalog.defaultCombination == "123", catalog.entries.map(\.id) == expected else {
            throw LoadError.invalid("7개 학습 조합 목록이 올바르지 않습니다")
        }
        var pairs = [String: GridModelPair]()
        for entry in catalog.entries {
            let pair = try loadPair(entry, passes: entry.id.compactMap { Int(String($0)) }, evaluationPasses: [1,2,3], read: read)
            let context = pair.modelA.printedGridContext!
            guard context.pose.tipContact && context.pose.tipHeightMM == 0 else { throw LoadError.invalid("접촉 모델의 높이 조건 불일치") }
            if let first = pairs.values.first?.modelA.printedGridContext {
                guard first.campaignID == context.campaignID, first.pose == context.pose else {
                    throw LoadError.invalid("조합 사이 배치·자세 조건이 다릅니다")
                }
            }
            pairs[entry.id] = pair
        }
        let hover = try JSONDecoder().decode(Catalog.self, from: read("hover3_model_catalog"))
        guard hover.version == 1, hover.defaultCombination == "hover3_1", hover.entries.map(\.id) == ["hover3_1"] else {
            throw LoadError.invalid("3 mm 모델 목록이 올바르지 않습니다")
        }
        let pair = try loadPair(hover.entries[0], passes: [1], evaluationPasses: [1], read: read)
        let context = pair.modelA.printedGridContext!
        guard context.pose.tipHeightMM == 3, !context.pose.tipContact,
              context.pose.phiDegrees == 0, context.pose.thetaDegrees == 90, context.pose.alphaDegrees == 0,
              context.campaignID != pairs["123"]!.modelA.printedGridContext!.campaignID,
              Set(pair.modelA.sourceSessions ?? []).isDisjoint(with: pairs["123"]!.modelA.sourceSessions ?? []) else {
            throw LoadError.invalid("3 mm 비접촉 모델과 기존 접촉 배치 구분 불일치")
        }
        pairs[pair.entry.id] = pair
        return GridModelLibrary(catalog: catalog, conditions: [
            .init(id: "contact0", title: "0 mm · 접촉", defaultCombination: "123", entries: catalog.entries),
            .init(id: "air3", title: "3 mm · 공중", defaultCombination: "hover3_1", entries: hover.entries)
        ], pairs: pairs)
    }
}
