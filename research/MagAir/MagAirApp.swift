import SwiftUI

@main
struct MagAirApp: App {
    @StateObject private var collector = Collector()
    @State private var selectedTab: String = {
        if ProcessInfo.processInfo.arguments.contains("--live-hover3") { return "gridLive" }
        if ProcessInfo.processInfo.arguments.contains("--prepare-hover3") { return "printed" }
        #if DEBUG && targetEnvironment(simulator)
        if ProcessInfo.processInfo.arguments.contains("--preview-printed-setup") ||
            ProcessInfo.processInfo.arguments.contains("--preview-printed-target") { return "printed" }
        #endif
        return "gridLive"
    }()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            TabView(selection: $selectedTab) {
                PrintedGridStudyView(collector: collector)
                    .tabItem { Label("273점 수집", systemImage: "square.grid.3x3.fill") }.tag("printed")
                GridLiveView(collector: collector, tester: collector.gridLiveTester) {
                    collector.selectPrinted(collector.nextPrintedBatch)
                    selectedTab = "printed"
                }
                    .tabItem { Label("A/B/C 실시간 테스트", systemImage: "square.grid.3x3") }.tag("gridLive")
            }
                .background(PencilEventBridge(onEvent: collector.receivePencil))
                .preferredColorScheme(.light)
                .tint(Color(red: 0.12, green: 0.65, blue: 0.58))
                .onChange(of: scenePhase) { _, phase in
                    if phase == .background { collector.background() }
                    if phase == .active { collector.startSensors() }
                }
        }
    }
}
