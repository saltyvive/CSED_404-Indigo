import Foundation
import CryptoKit

struct JointNeuralLayer: Decodable {
    var weights: [[Double]] // Output-major, exactly as exported by the trainer.
    var bias: [Double]
}

struct JointNeuralCondition: Decodable {
    var state: String
    var passes: [Int]
    var campaignID: String
    var tipHeightMM: Double
    var phiDegrees: Double
    var thetaDegrees: Double
    var alphaDegrees: Double
}

struct JointNeuralModel: Decodable {
    var version: Int
    var method: String
    var inputMean: [Double]
    var inputScale: [Double]
    var layers: [JointNeuralLayer]
    var widthMM: Double
    var heightMM: Double
    var contactLow: Double
    var contactHigh: Double
    var minimumSignalUT: Double
    var supportLimitUT: Double
    var supportFieldsUT: [[Double]]
    var trainingTrialIDs: [String]
    var sourceSessions: [String]
    var conditions: [JointNeuralCondition]
    var planSHA256: String

    var isValid: Bool {
        guard version == 1, method == "shared_mlp_xy_contact_v1", widthMM == 50, heightMM == 30,
              inputMean.count == 3, inputMean.allSatisfy(\.isFinite),
              inputScale.count == 3, inputScale.allSatisfy({ $0.isFinite && $0 > 0 }),
              layers.count == 3, contactLow == 0.35, contactHigh == 0.65,
              minimumSignalUT.isFinite, minimumSignalUT >= 3, supportLimitUT.isFinite, supportLimitUT >= 3,
              supportFieldsUT.count == 3276, supportFieldsUT.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) }),
              trainingTrialIDs.count == 819, Set(trainingTrialIDs).count == 819,
              sourceSessions.count == 39, Set(sourceSessions).count == 39,
              conditions.count == 2, conditions.map(\.state) == ["contact", "air"],
              conditions[0].passes == [1,3], conditions[1].passes == [1],
              conditions[0].tipHeightMM == 0, conditions[1].tipHeightMM == 3,
              conditions.allSatisfy({ $0.phiDegrees == 0 && $0.thetaDegrees == 90 && $0.alphaDegrees == 0 }) else { return false }
        let sizes = [3,64,64,3]
        for i in layers.indices {
            let layer = layers[i]
            guard layer.bias.count == sizes[i+1], layer.bias.allSatisfy(\.isFinite),
                  layer.weights.count == sizes[i+1],
                  layer.weights.allSatisfy({ $0.count == sizes[i] && $0.allSatisfy(\.isFinite) }) else { return false }
        }
        return true
    }
}

struct JointNeuralEstimate {
    var point: Point2D
    var contactScore: Double
    var supportDistanceUT: Double
    var supportLimitUT: Double
    var signal: Double
    var showCandidate: Bool
    var inSupport: Bool
    var inBounds: Bool
    var ambiguous: Bool
    var accepted: Bool { showCandidate && inSupport && inBounds && !ambiguous }
    var closestState: JointTipState { contactScore >= 0.5 ? .contact : .air }
    var state: JointTipState { accepted ? closestState : .uncertain }
    var gridEstimate: GridEstimate {
        .init(point: point, residual: supportDistanceUT, limit: supportLimitUT, signal: signal,
              accepted: accepted, showCandidate: showCandidate, ambiguous: ambiguous, otherLocationResidual: 0)
    }
    var reason: String {
        if !showCandidate { return "펜 신호가 약함 · 위치·접촉 표시 보류" }
        if !inSupport { return "학습한 자기장 범위에서 멂 · 주황색 후보" }
        if !inBounds { return "추정 좌표가 스윗 스팟을 벗어남 · 주황색 후보" }
        if ambiguous { return "접촉 점수가 중간 영역 · 접촉·공중 판정 보류" }
        return "C · " + state.title + (state == .contact ? " · 청록색" : " · 보라색")
    }
}

struct JointNeuralProjector {
    let model: JointNeuralModel
    init?(model: JointNeuralModel) {
        guard model.isValid else { return nil }; self.model = model
    }
    func project(_ field: [Double]) -> JointNeuralEstimate? {
        guard field.count == 3, field.allSatisfy(\.isFinite) else { return nil }
        var hidden = (0..<3).map { (field[$0]-model.inputMean[$0])/model.inputScale[$0] }
        for (i, layer) in model.layers.enumerated() {
            hidden = layer.weights.indices.map { j in
                let sum = zip(layer.weights[j],hidden).reduce(layer.bias[j]) { $0 + $1.0*$1.1 }
                return i < 2 ? tanh(sum) : sum
            }
        }
        let point = Point2D(x: hidden[0]/2+0.5, y: hidden[1]/1.2+0.5)
        let logit = hidden[2]
        let score = logit >= 0 ? 1/(1+exp(-logit)) : exp(logit)/(1+exp(logit))
        let support = model.supportFieldsUT.map { prototype in
            sqrt(zip(prototype,field).reduce(0.0) { $0 + pow($1.0-$1.1,2) })
        }.min()!
        let signal = sqrt(field.reduce(0.0) { $0+$1*$1 })
        guard point.x.isFinite, point.y.isFinite, score.isFinite, support.isFinite, signal.isFinite else { return nil }
        return .init(point: point, contactScore: score, supportDistanceUT: support, supportLimitUT: model.supportLimitUT,
                     signal: signal, showCandidate: signal >= model.minimumSignalUT, inSupport: support <= model.supportLimitUT,
                     inBounds: (-0.05...1.05).contains(point.x) && (-0.05...1.05).contains(point.y),
                     ambiguous: score > model.contactLow && score < model.contactHigh)
    }
}

struct JointNeuralBundle {
    let data: Data
    let sha256: String
    let projector: JointNeuralProjector

    static func load(library: GridModelLibrary, read: (String) throws -> Data) throws -> JointNeuralBundle {
        struct Catalog: Decodable { var version: Int; var resource: String; var sha256: String; var planSHA256: String }
        let catalog = try JSONDecoder().decode(Catalog.self, from: read("joint_mlp_catalog"))
        guard catalog.version == 1, catalog.resource == "joint_mlp_contact13_air1" else {
            throw GridModelLibrary.LoadError.invalid("C 모델 목록 불일치")
        }
        let data = try read(catalog.resource)
        let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let model = try JSONDecoder().decode(JointNeuralModel.self, from: data)
        guard hash == catalog.sha256, model.planSHA256 == catalog.planSHA256,
              let projector = JointNeuralProjector(model: model),
              let contact = library.pair("13"), let air = library.pair("hover3_1"),
              Set(model.trainingTrialIDs) == Set(contact.modelA.trainingTrialIDs + air.modelA.trainingTrialIDs),
              Set(model.sourceSessions) == Set((contact.modelA.sourceSessions ?? []) + (air.modelA.sourceSessions ?? [])),
              model.conditions[0].campaignID == contact.modelA.printedGridContext?.campaignID,
              model.conditions[1].campaignID == air.modelA.printedGridContext?.campaignID else {
            throw GridModelLibrary.LoadError.invalid("C 모델 해시·학습 자료·조건 불일치")
        }
        return .init(data: data, sha256: hash, projector: projector)
    }
}
