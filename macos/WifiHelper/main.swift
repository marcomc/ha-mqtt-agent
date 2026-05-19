import AppKit
import CoreLocation
import CoreWLAN
import Foundation

struct WifiSnapshot: Codable {
    let authorized: Bool
    let authorizationStatus: String
    let interface: String?
    let ssid: String?
    let bssid: String?
    let signalDbm: Int?
    let noiseDbm: Int?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case authorized
        case authorizationStatus = "authorization_status"
        case interface
        case ssid
        case bssid
        case signalDbm = "signal_dbm"
        case noiseDbm = "noise_dbm"
        case error
    }
}

final class LocationAuthorizer: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyThreeKilometers
    }

    func requestAuthorization(timeoutSeconds: TimeInterval) -> CLAuthorizationStatus {
        let status = authorizationStatus()
        if status == .notDetermined {
            manager.requestWhenInUseAuthorization()
        }
        manager.startUpdatingLocation()
        runUntilAuthorizationCompletes(timeoutSeconds: timeoutSeconds)
        manager.stopUpdatingLocation()
        return authorizationStatus()
    }

    func authorizationStatus() -> CLAuthorizationStatus {
        return manager.authorizationStatus
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        _ = manager
    }

    func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
        _ = (manager, status)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        _ = locations
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        _ = error
    }

    private func runUntilAuthorizationCompletes(timeoutSeconds: TimeInterval) {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while authorizationStatus() == .notDetermined && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
        }
    }
}

func currentWifiSnapshot(authorizer: LocationAuthorizer) -> WifiSnapshot {
    let status = authorizer.authorizationStatus()
    let authorized = isAuthorized(status)

    guard authorized else {
        return WifiSnapshot(
            authorized: false,
            authorizationStatus: statusName(status),
            interface: nil,
            ssid: nil,
            bssid: nil,
            signalDbm: nil,
            noiseDbm: nil,
            error: nil
        )
    }

    guard let interface = CWWiFiClient.shared().interface() else {
        return WifiSnapshot(
            authorized: true,
            authorizationStatus: statusName(status),
            interface: nil,
            ssid: nil,
            bssid: nil,
            signalDbm: nil,
            noiseDbm: nil,
            error: "wifi_interface_unavailable"
        )
    }

    return WifiSnapshot(
        authorized: true,
        authorizationStatus: statusName(status),
        interface: interface.interfaceName,
        ssid: interface.ssid(),
        bssid: interface.bssid(),
        signalDbm: interface.rssiValue(),
        noiseDbm: interface.noiseMeasurement(),
        error: nil
    )
}

func isAuthorized(_ status: CLAuthorizationStatus) -> Bool {
    switch status {
    case .authorized, .authorizedAlways, .authorizedWhenInUse:
        return true
    default:
        return false
    }
}

func statusName(_ status: CLAuthorizationStatus) -> String {
    switch status {
    case .notDetermined:
        return "not_determined"
    case .restricted:
        return "restricted"
    case .denied:
        return "denied"
    case .authorizedAlways:
        return "authorized_always"
    case .authorizedWhenInUse:
        return "authorized_when_in_use"
    case .authorized:
        return "authorized"
    @unknown default:
        return "unknown"
    }
}

func printJson(_ snapshot: WifiSnapshot) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    do {
        let data = try encoder.encode(snapshot)
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    } catch {
        let fallback = #"{"authorized":false,"authorization_status":"unknown","error":"json_encode_failed"}"#
        print(fallback)
    }
}

func printUsage() {
    print("usage: HaMqttAgentWifiHelper [--json|--authorize]")
}

let arguments = Set(CommandLine.arguments.dropFirst())
let application = NSApplication.shared
if arguments.contains("--authorize") {
    application.setActivationPolicy(.regular)
    application.finishLaunching()
    application.activate(ignoringOtherApps: true)
} else {
    application.setActivationPolicy(.accessory)
}
let authorizer = LocationAuthorizer()

if arguments.contains("--help") || arguments.contains("-h") {
    printUsage()
    exit(0)
}

if arguments.contains("--authorize") {
    _ = authorizer.requestAuthorization(timeoutSeconds: 30)
    printJson(currentWifiSnapshot(authorizer: authorizer))
    exit(0)
}

if arguments.isEmpty || arguments.contains("--json") {
    printJson(currentWifiSnapshot(authorizer: authorizer))
    exit(0)
}

printUsage()
exit(2)
