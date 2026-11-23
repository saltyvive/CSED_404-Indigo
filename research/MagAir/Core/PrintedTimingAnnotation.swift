import Foundation
import CryptoKit

/// A hash-scoped interpretation of an affected raw file, never a rewrite of it.
struct PrintedTimingAnnotation: Codable {
    var id: String
    var campaignID: String
    var sessionID: String
    var manifestSHA256: String
    var declaredTimingRevision: String
    var effectiveTimingRevision: String
    var reason: String
}

struct PrintedTimingAnnotations: Codable {
    var version: Int
    var annotations: [PrintedTimingAnnotation]
    static let bundled: Self = {
        guard let url = Bundle.main.url(forResource: "collection_timing_annotations", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let loaded = try? JSONDecoder().decode(Self.self, from: data), loaded.version == 1 else {
            return .init(version: 1, annotations: [])
        }
        return loaded
    }()

    func effectiveRevision(for session: SessionManifest, manifestData: Data?) -> String? {
        guard let meta = session.printedGrid else { return nil }
        let declared = meta.timingRevision ?? PrintedGridMetadata.legacyTimingRevision
        guard version == 1, let data = manifestData,
              let annotation = annotations.first(where: {
                  $0.sessionID == session.id && $0.campaignID == meta.campaignID &&
                  $0.declaredTimingRevision == declared &&
                  $0.manifestSHA256 == SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
              }) else { return declared }
        return annotation.effectiveTimingRevision
    }
}
