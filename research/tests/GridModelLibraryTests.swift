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
        let cases = try CommandLine.arguments.dropFirst(2).flatMap { path in
            try JSONDecoder().decode([LibraryReplayCase].self, from: Data(contentsOf: URL(fileURLWithPath: path)))
        }
        precondition(library.catalog.entries.count == 7 && library.catalog.defaultCombination == "123")
        precondition(library.allEntries.count == 8 && library.defaultLiveCombination == "hover3_1")
        precondition(library.conditions.map(\.id) == ["contact0", "air3"])
        precondition(library.condition(for: "13")?.entries.count == 7)
        precondition(library.condition(for: "hover3_1")?.entries.count == 1)
        precondition(library.pair("hover3_1")!.modelA.printedGridContext!.pose.tipHeightMM == 3)
        precondition(!library.pair("hover3_1")!.modelB.printedGridContext.pose.tipContact)
        precondition(library.pair("hover3_1")!.entry.evaluations.count == 1)
        precondition(library.pair("hover3_1")!.entry.evaluations[0].role == "training_replay")
        precondition(library.canReuseBaseline(from: "1", to: "123"))
        precondition(library.canReuseBaseline(from: "hover3_1", to: "hover3_1"))
        precondition(!library.canReuseBaseline(from: "123", to: "hover3_1"))
        precondition(!library.canReuseBaseline(from: "hover3_1", to: "1"))
        precondition(!library.canReuseBaseline(from: "missing", to: "1"))
        precondition(library.pair("123")!.entry.evaluations.allSatisfy { $0.role == "training_replay" })
        precondition(library.pair("12")!.modelA.printedGridContext!.passes == [1,2])
        var tested = 0
        for entry in library.allEntries {
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
        // A valid contact pair must not be advertised as the 3mm condition.
        var hoverCatalog = try JSONSerialization.jsonObject(with: read("hover3_model_catalog")) as! [String: Any]
        var hoverEntry = (hoverCatalog["entries"] as! [[String: Any]])[0]
        let contactEntry = library.pair("1")!.entry
        hoverEntry["resourceA"] = contactEntry.resourceA; hoverEntry["resourceB"] = contactEntry.resourceB
        hoverEntry["sha256A"] = contactEntry.sha256A; hoverEntry["sha256B"] = contactEntry.sha256B
        hoverCatalog["entries"] = [hoverEntry]
        let wrongHeight = try JSONSerialization.data(withJSONObject: hoverCatalog)
        do {
            _ = try GridModelLibrary.load { name in name == "hover3_model_catalog" ? wrongHeight : try read(name) }
            preconditionFailure("Contact model accepted as 3mm")
        } catch { }
        hoverCatalog = try JSONSerialization.jsonObject(with: read("hover3_model_catalog")) as! [String: Any]
        hoverEntry = (hoverCatalog["entries"] as! [[String: Any]])[0]
        var hoverEvaluation = (hoverEntry["evaluations"] as! [[String: Any]])[0]
        hoverEvaluation["role"] = "held_out_pass"; hoverEntry["evaluations"] = [hoverEvaluation]
        hoverCatalog["entries"] = [hoverEntry]
        let falseValidation = try JSONSerialization.data(withJSONObject: hoverCatalog)
        do {
            _ = try GridModelLibrary.load { name in name == "hover3_model_catalog" ? falseValidation : try read(name) }
            preconditionFailure("Air training replay labelled independent")
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
        precondition(cases.contains { $0.combination == "hover3_1" && $0.family == "A" })
        precondition(cases.contains { $0.combination == "hover3_1" && $0.family == "B" })
        print("Library: all 16 models validated; \(tested) Swift/Python predictions matched; corrupt hash, wrong height and evaluation leakage rejected; baseline policy checked.")
    }
}
