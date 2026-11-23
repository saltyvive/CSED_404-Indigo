import Foundation

struct LibraryReplayCase: Decodable {
    var combination: String
    var family: String
    var filteredDeltaUT: [Double]
    var xy: [Double]
    var residualUT: Double
    var otherLocationResidualUT: Double
    var shown: Bool
    var ambiguous: Bool
    var accepted: Bool
}

@main
struct GridModelLibraryTests {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        func read(_ resource: String) throws -> Data { try Data(contentsOf: root.appendingPathComponent(resource + ".json")) }
        let library = try GridModelLibrary.load(read: read)
        let cases = try JSONDecoder().decode([LibraryReplayCase].self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2])))
        precondition(library.catalog.entries.count == 7 && library.catalog.defaultCombination == "123")
        precondition(library.pair("123")!.entry.evaluations.allSatisfy { $0.role == "training_replay" })
        precondition(library.pair("12")!.modelA.printedGridContext!.passes == [1,2])
        var tested = 0
        for entry in library.catalog.entries {
            let pair = library.pair(entry.id)!
            let a = GridProjector(model: pair.modelA)!, b = KNNProjector(model: pair.modelB)!
            for c in cases where c.combination == entry.id {
                let p = (c.family == "A" ? a.project(c.filteredDeltaUT) : b.project(c.filteredDeltaUT))!
                precondition(abs(p.point.x-c.xy[0]) < 1e-8 && abs(p.point.y-c.xy[1]) < 1e-8)
                precondition(abs(p.residual-c.residualUT) < 1e-8 && abs(p.otherLocationResidual-c.otherLocationResidualUT) < 1e-8)
                precondition(p.accepted == c.accepted && p.showCandidate == c.shown && p.ambiguous == c.ambiguous)
                tested += 1
            }
        }
        precondition(tested == cases.count && tested >= 294)
        // Corrupt or mismatched resources must never silently switch the displayed model.
        do {
            _ = try GridModelLibrary.load { name in
                var data = try read(name)
                if name == "model_A_1" { data.append(32) }
                return data
            }
            preconditionFailure("Corrupt hash accepted")
        } catch { }
        var catalog = try JSONSerialization.jsonObject(with: read("model_catalog")) as! [String: Any]
        var entries = catalog["entries"] as! [[String: Any]]
        var evaluations = entries[6]["evaluations"] as! [[String: Any]]
        evaluations[0]["role"] = "held_out_pass"; entries[6]["evaluations"] = evaluations; catalog["entries"] = entries
        let invalid = try JSONSerialization.data(withJSONObject: catalog)
        do {
            _ = try GridModelLibrary.load { name in name == "model_catalog" ? invalid : try read(name) }
            preconditionFailure("Training replay labelled held-out")
        } catch { }
        print("Library: all 14 models validated; \(tested) Swift/Python predictions matched; corrupt hash and evaluation leakage rejected.")
    }
}
