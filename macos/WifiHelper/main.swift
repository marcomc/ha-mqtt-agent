import AppKit
import CoreLocation
import CoreWLAN
import Foundation
import MapKit

struct WifiSnapshot: Codable {
    let authorized: Bool
    let authorizationStatus: String
    let interface: String?
    let ssid: String?
    let bssid: String?
    let signalDbm: Int?
    let noiseDbm: Int?
    let latitude: Double?
    let longitude: Double?
    let locationAccuracyM: Double?
    let locationError: String?
    let geocodedLocation: GeocodedLocation?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case authorized
        case authorizationStatus = "authorization_status"
        case interface
        case ssid
        case bssid
        case signalDbm = "signal_dbm"
        case noiseDbm = "noise_dbm"
        case latitude
        case longitude
        case locationAccuracyM = "location_accuracy_m"
        case locationError = "location_error"
        case geocodedLocation = "geocoded_location"
        case error
    }
}

struct GeocodedLocation: Codable {
    let state: String?
    let name: String?
    let country: String?
    let isoCountryCode: String?
    let timeZone: String?
    let administrativeArea: String?
    let subAdministrativeArea: String?
    let postalCode: String?
    let locality: String?
    let subLocality: String?
    let thoroughfare: String?
    let subThoroughfare: String?
    let areasOfInterest: [String]
    let ocean: String?
    let inlandWater: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case state
        case name
        case country
        case isoCountryCode = "iso_country_code"
        case timeZone = "time_zone"
        case administrativeArea = "administrative_area"
        case subAdministrativeArea = "sub_administrative_area"
        case postalCode = "postal_code"
        case locality
        case subLocality = "sub_locality"
        case thoroughfare
        case subThoroughfare = "sub_thoroughfare"
        case areasOfInterest = "areas_of_interest"
        case ocean
        case inlandWater = "inland_water"
        case error
    }
}

struct GeocodedLocationResponse: Codable {
    let geocodedLocation: GeocodedLocation

    enum CodingKeys: String, CodingKey {
        case geocodedLocation = "geocoded_location"
    }
}

final class LocationAuthorizer: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var latestLocation: CLLocation?
    private var latestLocationError: Error?

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

    func currentLocation(timeoutSeconds: TimeInterval) -> CLLocation? {
        guard isAuthorized(authorizationStatus()) else {
            return nil
        }
        latestLocation = nil
        latestLocationError = nil
        manager.startUpdatingLocation()
        manager.requestLocation()
        runUntilLocationArrives(timeoutSeconds: timeoutSeconds)
        manager.stopUpdatingLocation()
        return latestLocation ?? manager.location
    }

    func locationErrorDescription() -> String? {
        return latestLocationError?.localizedDescription
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
        _ = manager
        latestLocation = locations.last
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        _ = manager
        latestLocationError = error
    }

    private func runUntilAuthorizationCompletes(timeoutSeconds: TimeInterval) {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while authorizationStatus() == .notDetermined && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
        }
    }

    private func runUntilLocationArrives(timeoutSeconds: TimeInterval) {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while latestLocation == nil && latestLocationError == nil && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
        }
    }
}

final class ReverseGeocoder {
    func reverseGeocode(location: CLLocation, timeoutSeconds: TimeInterval) -> GeocodedLocation {
        if #available(macOS 26.0, *) {
            return MapKitReverseGeocoder().reverseGeocode(
                location: location,
                timeoutSeconds: timeoutSeconds
            )
        }
        return LegacyCoreLocationReverseGeocoder().reverseGeocode(
            location: location,
            timeoutSeconds: timeoutSeconds
        )
    }
}

@available(macOS 26.0, *)
final class MapKitReverseGeocoder {
    private var request: MKReverseGeocodingRequest?
    private var mapItem: MKMapItem?
    private var latestError: Error?
    private var completed = false

    func reverseGeocode(location: CLLocation, timeoutSeconds: TimeInterval) -> GeocodedLocation {
        guard let request = MKReverseGeocodingRequest(location: location) else {
            return emptyGeocodedLocation(error: "geocode_request_failed")
        }
        self.request = request
        mapItem = nil
        latestError = nil
        completed = false
        request.getMapItems { mapItems, error in
            self.mapItem = mapItems?.first
            self.latestError = error
            self.completed = true
        }
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while !completed && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
        }
        if !completed {
            request.cancel()
        }
        if let mapItem {
            return geocodedLocation(from: mapItem, error: nil)
        }
        return emptyGeocodedLocation(error: latestError?.localizedDescription ?? "geocode_timed_out")
    }
}

