import Foundation

enum APIError: LocalizedError {
    case badURL(String)
    case http(Int, String)
    case notFound

    var errorDescription: String? {
        switch self {
        case .badURL(let s): return "Bad server address: \(s)"
        case .http(let code, let body): return "Server said \(code): \(body)"
        case .notFound: return "Not found on the server"
        }
    }
}

/// HTTP client for the laptop backend (contract owned by agent A).
struct API: Sendable {
    let base: URL

    init(baseString: String) throws {
        var s = baseString.trimmingCharacters(in: .whitespacesAndNewlines)
        if !s.contains("://") { s = "http://" + s }
        while s.hasSuffix("/") { s.removeLast() }
        if let u = URL(string: s), u.port == nil, u.path.isEmpty, u.scheme == "http" { s += ":8000" }
        guard let url = URL(string: s), url.host != nil else { throw APIError.badURL(baseString) }
        base = url
    }

    private static let fast: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.requestCachePolicy = .reloadIgnoringLocalCacheData
        c.timeoutIntervalForRequest = 5
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()

    /// Grading and compose run a local model; a cold start can take 20 s or more.
    private static let slow: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.requestCachePolicy = .reloadIgnoringLocalCacheData
        c.timeoutIntervalForRequest = 60
        return URLSession(configuration: c)
    }()

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    /// Resolve "/static/content/..." or a content-relative "audio/x.m4a" against the server.
    func url(_ path: String) -> URL? {
        if path.hasPrefix("http://") || path.hasPrefix("https://") { return URL(string: path) }
        let p = path.hasPrefix("/") ? path : "/static/content/" + path
        return URL(string: p, relativeTo: base)?.absoluteURL
    }

    private func endpoint(_ path: String, query: [URLQueryItem] = []) -> URL {
        var c = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { c.queryItems = query }
        return c.url!
    }

    private func send(_ req: URLRequest, slow: Bool = false) async throws -> Data {
        let (data, resp) = try await (slow ? Self.slow : Self.fast).data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 404 { throw APIError.notFound }
        guard (200..<300).contains(code) else {
            throw APIError.http(code, String(decoding: data.prefix(200), as: UTF8.self))
        }
        return data
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = [], as: T.Type = T.self) async throws -> T {
        let data = try await send(URLRequest(url: endpoint(path, query: query)))
        return try Self.decoder.decode(T.self, from: data)
    }

    /// 404 -> nil (the backend uses it for "no session / no result yet").
    private func getOptional<T: Decodable>(_ path: String, as: T.Type = T.self) async throws -> T? {
        do { return try await get(path, as: T.self) } catch APIError.notFound { return nil }
    }

    private func postJSON<Body: Encodable, T: Decodable>(_ path: String, _ body: Body, slow: Bool = false, as: T.Type = T.self) async throws -> T {
        var req = URLRequest(url: endpoint(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try Self.encoder.encode(body)
        return try Self.decoder.decode(T.self, from: try await send(req, slow: slow))
    }

    private func postMultipart<T: Decodable>(_ path: String, fields: [String: String], jpeg: Data, slow: Bool) async throws -> T {
        let boundary = "worn-\(UUID().uuidString)"
        var body = Data()
        func append(_ s: String) { body.append(Data(s.utf8)) }
        for (name, value) in fields.sorted(by: { $0.key < $1.key }) {
            append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n")
        }
        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"image\"; filename=\"page.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n")
        body.append(jpeg)
        append("\r\n--\(boundary)--\r\n")
        var req = URLRequest(url: endpoint(path))
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        return try Self.decoder.decode(T.self, from: try await send(req, slow: slow))
    }

    // MARK: endpoints

    func health() async throws -> Health { try await get("health") }
    func content() async throws -> [Lesson] { try await get("content", as: ContentResponse.self).langs }
    func currentSession() async throws -> SessionState? { try await getOptional("session") }

    @discardableResult
    func startSession(_ body: SessionRequest) async throws -> SessionState { try await postJSON("session", body) }

    func grade(jpeg: Data, char: String, lang: String) async throws -> GradeResult {
        try await postMultipart("grade", fields: ["char": char, "lang": lang], jpeg: jpeg, slow: true)
    }

    func strokeMatch(jpeg: Data, char: String, strokeIndex: Int) async throws -> StrokeMatch {
        try await postMultipart("stroke-match", fields: ["char": char, "stroke_index": String(strokeIndex)], jpeg: jpeg, slow: false)
    }

    func compose(text: String, lang: String) async throws -> ComposeResult {
        struct Body: Encodable { let text: String; let lang: String }
        return try await postJSON("compose", Body(text: text, lang: lang), slow: true)
    }

    func name(_ text: String) async throws -> NameResponse {
        try await get("name", query: [URLQueryItem(name: "text", value: text)])
    }

    func journal(lang: String) async throws -> JournalResponse {
        try await get("journal", query: [URLQueryItem(name: "lang", value: lang)])
    }

    func review() async throws -> ReviewResponse { try await get("review") }

    func event(_ e: EventBody) async throws {
        var req = URLRequest(url: endpoint("event"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try Self.encoder.encode(e)
        _ = try await send(req)
    }

    /// Any file under /static/content (stroke data, reactions.json, milestones.json).
    func staticFile(_ path: String) async throws -> Data {
        guard let u = url(path) else { throw APIError.badURL(path) }
        return try await send(URLRequest(url: u))
    }
}
