import Foundation

enum APIError: LocalizedError {
    case badURL(String)
    case http(Int, String)

    var errorDescription: String? {
        switch self {
        case .badURL(let s): return "Bad server address: \(s)"
        case .http(let code, let body): return "Server said \(code): \(body)"
        }
    }
}

/// Thin HTTP client for the laptop backend. Every device on the venue wifi talks to the same server.
struct API {
    let base: URL

    init(baseString: String) throws {
        var s = baseString.trimmingCharacters(in: .whitespacesAndNewlines)
        if !s.contains("://") { s = "http://" + s }
        while s.hasSuffix("/") { s.removeLast() }
        // Bare IP with no port -> assume the backend's :8000.
        if let u = URL(string: s), u.port == nil, u.path.isEmpty { s += ":8000" }
        guard let url = URL(string: s), url.host != nil else { throw APIError.badURL(baseString) }
        base = url
    }

    private static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.requestCachePolicy = .reloadIgnoringLocalCacheData
        c.timeoutIntervalForRequest = 5
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()

    /// Separate session for /grade: the local vision model can take 20s+ on a cold start.
    private static let slowSession: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 60
        return URLSession(configuration: c)
    }()

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    /// Resolve a server-relative path like "/static/content/audio/mandarin/hello.m4a".
    func url(_ path: String) -> URL? {
        if path.hasPrefix("http://") || path.hasPrefix("https://") { return URL(string: path) }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }

    private func send(_ req: URLRequest, slow: Bool = false) async throws -> Data? {
        let (data, resp) = try await (slow ? Self.slowSession : Self.session).data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 404 { return nil }  // backend uses 404 for "no session / no result yet"
        guard (200..<300).contains(code) else {
            throw APIError.http(code, String(decoding: data.prefix(200), as: UTF8.self))
        }
        return data
    }

    private func get<T: Decodable>(_ path: String) async throws -> T? {
        guard let data = try await send(URLRequest(url: base.appendingPathComponent(path))) else { return nil }
        return try Self.decoder.decode(T.self, from: data)
    }

    func health() async throws -> Health? { try await get("health") }
    func content() async throws -> [Lesson] { (try await get("content") as ContentResponse?)?.langs ?? [] }
    func currentSession() async throws -> SessionState? { try await get("session") }
    func result() async throws -> GradeResult? { try await get("session/result") }

    func startSession(_ body: SessionRequest) async throws -> SessionState {
        var req = URLRequest(url: base.appendingPathComponent("session"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try Self.encoder.encode(body)
        guard let data = try await send(req) else { throw APIError.http(404, "unknown lesson") }
        return try Self.decoder.decode(SessionState.self, from: data)
    }

    /// Backup path: grade a photo taken with the phone's camera (same endpoint the glasses use).
    func grade(jpeg: Data, char: String, lang: String) async throws -> GradeResult {
        let boundary = "worn-\(UUID().uuidString)"
        var body = Data()
        func field(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".data(using: .utf8)!)
        }
        field("char", char)
        field("lang", lang)
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"image\"; filename=\"phone.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(jpeg)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        var req = URLRequest(url: base.appendingPathComponent("grade"))
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        guard let data = try await send(req, slow: true) else { throw APIError.http(404, "grade endpoint missing") }
        return try Self.decoder.decode(GradeResult.self, from: data)
    }
}
