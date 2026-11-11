import SwiftUI

@main
struct MagAirApp: App {
    @StateObject private var collector = Collector()
    @State private var selectedTab = "edges"
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            TabView(selection: $selectedTab) {
                GridLiveView(collector: collector, tester: collector.gridLiveTester) { scenario in
                    collector.selectEdge(scenario)
                    selectedTab = "edges"
                }
                    .tabItem { Label("격자 내부 테스트", systemImage: "square.grid.3x3") }.tag("gridLive")
                EdgeLiveView(collector: collector, tester: collector.edgeLiveTester) {
                    collector.selectEdge(collector.nextDenseCollection)
                    selectedTab = "edges"
                }
                    .tabItem { Label("네 변 테스트", systemImage: "point.topleft.down.to.point.bottomright.curvepath") }.tag("edgeLive")
                EdgeStudyView(collector: collector)
                    .tabItem { Label("데이터 수집", systemImage: "rectangle.and.pencil.and.ellipsis") }.tag("edges")
                ContentView(collector: collector)
                    .disabled(collector.sessionOpen && collector.edgeScenario != nil)
                    .tabItem { Label("이전 수집", systemImage: "waveform.path") }.tag("collect")
                LiveTestView(collector: collector, tester: collector.liveTester)
                    .tabItem { Label("이전 모델 테스트", systemImage: "pencil.and.outline") }.tag("live")
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
