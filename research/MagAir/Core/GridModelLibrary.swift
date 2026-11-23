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
    private let pairs: [String: GridModelPair]
    func pair(_ id: String) -> GridModelPair? { pairs[id] }

    static func load(read: (String) throws -> Data) throws -> GridModelLibrary {
        let catalog = try JSONDecoder().decode(Catalog.self, from: read("model_catalog"))
        let expected = ["1", "2", "3", "12", "23", "13", "123"]
        guard catalog.version == 1, catalog.defaultCombination == "123", catalog.entries.map(\.id) == expected else {
            throw LoadError.invalid("7개 학습 조합 목록이 올바르지 않습니다")
        }
        var pairs = [String: GridModelPair]()
        for entry in catalog.entries {
            let a = try read(entry.resourceA), b = try read(entry.resourceB)
            func sha(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
            guard sha(a) == entry.sha256A, sha(b) == entry.sha256B else { throw LoadError.invalid("\(entry.title) 모델 해시 불일치") }
            let modelA = try JSONDecoder().decode(GridLiveModel.self, from: a)
            let modelB = try JSONDecoder().decode(KNNLiveModel.self, from: b)
            guard modelA.isValid, modelB.isValid, let context = modelA.printedGridContext,
                  entry.passes == entry.id.compactMap({ Int(String($0)) }),
                  context.passes == entry.passes, modelB.printedGridContext.passes == entry.passes,
                  context.campaignID == modelB.printedGridContext.campaignID, context.pose == modelB.printedGridContext.pose,
                  Set(modelA.sourceSessions ?? []) == Set(modelB.sourceSessions),
                  Set(modelA.trainingTrialIDs) == Set(modelB.trainingTrialIDs),
                  modelA.sourceSessions?.count == 13*entry.passes.count,
                  modelA.trainingTrialIDs.count == 273*entry.passes.count,
                  entry.evaluations.map(\.testPass) == [1,2,3],
                  entry.evaluations.allSatisfy({ $0.role == (entry.passes.contains($0.testPass) ? "training_replay" : "held_out_pass") &&
                      $0.primaryA.count == 273 && $0.primaryB.count == 273 }) else {
                throw LoadError.invalid("\(entry.title) A/B 학습 자료·평가 구분이 일치하지 않습니다")
            }
            if let first = pairs.values.first?.modelA.printedGridContext {
                guard first.campaignID == context.campaignID, first.pose == context.pose else {
                    throw LoadError.invalid("조합 사이 배치·자세 조건이 다릅니다")
                }
            }
            pairs[entry.id] = GridModelPair(entry: entry, modelA: modelA, modelB: modelB, dataA: a, dataB: b)
        }
        return GridModelLibrary(catalog: catalog, pairs: pairs)
    }
}