final class LegacyCoreLocationReverseGeocoder {
    func reverseGeocode(location: CLLocation, timeoutSeconds: TimeInterval) -> GeocodedLocation {
        if #unavailable(macOS 26.0) {
            let geocoder = CLGeocoder()
            var placemark: CLPlacemark?
            var latestError: Error?
            var completed = false
            geocoder.reverseGeocodeLocation(location) { placemarks, error in
                placemark = placemarks?.first
                latestError = error
                completed = true
            }
            let deadline = Date().addingTimeInterval(timeoutSeconds)
            while !completed && Date() < deadline {
                RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
            }
            if !completed {
                geocoder.cancelGeocode()
            }
            if let placemark {
                return geocodedLocation(from: placemark, error: nil)
            }
            return emptyGeocodedLocation(
                error: latestError?.localizedDescription ?? "geocode_timed_out"
            )
        }
        return emptyGeocodedLocation(error: "legacy_geocoder_unavailable")
    }
}

func currentWifiSnapshot(
    authorizer: LocationAuthorizer,
    locationTimeoutSeconds: TimeInterval?,
    geocodeTimeoutSeconds: TimeInterval?
) -> WifiSnapshot {
    let status = authorizer.authorizationStatus()
    let authorized = isAuthorized(status)
    let location = locationTimeoutSeconds.flatMap { authorizer.currentLocation(timeoutSeconds: $0) }
    let geocodedLocation = location.flatMap { currentLocation in
        geocodeTimeoutSeconds.map {
            ReverseGeocoder().reverseGeocode(location: currentLocation, timeoutSeconds: $0)
        }
    }

    guard authorized else {
        return WifiSnapshot(
            authorized: false,
            authorizationStatus: statusName(status),
            interface: nil,
            ssid: nil,
            bssid: nil,
            signalDbm: nil,
            noiseDbm: nil,
            latitude: nil,
            longitude: nil,
            locationAccuracyM: nil,
            locationError: authorizer.locationErrorDescription(),
            geocodedLocation: nil,
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
            latitude: location?.coordinate.latitude,
            longitude: location?.coordinate.longitude,
            locationAccuracyM: location?.horizontalAccuracy,
            locationError: authorizer.locationErrorDescription(),
            geocodedLocation: geocodedLocation,
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
        latitude: location?.coordinate.latitude,
        longitude: location?.coordinate.longitude,
        locationAccuracyM: location?.horizontalAccuracy,
        locationError: authorizer.locationErrorDescription(),
        geocodedLocation: geocodedLocation,
        error: nil
    )
}

func geocodedLocation(from placemark: CLPlacemark, error: String?) -> GeocodedLocation {
    return GeocodedLocation(
        state: geocodedLocationState(from: placemark),
        name: nonEmpty(placemark.name),
        country: nonEmpty(placemark.country),
        isoCountryCode: nonEmpty(placemark.isoCountryCode),
        timeZone: nonEmpty(placemark.timeZone?.identifier),
        administrativeArea: nonEmpty(placemark.administrativeArea),
        subAdministrativeArea: nonEmpty(placemark.subAdministrativeArea),
        postalCode: nonEmpty(placemark.postalCode),
        locality: nonEmpty(placemark.locality),
        subLocality: nonEmpty(placemark.subLocality),
        thoroughfare: nonEmpty(placemark.thoroughfare),
        subThoroughfare: nonEmpty(placemark.subThoroughfare),
        areasOfInterest: nonEmptyUnique((placemark.areasOfInterest ?? []).map { Optional($0) }),
        ocean: nonEmpty(placemark.ocean),
        inlandWater: nonEmpty(placemark.inlandWater),
        error: error
    )
}

@available(macOS 26.0, *)
func geocodedLocation(from mapItem: MKMapItem, error: String?) -> GeocodedLocation {
    let representations = mapItem.addressRepresentations
    let fullAddress = representations?.fullAddress(includingRegion: true, singleLine: true)
        ?? mapItem.address?.fullAddress
    let locality = representations?.cityName
    let country = representations?.regionName
    return GeocodedLocation(
        state: nonEmpty(fullAddress) ?? geocodedLocationState(
            name: mapItem.name,
            locality: locality,
            country: country
        ),
        name: nonEmpty(mapItem.name),
        country: nonEmpty(country),
        isoCountryCode: nil,
        timeZone: nonEmpty(mapItem.timeZone?.identifier),
        administrativeArea: nil,
        subAdministrativeArea: nil,
        postalCode: nil,
        locality: nonEmpty(locality),
        subLocality: nil,
        thoroughfare: nil,
        subThoroughfare: nil,
        areasOfInterest: [],
        ocean: nil,
        inlandWater: nil,
        error: error
    )
}

func emptyGeocodedLocation(error: String?) -> GeocodedLocation {
    return GeocodedLocation(
        state: nil,
        name: nil,
        country: nil,
        isoCountryCode: nil,
        timeZone: nil,
        administrativeArea: nil,
        subAdministrativeArea: nil,
        postalCode: nil,
        locality: nil,
        subLocality: nil,
        thoroughfare: nil,
        subThoroughfare: nil,
        areasOfInterest: [],
        ocean: nil,
        inlandWater: nil,
        error: error
    )
}

func geocodedLocationState(from placemark: CLPlacemark) -> String? {
    let parts = nonEmptyUnique([
        placemark.name,
        placemark.locality,
        placemark.administrativeArea,
        placemark.country,
    ])
    if parts.isEmpty {
        return nil
    }
    return parts.joined(separator: ", ")
}

func geocodedLocationState(name: String?, locality: String?, country: String?) -> String? {
    let parts = nonEmptyUnique([name, locality, country])
    if parts.isEmpty {
        return nil
    }
    return parts.joined(separator: ", ")
}

func nonEmpty(_ value: String?) -> String? {
    guard let value else {
        return nil
    }
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty ? nil : trimmed
}

func nonEmptyUnique(_ values: [String?]) -> [String] {
    var seen = Set<String>()
    var result: [String] = []
    for value in values {
        guard let text = nonEmpty(value) else {
            continue
        }
        let key = text.lowercased()
        if seen.contains(key) {
            continue
        }
        seen.insert(key)
        result.append(text)
    }
    return result
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

func printJson<T: Encodable>(_ value: T, outputPath: String?) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    do {
        let data = try encoder.encode(value)
        if let outputPath {
            try data.write(to: URL(fileURLWithPath: outputPath), options: [.atomic])
        } else {
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        }
    } catch {
        let fallback = #"{"authorized":false,"authorization_status":"unknown","error":"json_encode_failed"}"#
        print(fallback)
    }
}

func printUsage() {
    print("usage: HaMqttAgentWifiHelper [--json|--authorize|--reverse-geocode] [--location-timeout SECONDS] [--latitude LATITUDE] [--longitude LONGITUDE] [--geocode-timeout SECONDS] [--output PATH]")
}

let rawArguments = Array(CommandLine.arguments.dropFirst())
let arguments = Set(rawArguments)
let application = NSApplication.shared
if arguments.contains("--authorize") {
    application.setActivationPolicy(.regular)
    application.activate(ignoringOtherApps: true)
} else {
    application.setActivationPolicy(.accessory)
}
application.finishLaunching()
let authorizer = LocationAuthorizer()

if arguments.contains("--help") || arguments.contains("-h") {
    printUsage()
    exit(0)
}

if arguments.contains("--reverse-geocode") {
    guard let latitude = coordinateArgument("--latitude", rawArguments),
          let longitude = coordinateArgument("--longitude", rawArguments)
    else {
        printUsage()
        exit(2)
    }
    let location = CLLocation(latitude: latitude, longitude: longitude)
    let geocodedLocation = ReverseGeocoder().reverseGeocode(
        location: location,
        timeoutSeconds: geocodeTimeout(rawArguments) ?? 3
    )
    printJson(
        GeocodedLocationResponse(geocodedLocation: geocodedLocation),
        outputPath: outputPath(rawArguments)
    )
    exit(0)
}

if arguments.contains("--authorize") {
    _ = authorizer.requestAuthorization(timeoutSeconds: 30)
    printJson(
        currentWifiSnapshot(
            authorizer: authorizer,
            locationTimeoutSeconds: locationTimeout(rawArguments),
            geocodeTimeoutSeconds: geocodeTimeout(rawArguments)
        ),
        outputPath: outputPath(rawArguments)
    )
    exit(0)
}

if arguments.isEmpty || arguments.contains("--json") {
    printJson(
        currentWifiSnapshot(
            authorizer: authorizer,
            locationTimeoutSeconds: locationTimeout(rawArguments),
            geocodeTimeoutSeconds: geocodeTimeout(rawArguments)
        ),
        outputPath: outputPath(rawArguments)
    )
    exit(0)
}

printUsage()
exit(2)

func locationTimeout(_ arguments: [String]) -> TimeInterval? {
    guard let index = arguments.firstIndex(of: "--location-timeout") else {
        return nil
    }
    let valueIndex = arguments.index(after: index)
    guard valueIndex < arguments.endIndex else {
        return nil
    }
    return TimeInterval(arguments[valueIndex])
}

func geocodeTimeout(_ arguments: [String]) -> TimeInterval? {
    guard let index = arguments.firstIndex(of: "--geocode-timeout") else {
        return nil
    }
    let valueIndex = arguments.index(after: index)
    guard valueIndex < arguments.endIndex else {
        return nil
    }
    return TimeInterval(arguments[valueIndex])
}

func coordinateArgument(_ name: String, _ arguments: [String]) -> Double? {
    guard let index = arguments.firstIndex(of: name) else {
        return nil
    }
    let valueIndex = arguments.index(after: index)
    guard valueIndex < arguments.endIndex else {
        return nil
    }
    return Double(arguments[valueIndex])
}

func outputPath(_ arguments: [String]) -> String? {
    guard let index = arguments.firstIndex(of: "--output") else {
        return nil
    }
    let valueIndex = arguments.index(after: index)
    guard valueIndex < arguments.endIndex else {
        return nil
    }
    return arguments[valueIndex]
}
