import SwiftUI
import UIKit
import UIKit.UIGestureRecognizerSubclass

/// Public screen events only. These are not a Bluetooth/raw IMU stream.
struct PencilEvent {
    var timestamp: Double
    var type: String
    var phase: String
    var timestampBasis: String
    var valid: Bool
    var x: Double
    var y: Double
    var altitude: Double?
    var azimuth: Double?
    var zOffset: Double?
    var force: Double?
    var estimated: Int = 0
    var expecting: Int = 0
    var estimationIndex: String = ""
    var orientation: Int
    var columns: [String] {
        [type, phase, timestampBasis, valid ? "1" : "0", number(x), number(y),
         altitude.map(number) ?? "", azimuth.map(number) ?? "",
         "", // A2051 has no barrel-roll API. Never interpret the fallback 0 as measured 0°.
         zOffset.map(number) ?? "", force.map(number) ?? "",
         String(estimated), String(expecting), estimationIndex, String(orientation)]
    }
}

struct PencilEventBridge: UIViewRepresentable {
    var onEvent: (PencilEvent) -> Void
    func makeUIView(context: Context) -> PencilWindowObserver {
        let view = PencilWindowObserver()
        view.onEvent = onEvent
        view.isUserInteractionEnabled = false
        return view
    }
    func updateUIView(_ view: PencilWindowObserver, context: Context) { view.onEvent = onEvent }
    static func dismantleUIView(_ view: PencilWindowObserver, coordinator: ()) { view.detach() }
}

final class PencilWindowObserver: UIView, UIGestureRecognizerDelegate {
    var onEvent: ((PencilEvent) -> Void)?
    private weak var observedWindow: UIWindow?
    private var hover: UIHoverGestureRecognizer?
    private var touches: PencilTouchObserver?

    override func didMoveToWindow() {
        super.didMoveToWindow()
        guard window !== observedWindow else { return }
        detach()
        guard let window else { return }
        observedWindow = window
        let hover = UIHoverGestureRecognizer(target: self, action: #selector(hovered(_:)))
        hover.allowedTouchTypes = [NSNumber(value: UITouch.TouchType.pencil.rawValue)]
        hover.cancelsTouchesInView = false
        hover.delegate = self
        window.addGestureRecognizer(hover)
        self.hover = hover
        let touch = PencilTouchObserver(target: nil, action: nil)
        touch.allowedTouchTypes = [NSNumber(value: UITouch.TouchType.pencil.rawValue)]
        touch.cancelsTouchesInView = false
        touch.delaysTouchesBegan = false
        touch.delaysTouchesEnded = false
        touch.delegate = self
        touch.onEvent = { [weak self] event in self?.onEvent?(event) }
        window.addGestureRecognizer(touch)
        self.touches = touch
    }

    func detach() {
        if let hover { observedWindow?.removeGestureRecognizer(hover) }
        if let touches { observedWindow?.removeGestureRecognizer(touches) }
        hover = nil; touches = nil; observedWindow = nil
    }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer) -> Bool { true }

    @objc private func hovered(_ recognizer: UIHoverGestureRecognizer) {
        let valid = recognizer.state == .began || recognizer.state == .changed
        let point = recognizer.location(in: observedWindow)
        // UIGestureRecognizer exposes no hardware event timestamp. Explicitly mark receipt time.
        let event = PencilEvent(timestamp: ProcessInfo.processInfo.systemUptime, type: "hover",
                                phase: String(recognizer.state.rawValue), timestampBasis: "callback_uptime",
                                valid: valid, x: point.x, y: point.y,
                                altitude: valid ? Double(recognizer.altitudeAngle) : nil,
                                azimuth: valid ? Double(recognizer.azimuthAngle(in: observedWindow)) : nil,
                                zOffset: valid ? Double(recognizer.zOffset) : nil, force: nil,
                                orientation: observedWindow?.windowScene?.interfaceOrientation.rawValue ?? 0)
        onEvent?(event)
    }
}

final class PencilTouchObserver: UIGestureRecognizer {
    var onEvent: ((PencilEvent) -> Void)?
    override func canPrevent(_ preventedGestureRecognizer: UIGestureRecognizer) -> Bool { false }
    override func canBePrevented(by preventingGestureRecognizer: UIGestureRecognizer) -> Bool { false }
    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent) {
        emit(touches, event: event); state = .began
    }
    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent) {
        emit(touches, event: event); state = .changed
    }
    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent) {
        emit(touches, event: event); state = .ended
    }
    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent) {
        emit(touches, event: event); state = .cancelled
    }
    override func touchesEstimatedPropertiesUpdated(_ touches: Set<UITouch>) {
        emit(touches, event: nil, update: true)
    }
    private func emit(_ touches: Set<UITouch>, event: UIEvent?, update: Bool = false) {
        for touch in touches where touch.type == .pencil {
            let samples = update ? [touch] : (event?.coalescedTouches(for: touch) ?? [touch])
            for sample in samples {
                let valid = update || (sample.phase != .ended && sample.phase != .cancelled)
                let point = sample.location(in: view)
                onEvent?(PencilEvent(timestamp: sample.timestamp, type: update ? "touch_estimate_update" : "touch",
                                     phase: String(sample.phase.rawValue), timestampBasis: "uitouch_timestamp",
                                     valid: valid, x: point.x, y: point.y,
                                     altitude: valid ? Double(sample.altitudeAngle) : nil,
                                     azimuth: valid ? Double(sample.azimuthAngle(in: view)) : nil,
                                     zOffset: nil, force: valid ? Double(sample.force) : nil,
                                     estimated: sample.estimatedProperties.rawValue,
                                     expecting: sample.estimatedPropertiesExpectingUpdates.rawValue,
                                     estimationIndex: sample.estimationUpdateIndex?.stringValue ?? "",
                                     orientation: view?.window?.windowScene?.interfaceOrientation.rawValue ?? 0))
            }
        }
    }
}
