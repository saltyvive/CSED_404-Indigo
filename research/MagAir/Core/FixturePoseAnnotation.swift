import Foundation

/// A separately recorded user confirmation, never a rewrite of a raw session.
struct FixturePoseAnnotation: Codable {
    var id: String
    var campaignID: String
    var sessionManifestSHA256: [String: String]
    var expectedPhiDegrees: Double
    var expectedThetaDegrees: Double
    var expectedTipHeightMM: Double
    var expectedTipContact: Bool
    var alphaDegrees: Double
    var alphaLabelSource: String
    var confirmedOn: String
    var note: String

    func resolve(_ pose: PrintedGridPose, campaignID: String, sessionID: String? = nil) -> PrintedGridPose {
        guard pose.alphaDegrees == nil, self.campaignID == campaignID,
              sessionID.map({ sessionManifestSHA256[$0] != nil }) ?? true,
              pose.phiDegrees == expectedPhiDegrees, pose.thetaDegrees == expectedThetaDegrees,
              pose.tipHeightMM == expectedTipHeightMM, pose.tipContact == expectedTipContact else { return pose }
        var result = pose
        result.alphaDegrees = alphaDegrees
        result.alphaLabelSource = alphaLabelSource
        result.alphaDefinition = PrintedGridPose.alphaConvention
        return result
    }
}

struct FixturePoseAnnotations: Codable {
    var version: Int
    var annotations: [FixturePoseAnnotation]
    static let bundled: Self = {
        guard let url = Bundle.main.url(forResource: "fixture_pose_annotations", withExtension: "json"),
              let data = try? Data(contentsOf: url), let loaded = try? JSONDecoder().decode(Self.self, from: data),
              loaded.version == 1 else { return .init(version: 1, annotations: []) }
        return loaded
    }()
    func resolve(_ pose: PrintedGridPose, campaignID: String, sessionID: String? = nil) -> PrintedGridPose {
        annotations.reduce(pose) { $1.resolve($0, campaignID: campaignID, sessionID: sessionID) }
    }
}
